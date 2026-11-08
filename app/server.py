"""Loopback-only HTTP entry point for the local project manager."""

from __future__ import annotations

import argparse
import json
import mimetypes
import secrets
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    from .backend import AppError, MAX_BACKUP_BYTES, Store
except ImportError:
    from backend import AppError, MAX_BACKUP_BYTES, Store

try:
    from .export_xlsx import export_workbook
except ImportError:
    from export_xlsx import export_workbook


class LocalServer(HTTPServer):
    allow_reuse_address = True

    def server_close(self):
        super().server_close()
        store = getattr(self, "store", None)
        if store is not None:
            store.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "QualityNodes"

    def log_message(self, format, *args):
        return

    def _headers(self, status, content_type, size, extras=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'")
        for key, value in (extras or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _json(self, value, status=200):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def _check_host(self):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in allowed:
            raise AppError("请通过本机程序地址访问。", 403)
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in allowed}:
            raise AppError("这个请求并非来自本地程序页面。", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise AppError("这个请求并非来自本地程序页面。", 403)

    def _dispatch(self):
        self._check_host()
        path = unquote(urlsplit(self.path).path)
        if self.command == "GET":
            if path == "/api/state":
                return self._json(self.server.store.state())
            if path == "/api/backup":
                payload = self.server.store.backup_bytes()
                self._headers(200, "application/vnd.sqlite3", len(payload), {"Content-Disposition": 'attachment; filename="quality-nodes-backup.sqlite3"'})
                return self.wfile.write(payload)
            parts = [p for p in path.split("/") if p]
            if len(parts) == 4 and parts[:2] == ["api", "groups"] and parts[3] == "export":
                with self.server.store.lock:
                    group = self.server.store._get_group(parts[2])
                    payload = export_workbook(group)
                self._headers(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", len(payload),
                              {"Content-Disposition": 'attachment; filename="project-progress.xlsx"'})
                return self.wfile.write(payload)
            if path.startswith("/api/"):
                raise AppError("没有找到这个地址。", 404)
            relative = path.lstrip("/") or "index.html"
            root = self.server.web_root.resolve()
            target = (root / relative).resolve()
            if root not in target.parents or not target.is_file():
                raise AppError("没有找到这个页面。", 404)
            payload = target.read_bytes()
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if kind.startswith("text/") or kind == "application/javascript":
                kind += "; charset=utf-8"
            self._headers(200, kind, len(payload))
            return self.wfile.write(payload)
        if self.command not in {"POST", "PUT", "DELETE"} or not path.startswith("/api/"):
            raise AppError("这个操作不受支持。", 405)
        token = self.headers.get("X-App-Token", "")
        if not secrets.compare_digest(token, self.server.store.csrf_token):
            raise AppError("页面连接已更新，请刷新后重试。", 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise AppError("请求长度格式不正确。") from None
        limit = MAX_BACKUP_BYTES if path == "/api/restore" else 2 * 1024 * 1024
        if not 0 <= length <= limit:
            raise AppError("提交的内容过大。", 413)
        raw = self.rfile.read(length)
        if path == "/api/restore" and self.command == "POST":
            return self._json(self.server.store.restore_bytes(raw))
        if raw and self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise AppError("请以 JSON 格式提交内容。", 415)
        try:
            value = json.loads(raw) if raw else {}
        except (ValueError, UnicodeDecodeError):
            raise AppError("提交的内容无法读取，请重试。") from None
        parts = [p for p in path.removeprefix("/api/").split("/") if p]
        return self._json(self.server.store.mutate(self.command, parts, value))

    def _safe_dispatch(self):
        try:
            self._dispatch()
        except AppError as exc:
            self._json({"error": str(exc)}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._json({"error": "操作未完成，请稍后重试。原有记录保持不变。"}, 500)

    do_GET = _safe_dispatch
    do_POST = _safe_dispatch
    do_PUT = _safe_dispatch
    do_DELETE = _safe_dispatch


def create_server(host="127.0.0.1", port=0, data_dir=None, presets_path=None):
    if host != "127.0.0.1":
        raise ValueError("服务仅允许在本机运行。")
    server = LocalServer((host, port), Handler)
    try:
        server.store = Store(data_dir=data_dir, presets_path=presets_path)
    except Exception:
        HTTPServer.server_close(server)
        raise
    server.web_root = Path(__file__).resolve().parent / "web"
    return server


def main():
    parser = argparse.ArgumentParser(description="启动本地项目材料管理工具")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    server = create_server(port=args.port, data_dir=args.data_dir)
    print(f"本地地址：http://127.0.0.1:{server.server_port}", flush=True)
    print(f"数据目录：{server.store.data_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
