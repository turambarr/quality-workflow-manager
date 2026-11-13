"""Local project records, workflow templates, and immutable saved revisions."""

from __future__ import annotations

import copy
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path


STATUSES = ("未开始", "进行中", "待检查", "需修改", "已完成", "不涉及")
SCHEMA_VERSION = "7"
MAX_BACKUP_BYTES = 64 * 1024 * 1024


class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_id():
    return uuid.uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def default_data_dir():
    if os.environ.get("QUALITY_DATA_DIR"):
        return Path(os.environ["QUALITY_DATA_DIR"]).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "质量节点"


def text(value, field, required=False, limit=20000):
    if not isinstance(value, str):
        raise AppError(f"{field}需要填写文字。")
    value = value.strip()
    if required and not value:
        raise AppError(f"请填写{field}。")
    if len(value) > limit:
        raise AppError(f"{field}最多填写 {limit} 个字符。")
    return value


def object_value(value, field):
    if not isinstance(value, dict):
        raise AppError(f"{field}格式不正确。")
    return value


def basic_info(value):
    object_value(value, "基本信息")
    if len(value) > 80:
        raise AppError("基本信息最多保留 80 项。")
    return {text(k, "信息名称", True, 200): text(v, "信息内容", limit=5000) for k, v in value.items()}


def coordinate(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not -200000 <= value <= 200000:
        raise AppError("节点位置需要在有效范围内。")
    return round(value, 2)


def parent_identifier(value):
    if value is None or value == "":
        return None
    return text(value, "父节点编号", True, 200)


def sequence_index(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000000:
        raise AppError("节点顺序需要填写有效的非负整数。")
    return value


def planned_date(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise AppError("计划日期需要使用年-月-日格式。")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
        if parsed.isoformat() != value:
            raise ValueError
    except ValueError:
        raise AppError("请填写有效的计划日期，例如 2026-11-07。") from None
    return value


def boolean(value, label):
    if not isinstance(value, bool):
        raise AppError(f"{label}格式不正确。")
    return value


def document_templates(value):
    if not isinstance(value, list) or len(value) > 200:
        raise AppError("每个节点最多添加 200 个文档模板。")
    result, ids = [], set()
    for item in value:
        object_value(item, "文档模板")
        ident = text(item.get("id") or new_id(), "模板编号", True, 200)
        if ident in ids:
            raise AppError("同一节点内的文档模板编号不能重复。")
        ids.add(ident)
        result.append({"id": ident, "name": text(item.get("name", ""), "模板名称", True, 500)})
    return result


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS groups (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, teacher TEXT NOT NULL, description TEXT NOT NULL,
 basic_info TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
 id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES groups(id),
 title TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL,
 x REAL NOT NULL, y REAL NOT NULL, templates TEXT NOT NULL,
 archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS edges (
 id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES groups(id),
 source TEXT NOT NULL REFERENCES nodes(id), target TEXT NOT NULL REFERENCES nodes(id),
 UNIQUE(group_id, source, target), CHECK(source != target)
);
CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(id),
 version INTEGER NOT NULL CHECK(version > 0), snapshot TEXT NOT NULL,
 UNIQUE(node_id, version)
);
CREATE TABLE IF NOT EXISTS templates (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
 nodes TEXT NOT NULL, edges TEXT NOT NULL, is_preset INTEGER NOT NULL DEFAULT 0
);
CREATE TRIGGER IF NOT EXISTS immutable_record_update BEFORE UPDATE ON records
BEGIN SELECT RAISE(ABORT, 'Saved records cannot be changed'); END;
CREATE TRIGGER IF NOT EXISTS immutable_record_delete BEFORE DELETE ON records
BEGIN SELECT RAISE(ABORT, 'Saved records cannot be deleted'); END;
"""


class Store:
    def __init__(self, data_dir=None, presets_path=None):
        self.data_dir = Path(data_dir).expanduser() if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "projects.sqlite3"
        self.lock = threading.RLock()
        self.csrf_token = secrets.token_urlsafe(32)
        self._connect()
        self.db.executescript(SCHEMA)
        with self.db:
            self._drop_legacy_triggers(self.db)
        existing = self.db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        previous = existing[0] if existing else None
        if existing and existing[0] not in ("1", "2", "3", "4", "5", "6", SCHEMA_VERSION):
            self.db.close()
            raise AppError("数据库版本与当前程序不兼容。", 409)
        if existing and existing[0] in ("1", "2", "3", "4", "5", "6"):
            self._save_automatic_backup("升级前")
        self._migrate_database(self.db)
        preset_file = Path(presets_path) if presets_path else Path(__file__).resolve().parent / "presets.json"
        preset = json.loads(preset_file.read_text(encoding="utf-8")) if preset_file.is_file() else None
        seeded = self.db.execute("SELECT value FROM metadata WHERE key='initialized'").fetchone()
        if seeded and previous != SCHEMA_VERSION and preset:
            # 旧库升级：补齐新增的内置分级模板；内置模板改过名的，跟着改名。
            with self.db:
                self._ensure_builtin_folders(preset)
                self._ensure_builtin_templates(preset)
        if not seeded and preset:
            with self.db:
                self._seed(preset)
                self.db.execute("INSERT INTO metadata VALUES ('initialized','1')")

    def _connect(self):
        self.db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")

    def close(self):
        self.db.close()

    @staticmethod
    def _drop_legacy_triggers(db):
        # SCHEMA 里的旧触发器会在每次启动时被 IF NOT EXISTS 重新建出来，必须先清掉，
        # 否则“同一天再次保存”会被旧触发器拦住。
        db.execute("DROP TRIGGER IF EXISTS immutable_record_update")
        db.execute("DROP TRIGGER IF EXISTS immutable_record_delete")

    @staticmethod
    def _migrate_database(db):
        version_row = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        version = version_row[0] if version_row else "1"
        if version not in ("1", "2", "3", "4", "5", "6", SCHEMA_VERSION):
            raise AppError("数据库版本与当前程序不兼容。", 409)
        if version == SCHEMA_VERSION:
            return
        with db:
            if version == "1":
                db.execute("ALTER TABLE nodes ADD COLUMN parent_id TEXT")
                db.execute("ALTER TABLE nodes ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0")
                db.execute("ALTER TABLE nodes ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
                db.execute("ALTER TABLE nodes ADD COLUMN planned_date TEXT")
                for group in db.execute("SELECT id FROM groups").fetchall():
                    for index, node in enumerate(db.execute("SELECT id FROM nodes WHERE group_id=? ORDER BY rowid", (group[0],)).fetchall()):
                        db.execute("UPDATE nodes SET order_index=? WHERE id=?", (index, node[0]))
                for row in db.execute("SELECT id,nodes FROM templates").fetchall():
                    nodes = json.loads(row[1])
                    for index, node in enumerate(nodes):
                        node.setdefault("parent_id", None)
                        node.setdefault("order_index", index)
                        node.setdefault("planned_date", None)
                        node.pop("favorite", None)
                    db.execute("UPDATE templates SET nodes=? WHERE id=?", (encode(nodes), row[0]))
            if version in ("1", "2"):
                db.execute(
                    "CREATE TABLE IF NOT EXISTS folders ("
                    "id TEXT PRIMARY KEY, name TEXT NOT NULL,"
                    " order_index INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"
                )
                db.execute("ALTER TABLE groups ADD COLUMN folder_id TEXT")
            if version in ("1", "2", "3"):
                db.execute("ALTER TABLE groups ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            # 版本 5：项目组不再单独命名，直接用老师姓名作名称；原来的老师字段改为对接学生。
            if version in ("1", "2", "3", "4"):
                db.execute("UPDATE groups SET name=teacher, teacher='' WHERE TRIM(teacher)<>''")
            # 版本 6：一条记录对应一个检查日期，同一天再次保存时更新当天的记录。
            if version in ("1", "2", "3", "4", "5"):
                Store._migrate_records_to_days(db)
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('schema_version', ?)", (SCHEMA_VERSION,))

    @staticmethod
    def _migrate_records_to_days(db):
        """把旧记录整理成“每个节点每天一条”，并允许当天记录被再次保存覆盖。"""
        for trigger in ("immutable_record_update", "immutable_record_delete", "record_update_guard", "record_delete_guard"):
            db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        columns = {row[1] for row in db.execute("PRAGMA table_info(records)")}
        if "day" not in columns:
            db.execute("ALTER TABLE records ADD COLUMN day TEXT")
        rows = db.execute("SELECT id,node_id,version,snapshot FROM records ORDER BY node_id, version, rowid").fetchall()
        parsed, keep = [], {}
        for rid, nid, version, snapshot in rows:
            record = json.loads(snapshot)
            day = str(record.get("created_at") or "")[:10] or datetime.now().astimezone().date().isoformat()
            parsed.append((rid, nid, version, record, day))
            keep[(nid, day)] = rid  # 同一天里版本更大的（后保存的）留下
        kept = set(keep.values())
        for rid, nid, version, record, day in parsed:
            if rid not in kept:
                db.execute("DELETE FROM records WHERE id=?", (rid,))
        counters = {}
        for rid, nid, version, record, day in parsed:
            if rid not in kept:
                continue
            counters[nid] = counters.get(nid, 0) + 1
            record["version"] = counters[nid]
            record["day"] = day
            db.execute("UPDATE records SET version=?, day=?, snapshot=? WHERE id=?",
                       (record["version"], day, encode(record), rid))
        db.execute(
            "CREATE TRIGGER IF NOT EXISTS record_update_guard BEFORE UPDATE ON records "
            "WHEN OLD.day <> date('now','localtime') BEGIN SELECT RAISE(ABORT, '历史记录不可修改'); END"
        )
        db.execute(
            "CREATE TRIGGER IF NOT EXISTS record_delete_guard BEFORE DELETE ON records "
            "BEGIN SELECT RAISE(ABORT, 'Saved records cannot be deleted'); END"
        )

    def _save_automatic_backup(self, prefix):
        folder = self.data_dir / "backups"
        folder.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = folder / f"{prefix}-{stamp}.sqlite3"
        target.write_bytes(self.backup_bytes())
        return target

    RENAMED_TEMPLATES = {"重要级 · 项目组": "项目组管理 · 重要级", "重要级 · 学院": "学院管理 · 重要级"}

    def _ensure_builtin_folders(self, preset):
        for index, folder in enumerate(preset.get("folders", [])):
            name = folder.get("name")
            if not name or self.db.execute("SELECT 1 FROM folders WHERE name=?", (name,)).fetchone():
                continue
            self.db.execute("INSERT INTO folders (id,name,order_index,created_at) VALUES (?,?,?,?)",
                            (folder.get("id") or new_id(), name, index, now()))

    def _ensure_builtin_templates(self, preset):
        for entry in preset.get("templates", []):
            name = text(entry["name"], "分级模板名称", True, 200)
            found = self.db.execute("SELECT id FROM templates WHERE name=?", (name,)).fetchone()
            if not found:
                old_name = self.RENAMED_TEMPLATES.get(name)
                renamed = self.db.execute("SELECT id FROM templates WHERE name=?", (old_name,)).fetchone() if old_name else None
                if renamed:
                    self.db.execute("UPDATE templates SET name=? WHERE id=?", (name, renamed[0]))
                    found = renamed
            if found:
                continue
            nodes, edges = self._validate_flow(entry.get("nodes", []), entry.get("edges", []))
            self.db.execute("INSERT INTO templates VALUES (?,?,?,?,?,1)",
                            (entry.get("id") or new_id(), name,
                             text(entry.get("description", ""), "分级模板说明"), encode(nodes), encode(edges)))

    def _seed(self, preset):
        folder_ids = {}
        for entry in preset.get("folders", []):
            fid = entry.get("id") or new_id()
            self.db.execute("INSERT OR IGNORE INTO folders (id,name,order_index,created_at) VALUES (?,?,?,?)",
                            (fid, text(entry["name"], "文件夹名称", True, 200),
                             sequence_index(entry.get("order_index", 0)), entry.get("created_at", now())))
            folder_ids[entry["name"]] = fid
        for entry in preset.get("templates", []):
            nodes, edges = self._validate_flow(entry.get("nodes", []), entry.get("edges", []))
            self.db.execute("INSERT INTO templates VALUES (?,?,?,?,?,1)",
                            (entry.get("id") or new_id(), text(entry["name"], "分级模板名称", True, 200),
                             text(entry.get("description", ""), "分级模板说明"), encode(nodes), encode(edges)))
        for entry in preset.get("demo_groups", []):
            gid = entry.get("id") or new_id()
            self.db.execute("INSERT INTO groups (id,name,teacher,description,basic_info,is_demo,created_at,updated_at,folder_id) VALUES (?,?,?,?,?,1,?,?,?)", (
                gid, entry["name"], entry.get("teacher", ""), entry.get("description", ""),
                encode(entry.get("basic_info", {})), entry.get("created_at", now()), entry.get("updated_at", now()),
                folder_ids.get(entry.get("folder"))))
            nodes, edges = self._validate_flow(entry.get("nodes", []), entry.get("edges", []))
            originals = {n.get("id"): n for n in entry.get("nodes", [])}
            for node in nodes:
                self._insert_node(gid, node)
                for record in originals.get(node["id"], {}).get("records", []):
                    current = self._get_node(gid, node["id"])
                    payload = dict(record, expected_version=len(current["records"]))
                    self._append_record(gid, node["id"], payload, created_at=record.get("created_at"))
            for edge in edges:
                self.db.execute("INSERT INTO edges VALUES (?,?,?,?)", (edge["id"], gid, edge["source"], edge["target"]))

    def _validate_flow(self, nodes, edges):
        if not isinstance(nodes, list) or len(nodes) > 500:
            raise AppError("每套分级模板最多包含 500 个节点。")
        if not isinstance(edges, list) or len(edges) > 2000:
            raise AppError("流程连接数量超出范围。")
        result, ids = [], set()
        sibling_counts = {}
        for node in nodes:
            object_value(node, "节点")
            parent = parent_identifier(node.get("parent_id"))
            value = self._normalize_node(dict(node, order_index=node.get("order_index", sibling_counts.get(parent, 0))))
            value.pop("favorite", None)
            sibling_counts[parent] = sibling_counts.get(parent, 0) + 1
            if value["id"] in ids:
                raise AppError("流程节点编号不能重复。")
            ids.add(value["id"])
            result.append(value)
        self._validate_hierarchy(result)
        by_id = {node["id"]: node for node in result}
        edge_result, pairs, edge_ids = [], set(), set()
        for edge in edges:
            object_value(edge, "流程连接")
            source, target = edge.get("source"), edge.get("target")
            if source not in ids or target not in ids:
                raise AppError("流程连接需要指向现有节点。")
            if source == target or (source, target) in pairs:
                raise AppError("流程连接不能重复或指向节点自身。")
            if by_id[source]["parent_id"] != by_id[target]["parent_id"]:
                raise AppError("流程连接需要位于同一级流程中。")
            ident = text(edge.get("id") or new_id(), "连接编号", True, 200)
            if ident in edge_ids:
                raise AppError("流程连接编号不能重复。")
            edge_ids.add(ident)
            pairs.add((source, target))
            edge_result.append({"id": ident, "source": source, "target": target})
        return result, edge_result

    def _normalize_node(self, data):
        object_value(data, "节点")
        return {
            "id": text(data.get("id") or new_id(), "节点编号", True, 200),
            "title": text(data.get("title", ""), "节点名称", True, 300),
            "description": text(data.get("description", ""), "节点说明"),
            "category": text(data.get("category", ""), "节点分类", limit=200),
            "x": coordinate(data.get("x", 0)), "y": coordinate(data.get("y", 0)),
            "templates": document_templates(data.get("templates", [])),
            "archived": boolean(data.get("archived", False), "节点归档状态"),
            "parent_id": parent_identifier(data.get("parent_id")),
            "order_index": sequence_index(data.get("order_index", 0)),
            "favorite": boolean(data.get("favorite", False), "节点收藏状态"),
            "planned_date": planned_date(data.get("planned_date")),
        }

    def _validate_hierarchy(self, nodes):
        by_id = {node["id"]: node for node in nodes}
        for node in nodes:
            seen, current, depth = {node["id"]}, node, 1
            while current.get("parent_id") is not None:
                parent_id = current["parent_id"]
                if parent_id not in by_id:
                    raise AppError("父节点需要属于同一个项目组或分级模板。")
                if parent_id in seen:
                    raise AppError("节点不能放入自身或自己的子流程中。")
                seen.add(parent_id)
                current = by_id[parent_id]
                if not node.get("archived", False) and current.get("archived", False):
                    raise AppError("请先恢复父节点，再使用其中的子流程。")
                depth += 1
                if depth > 10:
                    raise AppError("流程最多支持 10 级节点。")

    def _descendant_ids(self, nodes, nid):
        result = {nid}
        changed = True
        while changed:
            changed = False
            for node in nodes:
                if node.get("parent_id") in result and node["id"] not in result:
                    result.add(node["id"])
                    changed = True
        return result

    def _remove_invalid_edges(self, gid):
        self.db.execute("""DELETE FROM edges WHERE group_id=? AND (
            source IN (SELECT id FROM nodes WHERE archived=1) OR
            target IN (SELECT id FROM nodes WHERE archived=1) OR
            (SELECT parent_id FROM nodes WHERE id=edges.source) IS NOT
            (SELECT parent_id FROM nodes WHERE id=edges.target))""", (gid,))

    def _insert_node(self, gid, node):
        self.db.execute("INSERT INTO nodes (id,group_id,title,description,category,x,y,templates,archived,parent_id,order_index,favorite,planned_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            node["id"], gid, node["title"], node["description"], node["category"],
            node["x"], node["y"], encode(node["templates"]), int(node["archived"]), node.get("parent_id"),
            node.get("order_index", 0), int(node.get("favorite", False)), node.get("planned_date")))

    def _get_group(self, gid):
        row = self.db.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
        if row is None:
            raise AppError("找不到这个项目组。", 404)
        result = dict(row)
        result["basic_info"] = json.loads(result["basic_info"])
        result["is_demo"] = bool(result["is_demo"])
        result["nodes"] = [self._row_node(x) for x in self.db.execute("SELECT * FROM nodes WHERE group_id=? ORDER BY rowid", (gid,))]
        result["edges"] = [dict(id=x["id"], source=x["source"], target=x["target"]) for x in self.db.execute("SELECT * FROM edges WHERE group_id=? ORDER BY rowid", (gid,))]
        return result

    def _row_node(self, row):
        node = dict(row)
        node.pop("group_id", None)
        node["templates"] = json.loads(node["templates"])
        node["archived"] = bool(node["archived"])
        node["favorite"] = bool(node["favorite"])
        node["records"] = []
        for row in self.db.execute("SELECT version, day, snapshot FROM records WHERE node_id=? ORDER BY version", (node["id"],)):
            record = json.loads(row["snapshot"])
            record["version"] = row["version"]
            record["day"] = row["day"] or str(record.get("created_at") or "")[:10]
            node["records"].append(record)
        return node

    def _get_node(self, gid, nid):
        row = self.db.execute("SELECT * FROM nodes WHERE group_id=? AND id=?", (gid, nid)).fetchone()
        if row is None:
            raise AppError("找不到这个流程节点。", 404)
        return self._row_node(row)

    def _touch(self, gid):
        self.db.execute("UPDATE groups SET updated_at=? WHERE id=?", (now(), gid))

    def state(self):
        with self.lock:
            groups = [self._get_group(r[0]) for r in self.db.execute("SELECT id FROM groups ORDER BY rowid")]
            folders = [dict(r) for r in self.db.execute("SELECT * FROM folders ORDER BY order_index, rowid")]
            templates = []
            for row in self.db.execute("SELECT * FROM templates ORDER BY rowid"):
                entry = dict(row)
                entry["nodes"], entry["edges"] = json.loads(entry["nodes"]), json.loads(entry["edges"])
                entry["is_preset"] = bool(entry["is_preset"])
                templates.append(entry)
            return {"groups": groups, "folders": folders, "templates": templates, "csrf_token": self.csrf_token,
                    "storage": {"path": str(self.path), "mode": "local", "schema_version": SCHEMA_VERSION}}

    def mutate(self, method, parts, data):
        object_value(data, "提交内容")
        with self.lock, self.db:
            self._mutate(method, parts, data)
        return self.state()

    def _mutate(self, method, parts, data):
        if parts and parts[0] == "folders":
            if parts == ["folders"] and method == "POST":
                return self._create_folder(data)
            if len(parts) == 2 and method == "PUT":
                return self._rename_folder(parts[1], data)
            if len(parts) == 2 and method == "DELETE":
                return self._delete_folder(parts[1])
            raise AppError("没有找到这个操作。", 404)
        if parts == ["groups"] and method == "POST":
            return self._create_group(data)
        if parts and parts[0] == "templates":
            return self._template_mutation(method, parts, data)
        if len(parts) < 2 or parts[0] != "groups":
            raise AppError("没有找到这个操作。", 404)
        gid = parts[1]
        group = self._get_group(gid)
        if len(parts) == 3 and method == "POST" and parts[2] == "organize":
            self._organize_group(gid, group, data)
            self._touch(gid)
            return
        if len(parts) == 3 and method == "POST" and parts[2] == "group-nodes":
            self._group_nodes(gid, group, data)
            self._touch(gid)
            return
        if len(parts) == 2 and method == "PUT":
            name = text(data.get("name", group["name"]), "老师姓名", True, 200)
            teacher = text(data.get("teacher", group["teacher"]), "对接学生姓名", limit=200)
            description = text(data.get("description", group["description"]), "项目组说明")
            info = basic_info(data.get("basic_info", group["basic_info"]))
            folder_id = self._folder_id(data.get("folder_id", group["folder_id"]))
            archived = 1 if boolean(data.get("archived", bool(group["archived"])), "归档状态") else 0
            self.db.execute("UPDATE groups SET name=?,teacher=?,description=?,basic_info=?,folder_id=?,archived=?,updated_at=? WHERE id=?", (name, teacher, description, encode(info), folder_id, archived, now(), gid))
            return
        if len(parts) == 2 and method == "DELETE":
            self._delete_group(gid)
            return
        if len(parts) == 3 and parts[2] == "nodes" and method == "POST":
            if len(group["nodes"]) >= 500:
                raise AppError("每个项目组最多保留 500 个节点。")
            parent = parent_identifier(data.get("parent_id"))
            siblings = [n for n in group["nodes"] if n["parent_id"] == parent and not n["archived"]]
            node = self._normalize_node(dict(data, id=new_id(), archived=False,
                order_index=data.get("order_index", max((n["order_index"] for n in siblings), default=-1) + 1)))
            self._validate_hierarchy(group["nodes"] + [node])
            self._insert_node(gid, node)
            self._touch(gid)
            return
        if len(parts) >= 4 and parts[2] == "nodes":
            nid = parts[3]
            node = self._get_node(gid, nid)
            if len(parts) == 5 and parts[4] == "records" and method == "POST":
                self._append_record(gid, nid, data)
                self._touch(gid)
                return
            if len(parts) == 4 and method == "DELETE":
                descendants = self._descendant_ids(group["nodes"], nid)
                for child_id in descendants:
                    self.db.execute("UPDATE nodes SET archived=1 WHERE id=?", (child_id,))
                self._remove_invalid_edges(gid)
                self._touch(gid)
                return
            if len(parts) == 4 and method == "PUT":
                if "archived" in data and not isinstance(data["archived"], bool):
                    raise AppError("节点归档状态格式不正确。")
                value = self._normalize_node(dict(node, **{k: v for k, v in data.items() if k != "id"}))
                descendants = self._descendant_ids(group["nodes"], nid) if "archived" in data else set()
                candidate_nodes = []
                for item in group["nodes"]:
                    candidate = dict(value) if item["id"] == nid else dict(item)
                    if candidate["id"] in descendants:
                        candidate["archived"] = value["archived"]
                    candidate_nodes.append(candidate)
                self._validate_hierarchy(candidate_nodes)
                self.db.execute("UPDATE nodes SET title=?,description=?,category=?,x=?,y=?,templates=?,archived=?,parent_id=?,order_index=?,favorite=?,planned_date=? WHERE id=?", (
                    value["title"], value["description"], value["category"], value["x"], value["y"], encode(value["templates"]), int(value["archived"]),
                    value["parent_id"], value["order_index"], int(value["favorite"]), value["planned_date"], nid))
                for child_id in descendants - {nid}:
                    self.db.execute("UPDATE nodes SET archived=? WHERE id=?", (int(value["archived"]), child_id))
                self._remove_invalid_edges(gid)
                self._touch(gid)
                return
        if len(parts) == 3 and parts[2] == "edges" and method == "POST":
            source, target = data.get("source"), data.get("target")
            if not isinstance(source, str) or not isinstance(target, str):
                raise AppError("请选择连接的起点与终点。")
            if source == target:
                raise AppError("节点不能连接到自身。")
            a, b = self._get_node(gid, source), self._get_node(gid, target)
            if a["archived"] or b["archived"]:
                raise AppError("请先恢复归档节点，再添加连接。")
            if a["parent_id"] != b["parent_id"]:
                raise AppError("只能连接同一级流程中的节点。")
            if self.db.execute("SELECT 1 FROM edges WHERE group_id=? AND source=? AND target=?", (gid, source, target)).fetchone():
                raise AppError("这两个节点之间已经存在相同方向的连接。")
            if len(group["edges"]) >= 2000:
                raise AppError("流程连接数量超出范围。")
            self.db.execute("INSERT INTO edges VALUES (?,?,?,?)", (new_id(), gid, source, target))
            self._touch(gid)
            return
        if len(parts) == 4 and parts[2] == "edges" and method == "DELETE":
            cursor = self.db.execute("DELETE FROM edges WHERE group_id=? AND id=?", (gid, parts[3]))
            if not cursor.rowcount:
                raise AppError("找不到这条流程连接。", 404)
            self._touch(gid)
            return
        raise AppError("没有找到这个操作。", 404)

    def _selected_siblings(self, group, data, complete=False):
        parent = parent_identifier(data.get("parent_id"))
        if parent is not None:
            matches = [n for n in group["nodes"] if n["id"] == parent and not n["archived"]]
            if not matches:
                raise AppError("请选择这个项目组中尚未归档的父节点。")
        selection = data.get("node_ids")
        if not isinstance(selection, list) or any(not isinstance(nid, str) for nid in selection):
            raise AppError("请选择需要整理的节点。")
        if len(selection) != len(set(selection)):
            raise AppError("节点列表中不能包含重复项。")
        siblings = [n for n in group["nodes"] if n["parent_id"] == parent and not n["archived"]]
        allowed = {n["id"] for n in siblings}
        if not set(selection).issubset(allowed):
            raise AppError("请只选择当前同一级流程中尚未归档的节点。")
        if complete and set(selection) != allowed:
            raise AppError("节点顺序需要包含当前同一级流程中的全部节点，请刷新后重试。", 409)
        if not complete and not selection:
            raise AppError("请至少选择一个节点。")
        return parent, selection, siblings

    def _organize_group(self, gid, group, data):
        parent, selection, siblings = self._selected_siblings(group, data, complete=True)
        for index, nid in enumerate(selection):
            self.db.execute("UPDATE nodes SET order_index=?,x=?,y=70 WHERE id=?", (index, 60 + index * 300, nid))
        self.db.execute("DELETE FROM edges WHERE group_id=? AND source IN (SELECT id FROM nodes WHERE group_id=? AND parent_id IS ?)", (gid, gid, parent))
        for source, target in zip(selection, selection[1:]):
            self.db.execute("INSERT INTO edges VALUES (?,?,?,?)", (new_id(), gid, source, target))

    def _group_nodes(self, gid, group, data):
        if len(group["nodes"]) >= 500:
            raise AppError("每个项目组最多保留 500 个节点。")
        parent, selection, siblings = self._selected_siblings(group, data)
        selected = set(selection)
        ordered_siblings = sorted(siblings, key=lambda n: n["order_index"])
        first = next(n for n in ordered_siblings if n["id"] in selected)
        container = self._normalize_node({"title": data.get("title", ""), "parent_id": parent,
            "order_index": first["order_index"], "x": first["x"], "y": first["y"]})
        candidate_nodes = copy.deepcopy(group["nodes"])
        for node in candidate_nodes:
            if node["id"] in selected:
                node["parent_id"] = container["id"]
        candidate_nodes.append(container)
        self._validate_hierarchy(candidate_nodes)
        self._insert_node(gid, container)
        for index, nid in enumerate(selection):
            self.db.execute("UPDATE nodes SET parent_id=?,order_index=?,x=?,y=70 WHERE id=?", (container["id"], index, 60 + index * 300, nid))
        remaining, inserted = [], False
        for node in ordered_siblings:
            if node["id"] in selected:
                if not inserted:
                    remaining.append(container["id"])
                    inserted = True
            else:
                remaining.append(node["id"])
        for index, nid in enumerate(remaining):
            self.db.execute("UPDATE nodes SET order_index=? WHERE id=?", (index, nid))
        edges, pairs = [], set()
        for edge in group["edges"]:
            source, target = edge["source"], edge["target"]
            if source in selected and target not in selected:
                source = container["id"]
            elif source not in selected and target in selected:
                target = container["id"]
            if (source, target) not in pairs:
                edges.append(dict(edge, source=source, target=target))
                pairs.add((source, target))
        self.db.execute("DELETE FROM edges WHERE group_id=?", (gid,))
        for edge in edges:
            self.db.execute("INSERT INTO edges VALUES (?,?,?,?)", (edge["id"], gid, edge["source"], edge["target"]))
        self._remove_invalid_edges(gid)

    def _delete_group(self, gid):
        saved = self.db.execute("SELECT COUNT(*) FROM records r JOIN nodes n ON n.id=r.node_id WHERE n.group_id=?", (gid,)).fetchone()[0]
        if saved:
            raise AppError("这个项目组已经有情况记录，不能删除；可以改为归档，记录会继续保留。", 409)
        self.db.execute("DELETE FROM edges WHERE group_id=?", (gid,))
        self.db.execute("DELETE FROM nodes WHERE group_id=?", (gid,))
        self.db.execute("DELETE FROM groups WHERE id=?", (gid,))

    def _folder_id(self, value):
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise AppError("所属文件夹格式不正确。")
        if self.db.execute("SELECT 1 FROM folders WHERE id=?", (value,)).fetchone() is None:
            raise AppError("找不到选择的文件夹。", 404)
        return value

    def _create_folder(self, data):
        if self.db.execute("SELECT COUNT(*) FROM folders").fetchone()[0] >= 200:
            raise AppError("文件夹数量已达到上限。")
        name = text(data.get("name", ""), "文件夹名称", True, 200)
        if self.db.execute("SELECT 1 FROM folders WHERE name=?", (name,)).fetchone():
            raise AppError("已经有同名文件夹。")
        order = self.db.execute("SELECT COALESCE(MAX(order_index), -1) + 1 FROM folders").fetchone()[0]
        self.db.execute("INSERT INTO folders VALUES (?,?,?,?)", (new_id(), name, order, now()))

    def _rename_folder(self, fid, data):
        row = self.db.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone()
        if row is None:
            raise AppError("找不到这个文件夹。", 404)
        name = text(data.get("name", row["name"]), "文件夹名称", True, 200)
        if self.db.execute("SELECT 1 FROM folders WHERE name=? AND id<>?", (name, fid)).fetchone():
            raise AppError("已经有同名文件夹。")
        self.db.execute("UPDATE folders SET name=? WHERE id=?", (name, fid))

    def _delete_folder(self, fid):
        if self.db.execute("SELECT 1 FROM folders WHERE id=?", (fid,)).fetchone() is None:
            raise AppError("找不到这个文件夹。", 404)
        self.db.execute("UPDATE groups SET folder_id=NULL, updated_at=? WHERE folder_id=?", (now(), fid))
        self.db.execute("DELETE FROM folders WHERE id=?", (fid,))

    def _create_group(self, data):
        if self.db.execute("SELECT COUNT(*) FROM groups").fetchone()[0] >= 1000:
            raise AppError("项目组数量已达到上限。")
        name = text(data.get("name", ""), "老师姓名", True, 200)
        teacher = text(data.get("teacher", ""), "对接学生姓名", limit=200)
        description = text(data.get("description", ""), "项目组说明")
        info = basic_info(data.get("basic_info", {}))
        folder_id = self._folder_id(data.get("folder_id"))
        gid, stamp = new_id(), now()
        self.db.execute("INSERT INTO groups (id,name,teacher,description,basic_info,is_demo,created_at,updated_at,folder_id) VALUES (?,?,?,?,?,0,?,?,?)",
                        (gid, name, teacher, description, encode(info), stamp, stamp, folder_id))
        template_id = data.get("template_id")
        if template_id:
            if not isinstance(template_id, str):
                raise AppError("分级模板编号格式不正确。")
            template = self.db.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
            if template is None:
                raise AppError("找不到选择的分级模板。", 404)
            nodes, edges = json.loads(template["nodes"]), json.loads(template["edges"])
            mapping = {node["id"]: new_id() for node in nodes}
            for node in nodes:
                value = copy.deepcopy(node)
                value["id"] = mapping[node["id"]]
                value["archived"] = False
                value["parent_id"] = mapping.get(node.get("parent_id"))
                value["favorite"] = False
                for doc in value["templates"]:
                    doc["id"] = new_id()
                self._insert_node(gid, value)
            for edge in edges:
                self.db.execute("INSERT INTO edges VALUES (?,?,?,?)", (new_id(), gid, mapping[edge["source"]], mapping[edge["target"]]))

    def _append_record(self, gid, nid, data, created_at=None):
        node = self._get_node(gid, nid)
        if node["archived"]:
            raise AppError("请先恢复归档节点，再记录完成情况。")
        records = node["records"]
        current = records[-1] if records else None
        current_version = current["version"] if current else 0
        expected = data.get("expected_version")
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise AppError("缺少当前记录版本，请重新打开节点后保存。", 409)
        if expected != current_version:
            raise AppError("这个节点已有新的记录，请刷新后再保存。", 409)
        author = text(data.get("author", ""), "记录人", True, 200)
        status = data.get("status", "未开始")
        if status not in STATUSES:
            raise AppError("请选择有效的完成情况。")
        note = text(data.get("note", ""), "本次情况说明")
        updates = data.get("documents", [])
        if not isinstance(updates, list) or len(updates) > 200:
            raise AppError("文档情况格式不正确。")
        names = {d["id"]: d["name"] for d in node["templates"]}
        previous = {d["template_id"]: d for d in current["documents"]} if current else {}
        supplied = {}
        for item in updates:
            object_value(item, "文档情况")
            ident = item.get("template_id")
            if not isinstance(ident, str) or ident not in names:
                raise AppError("文档模板已经变化，请重新打开节点后保存。", 409)
            if ident in supplied:
                raise AppError("同一份文档的完成情况不能重复提交。")
            if item.get("status", "未开始") not in STATUSES:
                raise AppError("请选择有效的文档完成情况。")
            supplied[ident] = {"status": item.get("status", "未开始"), "note": text(item.get("note", ""), "文档情况说明")}
        documents = []
        for ident, name in names.items():
            value = supplied.get(ident, previous.get(ident, {"status": "未开始", "note": ""}))
            documents.append({"template_id": ident, "name": name, "status": value["status"], "note": value["note"]})
        stamp = created_at or now()
        day = stamp[:10]
        same_day = bool(current) and current.get("day") == day
        if same_day and (author == current.get("author") and status == current.get("status")
                         and note == current.get("note") and documents == current.get("documents")):
            raise AppError("这次没有改动，不需要保存。")
        snapshot = {"id": new_id(), "version": current_version + 1, "created_at": stamp, "day": day,
                    "author": author, "status": status, "note": note, "documents": documents,
                    "node_title": node["title"], "node_description": node["description"]}
        if same_day:
            snapshot["id"] = current["id"]
            snapshot["version"] = current_version
            self.db.execute("UPDATE records SET snapshot=? WHERE id=?", (encode(snapshot), current["id"]))
        else:
            self.db.execute("INSERT INTO records (id,node_id,version,snapshot,day) VALUES (?,?,?,?,?)",
                            (snapshot["id"], nid, snapshot["version"], encode(snapshot), day))

    def _template_mutation(self, method, parts, data):
        if method == "POST" and len(parts) == 1:
            name = text(data.get("name", ""), "分级模板名称", True, 200)
            description = text(data.get("description", ""), "分级模板说明")
            if data.get("group_id"):
                group = self._get_group(data["group_id"])
                nodes = [n for n in group["nodes"] if not n["archived"]]
                ids = {n["id"] for n in nodes}
                edges = [e for e in group["edges"] if e["source"] in ids and e["target"] in ids]
            else:
                nodes, edges = data.get("nodes", []), data.get("edges", [])
            nodes, edges = self._validate_flow(nodes, edges)
            self.db.execute("INSERT INTO templates VALUES (?,?,?,?,?,0)", (new_id(), name, description, encode(nodes), encode(edges)))
            return
        if method == "PUT" and len(parts) == 2:
            old = self.db.execute("SELECT * FROM templates WHERE id=?", (parts[1],)).fetchone()
            if old is None:
                raise AppError("找不到这个分级模板。", 404)
            nodes, edges = self._validate_flow(data.get("nodes", json.loads(old["nodes"])), data.get("edges", json.loads(old["edges"])))
            self.db.execute("UPDATE templates SET name=?,description=?,nodes=?,edges=? WHERE id=?", (
                text(data.get("name", old["name"]), "分级模板名称", True, 200),
                text(data.get("description", old["description"]), "分级模板说明"), encode(nodes), encode(edges), parts[1]))
            return
        raise AppError("没有找到这个操作。", 404)

    def backup_bytes(self):
        with self.lock, tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "backup.sqlite3"
            dest = sqlite3.connect(target)
            try:
                self.db.backup(dest)
            finally:
                dest.close()
            return target.read_bytes()

    def restore_bytes(self, payload):
        if not payload.startswith(b"SQLite format 3\x00") or len(payload) > MAX_BACKUP_BYTES:
            raise AppError("请选择本程序导出的有效数据库备份，文件大小不能超过 64 MB。")
        with self.lock, tempfile.TemporaryDirectory(dir=self.data_dir) as folder:
            incoming = Path(folder) / "incoming.sqlite3"
            incoming.write_bytes(payload)
            candidate = None
            try:
                candidate = sqlite3.connect(incoming)
                candidate.execute("PRAGMA query_only=ON")
                if candidate.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise AppError("备份文件不完整，无法恢复。")
                version_row = candidate.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
                if version_row is None or version_row[0] not in ("1", "2", "3", "4", "5", "6", SCHEMA_VERSION):
                    raise AppError("这个备份的版本与当前程序不兼容。")
                candidate.execute("PRAGMA query_only=OFF")
                self._drop_legacy_triggers(candidate)
                self._migrate_database(candidate)
                candidate.commit()
                reference = sqlite3.connect(":memory:")
                try:
                    reference.executescript(SCHEMA)
                    self._drop_legacy_triggers(reference)
                    self._migrate_database(reference)
                    expected = reference.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
                finally:
                    reference.close()
                actual = candidate.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
                if expected != actual:
                    raise AppError("这个备份的数据库结构与当前程序不兼容。")
                if candidate.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise AppError("备份中的项目记录不完整，无法恢复。")
                for row in candidate.execute("SELECT snapshot FROM records"):
                    record = json.loads(row[0])
                    if not isinstance(record, dict) or record.get("status") not in STATUSES or not isinstance(record.get("documents"), list):
                        raise AppError("备份中的历史记录格式不正确。")
                for table, columns in (("groups", ("basic_info",)), ("nodes", ("templates",)), ("templates", ("nodes", "edges"))):
                    for column in columns:
                        for row in candidate.execute(f"SELECT {column} FROM {table}"):
                            json.loads(row[0])
                for row in candidate.execute("SELECT nodes,edges FROM templates"):
                    self._validate_flow(json.loads(row[0]), json.loads(row[1]))
                fields = ("id", "title", "description", "category", "x", "y", "templates", "archived", "parent_id", "order_index", "favorite", "planned_date")
                for group in candidate.execute("SELECT id FROM groups").fetchall():
                    values = []
                    for row in candidate.execute(f"SELECT {','.join(fields)} FROM nodes WHERE group_id=?", (group[0],)):
                        value = dict(zip(fields, row))
                        value["templates"] = json.loads(value["templates"])
                        value["archived"], value["favorite"] = bool(value["archived"]), bool(value["favorite"])
                        values.append(self._normalize_node(value))
                    self._validate_hierarchy(values)
            except (sqlite3.Error, ValueError, TypeError):
                raise AppError("无法读取这个备份，请选择本程序导出的完整数据库文件。") from None
            finally:
                if candidate:
                    candidate.close()
            self._save_automatic_backup("恢复前")
            self.db.close()
            try:
                os.replace(incoming, self.path)
            finally:
                self._connect()
            return self.state()
