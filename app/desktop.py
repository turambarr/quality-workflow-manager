"""Launch the local workspace in a desktop window or the default browser."""

import argparse
import logging
import sys
import threading
import webbrowser

from server import create_server


def main(argv=None):
    parser = argparse.ArgumentParser(description="启动质量节点管理工具")
    parser.add_argument("--browser", action="store_true", help="使用默认浏览器打开")
    parser.add_argument("--data-dir", help="指定本地数据目录")
    parser.add_argument("--port", type=int, default=0, help="指定本地端口，默认自动分配")
    args = parser.parse_args(argv)

    server = create_server(port=args.port, data_dir=args.data_dir)
    url = "http://127.0.0.1:{}/".format(server.server_address[1])
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        if not args.browser:
            try:
                import webview
            except ImportError:
                webview = None
            if webview is not None:
                webview.settings["ALLOW_DOWNLOADS"] = True
                webview.create_window(
                    "质量节点", url, width=1440, height=940,
                    min_size=(900, 640), background_color="#f8f6f1",
                )
                webview.start()
                return 0

        webbrowser.open(url)
        print("质量节点已启动：{}".format(url), flush=True)
        print("请保持此窗口打开。退出工具时，可关闭此窗口或按 Control+C。", flush=True)
        while worker.is_alive():
            worker.join(timeout=0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logging.exception("工具启动失败")
        if getattr(sys, "frozen", False):
            try:
                import tkinter
                from tkinter import messagebox
                root = tkinter.Tk()
                root.withdraw()
                messagebox.showerror("质量节点", "无法启动工具：{}".format(exc))
                root.destroy()
            except Exception:
                pass
        raise
