"""Persistent revisions, isolated flows, backups, and loopback HTTP behavior."""

import copy
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import AppError, SCHEMA, Store
from server import create_server


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.empty = Path(self.folder.name) / "empty.json"
        self.empty.write_text('{"templates":[],"demo_groups":[]}', encoding="utf-8")
        self.store = Store(self.folder.name, self.empty)
        state = self.store.mutate("POST", ["groups"], {"name": "测试项目组", "teacher": "李老师"})
        self.gid = state["groups"][0]["id"]
        state = self.store.mutate("POST", ["groups", self.gid, "nodes"], {
            "title": "第1次采购", "description": "采购说明", "templates": [
                {"id": "doc-a", "name": "供方评价单"}, {"id": "doc-b", "name": "采购检查单"}], "x": 30, "y": 80})
        self.nid = state["groups"][0]["nodes"][0]["id"]

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def node(self, state=None):
        state = state or self.store.state()
        group = next(g for g in state["groups"] if g["id"] == self.gid)
        return next(n for n in group["nodes"] if n["id"] == self.nid)

    def save(self, version=0, **kwargs):
        data = {"expected_version": version, "author": "李老师", "status": "需修改", "note": "请补充日期", "documents": [{"template_id": "doc-a", "status": "已完成", "note": "已检查"}]}
        data.update(kwargs)
        return self.store.mutate("POST", ["groups", self.gid, "nodes", self.nid, "records"], data)

    def backdate(self, days=1):
        """把最近一条记录挪到更早的日期，用来模拟另一次检查日。"""
        record = self.node()["records"][-1]
        day = (datetime.now().astimezone().date() - timedelta(days=days)).isoformat()
        snapshot = dict(record, day=day, created_at=day + "T09:00:00+08:00")
        self.store.db.execute("UPDATE records SET day=?, snapshot=? WHERE id=?",
                              (day, json.dumps(snapshot, ensure_ascii=False), record["id"]))
        self.store.db.commit()

    def test_revisions_append_and_inherit_complete_snapshot(self):
        self.save()
        self.backdate()
        first = copy.deepcopy(self.node()["records"][0])
        self.assertEqual(first["day"], (datetime.now().astimezone().date() - timedelta(days=1)).isoformat())
        state = self.save(1, status="已完成", note="已补充", documents=[{"template_id": "doc-b", "status": "已完成", "note": "日期已填写"}])
        records = self.node(state)["records"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], first)
        self.assertEqual(records[1]["version"], 2)
        self.assertEqual([d["status"] for d in records[1]["documents"]], ["已完成", "已完成"])
        self.assertEqual(records[1]["documents"][0]["note"], "已检查")
        self.assertIn("+", records[1]["created_at"])

    def test_saved_revision_survives_restart(self):
        self.save()
        snapshot = self.node()["records"][0]
        self.store.close()
        self.store = Store(self.folder.name, self.empty)
        self.assertEqual(self.node()["records"][0], snapshot)

    def test_node_and_template_rename_preserves_history(self):
        self.save()
        self.store.mutate("PUT", ["groups", self.gid, "nodes", self.nid], {
            "title": "采购更新", "description": "新说明", "templates": [{"id": "doc-a", "name": "新版评价单"}]})
        self.backdate()
        self.save(1, documents=[])
        records = self.node()["records"]
        self.assertEqual(records[0]["node_title"], "第1次采购")
        self.assertEqual(records[0]["node_description"], "采购说明")
        self.assertEqual(records[0]["documents"][0]["name"], "供方评价单")
        self.assertEqual(len(records[0]["documents"]), 2)
        self.assertEqual(records[1]["documents"][0]["name"], "新版评价单")
        self.assertEqual(len(records[1]["documents"]), 1)

    def test_conflicting_save_keeps_existing_records(self):
        self.save()
        with self.assertRaises(AppError) as raised:
            self.save()
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(len(self.node()["records"]), 1)

    def test_invalid_document_does_not_create_partial_record(self):
        with self.assertRaises(AppError):
            self.save(documents=[{"template_id": "not-present", "status": "已完成"}])
        self.assertEqual(self.node()["records"], [])
        with self.assertRaises(AppError):
            self.save(status="任意值")
        self.assertEqual(self.node()["records"], [])

    def test_past_records_cannot_be_modified_or_removed_in_database(self):
        self.save()
        self.backdate()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE records SET snapshot='{}'")
        self.store.db.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("DELETE FROM records")
        self.store.db.rollback()
        self.assertEqual(len(self.node()["records"]), 1)

    def test_same_day_save_keeps_one_record_and_last_values(self):
        self.save()
        state = self.save(1, status="已完成", note="下午又改了一版")
        records = self.node(state)["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["version"], 1)
        self.assertEqual(records[0]["status"], "已完成")
        self.assertEqual(records[0]["note"], "下午又改了一版")

    def test_save_without_changes_is_rejected(self):
        self.save()
        with self.assertRaises(AppError) as raised:
            self.save(1)
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("没有改动", str(raised.exception))
        self.assertEqual(len(self.node()["records"]), 1)

    def test_next_day_save_adds_a_new_version(self):
        self.save()
        self.backdate()
        state = self.save(1, note="第二天复查")
        records = self.node(state)["records"]
        self.assertEqual([r["version"] for r in records], [1, 2])
        self.assertEqual(records[1]["note"], "第二天复查")
        self.assertNotEqual(records[0]["day"], records[1]["day"])

    def test_archiving_preserves_history_and_removes_edges(self):
        self.save()
        self.backdate()
        state = self.store.mutate("POST", ["groups", self.gid, "nodes"], {"title": "交付"})
        other = state["groups"][0]["nodes"][1]["id"]
        self.store.mutate("POST", ["groups", self.gid, "edges"], {"source": self.nid, "target": other})
        state = self.store.mutate("DELETE", ["groups", self.gid, "nodes", self.nid], {})
        self.assertTrue(self.node(state)["archived"])
        self.assertEqual(len(self.node(state)["records"]), 1)
        self.assertEqual(state["groups"][0]["edges"], [])
        with self.assertRaises(AppError):
            self.save(1)
        self.store.mutate("PUT", ["groups", self.gid, "nodes", self.nid], {"archived": False})
        self.save(1)
        self.assertEqual(len(self.node()["records"]), 2)

    def test_flow_template_copy_has_independent_ids_and_no_history(self):
        self.save()
        state = self.store.mutate("POST", ["templates"], {"name": "采购流程", "group_id": self.gid})
        template = state["templates"][0]
        self.assertNotIn("records", template["nodes"][0])
        self.store.mutate("POST", ["groups"], {"name": "第二组", "template_id": template["id"]})
        groups = self.store.state()["groups"]
        second = groups[1]["nodes"][0]
        self.assertNotEqual(second["id"], self.nid)
        self.assertNotEqual(second["templates"][0]["id"], "doc-a")
        self.assertEqual(second["records"], [])
        self.store.mutate("PUT", ["groups", groups[1]["id"], "nodes", second["id"]], {"title": "第二组独立名称"})
        self.assertEqual(self.node()["title"], "第1次采购")

    def test_template_edits_affect_only_future_groups(self):
        state = self.store.mutate("POST", ["templates"], {"name": "空白流程", "nodes": [], "edges": []})
        tid = state["templates"][0]["id"]
        self.store.mutate("PUT", ["templates", tid], {"nodes": [{"id": "template-node", "title": "新节点", "templates": [{"id": "template-doc", "name": "说明单"}]}]})
        self.assertEqual(self.node()["title"], "第1次采购")
        self.assertEqual(self.store.state()["templates"][0]["nodes"][0]["templates"][0]["id"], "template-doc")

    def test_invalid_flow_links_and_cross_group_access(self):
        with self.assertRaises(AppError):
            self.store.mutate("POST", ["groups", self.gid, "edges"], {"source": self.nid, "target": self.nid})
        state = self.store.mutate("POST", ["groups"], {"name": "其他组"})
        other = state["groups"][1]["id"]
        with self.assertRaises(AppError) as raised:
            self.store.mutate("PUT", ["groups", other, "nodes", self.nid], {"title": "错误"})
        self.assertEqual(raised.exception.status, 404)

    def test_invalid_group_creation_rolls_back(self):
        with self.assertRaises(AppError):
            self.store.mutate("POST", ["groups"], {"name": "失败组", "template_id": "missing"})
        self.assertEqual(len(self.store.state()["groups"]), 1)

    def test_backup_restore_and_automatic_previous_backup(self):
        self.save()
        payload = self.store.backup_bytes()
        self.backdate()
        self.save(1, note="后来的记录")
        self.assertEqual(len(self.node()["records"]), 2)
        self.store.restore_bytes(payload)
        self.assertEqual(len(self.node()["records"]), 1)
        backups = list((Path(self.folder.name) / "backups").glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        con = sqlite3.connect(backups[0])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM records").fetchone()[0], 2)
        con.close()

    def test_invalid_backup_preserves_current_data(self):
        self.save()
        original = self.store.state()["groups"]
        for payload in (b"not sqlite", b"SQLite format 3\x00broken"):
            with self.assertRaises(AppError):
                self.store.restore_bytes(payload)
            self.assertEqual(self.store.state()["groups"], original)

    def test_changed_schema_backup_rejected(self):
        payload = self.store.backup_bytes()
        path = Path(self.folder.name) / "altered.sqlite3"
        path.write_bytes(payload)
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE unexpected(value TEXT)")
        con.commit()
        con.close()
        with self.assertRaises(AppError):
            self.store.restore_bytes(path.read_bytes())

    def test_input_limits_and_types(self):
        for payload in ({"title": ""}, {"title": "x", "x": float("nan")}, {"title": "x", "templates": [{"name": ""}]}, {"title": "x", "templates": [{"id": "d", "name": "A"}, {"id": "d", "name": "B"}]}):
            with self.assertRaises(AppError):
                self.store.mutate("POST", ["groups", self.gid, "nodes"], payload)
        self.assertEqual(len(self.store.state()["groups"][0]["nodes"]), 1)

    def add_node(self, title, parent_id=None, **fields):
        payload = dict(title=title, parent_id=parent_id)
        payload.update(fields)
        state = self.store.mutate("POST", ["groups", self.gid, "nodes"], payload)
        return next(g for g in state["groups"] if g["id"] == self.gid)["nodes"][-1]

    def test_hierarchy_favorite_and_planned_date_survive_restart(self):
        child = self.add_node("采购准备", self.nid, planned_date="2026-12-01", favorite=True)
        self.assertEqual(child["parent_id"], self.nid)
        self.assertTrue(child["favorite"])
        self.assertEqual(child["planned_date"], "2026-12-01")
        self.store.close()
        self.store = Store(self.folder.name, self.empty)
        reopened = self.store._get_node(self.gid, child["id"])
        self.assertEqual(reopened["planned_date"], "2026-12-01")
        self.assertTrue(reopened["favorite"])
        with self.assertRaises(AppError):
            self.add_node("日期错误", planned_date="2026-02-30")
        with self.assertRaises(AppError):
            self.add_node("收藏错误", favorite="yes")

    def test_parent_cycle_and_cross_group_parent_are_rejected(self):
        child = self.add_node("子节点", self.nid)
        with self.assertRaises(AppError):
            self.store.mutate("PUT", ["groups", self.gid, "nodes", self.nid], {"parent_id": child["id"]})
        self.assertIsNone(self.node()["parent_id"])
        state = self.store.mutate("POST", ["groups"], {"name": "另一组"})
        other_group = state["groups"][-1]["id"]
        with self.assertRaises(AppError):
            self.store.mutate("POST", ["groups", other_group, "nodes"], {"title": "异组子节点", "parent_id": self.nid})

    def test_maximum_depth_including_moving_a_subtree(self):
        chain = [self.nid]
        for index in range(9):
            chain.append(self.add_node(f"第{index + 2}级", chain[-1])["id"])
        with self.assertRaises(AppError):
            self.add_node("第11级", chain[-1])
        additional = self.add_node("另一父节点")
        with self.assertRaises(AppError):
            self.store.mutate("PUT", ["groups", self.gid, "nodes", self.nid], {"parent_id": additional["id"]})
        with self.assertRaises(AppError):
            self.store.mutate("POST", ["groups", self.gid, "group-nodes"], {"title": "过深分组", "parent_id": None, "node_ids": [self.nid]})
        self.assertEqual(len(self.store.state()["groups"][0]["nodes"]), 11)

    def test_recursive_archive_and_restore_preserve_parent_and_child_history(self):
        self.save()
        child = self.add_node("子流程", self.nid)
        grandchild = self.add_node("更细节点", child["id"])
        self.store.mutate("POST", ["groups", self.gid, "nodes", grandchild["id"], "records"], {"expected_version": 0, "author": "老师", "status": "进行中"})
        self.store.mutate("DELETE", ["groups", self.gid, "nodes", self.nid], {})
        nodes = self.store.state()["groups"][0]["nodes"]
        self.assertTrue(all(n["archived"] for n in nodes))
        self.assertEqual(sum(len(n["records"]) for n in nodes), 2)
        with self.assertRaises(AppError):
            self.store.mutate("PUT", ["groups", self.gid, "nodes", grandchild["id"]], {"archived": False})
        self.store.mutate("PUT", ["groups", self.gid, "nodes", self.nid], {"archived": False})
        nodes = self.store.state()["groups"][0]["nodes"]
        self.assertTrue(all(not n["archived"] for n in nodes))
        self.assertEqual(sum(len(n["records"]) for n in nodes), 2)

    def test_moving_node_removes_only_invalid_cross_level_edges(self):
        second = self.add_node("第二节点")
        third = self.add_node("第三节点")
        self.store.mutate("POST", ["groups", self.gid, "edges"], {"source": self.nid, "target": second["id"]})
        self.store.mutate("POST", ["groups", self.gid, "edges"], {"source": second["id"], "target": third["id"]})
        self.store.mutate("PUT", ["groups", self.gid, "nodes", self.nid], {"parent_id": third["id"]})
        edges = self.store.state()["groups"][0]["edges"]
        self.assertEqual([(e["source"], e["target"]) for e in edges], [(second["id"], third["id"])])
        with self.assertRaises(AppError):
            self.store.mutate("POST", ["groups", self.gid, "edges"], {"source": self.nid, "target": second["id"]})

    def test_organize_changes_requested_level_only(self):
        second = self.add_node("第二节点")
        third = self.add_node("第三节点")
        child_a = self.add_node("子节点A", self.nid)
        child_b = self.add_node("子节点B", self.nid)
        self.store.mutate("POST", ["groups", self.gid, "edges"], {"source": child_a["id"], "target": child_b["id"]})
        self.save()
        selection = [third["id"], self.nid, second["id"]]
        state = self.store.mutate("POST", ["groups", self.gid, "organize"], {"parent_id": None, "node_ids": selection})
        nodes = {n["id"]: n for n in state["groups"][0]["nodes"]}
        self.assertEqual([(nodes[n]["order_index"], nodes[n]["x"], nodes[n]["y"]) for n in selection], [(0, 60, 70), (1, 360, 70), (2, 660, 70)])
        edges = {(e["source"], e["target"]) for e in state["groups"][0]["edges"]}
        self.assertEqual(edges, {(third["id"], self.nid), (self.nid, second["id"]), (child_a["id"], child_b["id"])})
        self.assertEqual(len(nodes[self.nid]["records"]), 1)
        unchanged = copy.deepcopy(state["groups"])
        with self.assertRaises(AppError) as raised:
            self.store.mutate("POST", ["groups", self.gid, "organize"], {"parent_id": None, "node_ids": selection[:2]})
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.store.state()["groups"], unchanged)

    def test_grouping_preserves_records_and_connects_parent_boundaries(self):
        self.save()
        before = self.add_node("前序节点")
        after = self.add_node("后续节点")
        selected_b = self.add_node("另一材料")
        self.store.mutate("POST", ["groups", self.gid, "organize"], {"node_ids": [before["id"], self.nid, selected_b["id"], after["id"]]})
        state = self.store.mutate("POST", ["groups", self.gid, "group-nodes"], {"title": "采购办理", "parent_id": None, "node_ids": [self.nid, selected_b["id"]]})
        parent = next(n for n in state["groups"][0]["nodes"] if n["title"] == "采购办理")
        self.assertEqual(self.node(state)["parent_id"], parent["id"])
        self.assertEqual(len(self.node(state)["records"]), 1)
        edges = {(e["source"], e["target"]) for e in state["groups"][0]["edges"]}
        self.assertEqual(edges, {(before["id"], parent["id"]), (parent["id"], after["id"]), (self.nid, selected_b["id"])})
        with self.assertRaises(AppError):
            self.store.mutate("POST", ["groups", self.gid, "group-nodes"], {"title": "跨级选择", "node_ids": [self.nid, after["id"]]})

    def test_hierarchical_template_copy_remaps_parent_and_omits_favorites(self):
        self.store.mutate("PUT", ["groups", self.gid, "nodes", self.nid], {"favorite": True, "planned_date": "2026-11-20"})
        child = self.add_node("采购子节点", self.nid, favorite=True)
        state = self.store.mutate("POST", ["templates"], {"name": "层级模板", "group_id": self.gid})
        template = state["templates"][0]
        self.assertTrue(all("favorite" not in n for n in template["nodes"]))
        state = self.store.mutate("POST", ["groups"], {"name": "新项目组", "template_id": template["id"]})
        copied = state["groups"][-1]["nodes"]
        root = next(n for n in copied if n["parent_id"] is None)
        leaf = next(n for n in copied if n["parent_id"] is not None)
        self.assertEqual(leaf["parent_id"], root["id"])
        self.assertNotEqual(leaf["parent_id"], self.nid)
        self.assertEqual(root["planned_date"], "2026-11-20")
        self.assertTrue(all(not n["favorite"] for n in copied))


class FolderTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.empty = Path(self.folder.name) / "empty.json"
        self.empty.write_text('{"templates":[],"demo_groups":[]}', encoding="utf-8")
        self.store = Store(self.folder.name, self.empty)
        state = self.store.mutate("POST", ["groups"], {"name": "采购组"})
        self.gid = state["groups"][0]["id"]

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def test_folders_organize_groups_without_touching_records(self):
        state = self.store.mutate("POST", ["folders"], {"name": "2026 级"})
        fid = state["folders"][0]["id"]
        state = self.store.mutate("PUT", ["folders", fid], {"name": "2026 届"})
        self.assertEqual(state["folders"][0]["name"], "2026 届")
        state = self.store.mutate("PUT", ["groups", self.gid], {"folder_id": fid})
        self.assertEqual(state["groups"][0]["folder_id"], fid)
        state = self.store.mutate("DELETE", ["folders", fid], {})
        self.assertEqual(state["folders"], [])
        self.assertIsNone(state["groups"][0]["folder_id"])

    def test_unknown_folder_rejected(self):
        with self.assertRaises(AppError):
            self.store.mutate("PUT", ["groups", self.gid], {"folder_id": "missing"})
        with self.assertRaises(AppError):
            self.store.mutate("POST", ["groups"], {"name": "另一个组", "folder_id": "missing"})

    def test_folder_name_must_be_present_and_unique(self):
        self.store.mutate("POST", ["folders"], {"name": "归档"})
        with self.assertRaises(AppError):
            self.store.mutate("POST", ["folders"], {"name": "归档"})
        with self.assertRaises(AppError):
            self.store.mutate("POST", ["folders"], {"name": "  "})

    def test_folders_survive_restart_and_backup(self):
        state = self.store.mutate("POST", ["folders"], {"name": "备用"})
        fid = state["folders"][0]["id"]
        self.store.mutate("PUT", ["groups", self.gid], {"folder_id": fid})
        payload = self.store.backup_bytes()
        self.store.close()
        self.store = Store(self.folder.name, self.empty)
        self.assertEqual(self.store.state()["folders"][0]["id"], fid)
        self.assertEqual(self.store.state()["groups"][0]["folder_id"], fid)
        other = tempfile.TemporaryDirectory()
        try:
            empty = Path(other.name) / "empty.json"
            empty.write_text('{"templates":[],"demo_groups":[]}', encoding="utf-8")
            store = Store(other.name, empty)
            try:
                restored = store.restore_bytes(payload)
                self.assertEqual(restored["folders"][0]["name"], "备用")
                self.assertEqual(restored["groups"][0]["folder_id"], fid)
            finally:
                store.close()
        finally:
            other.cleanup()


    def test_group_archive_and_restore(self):
        state = self.store.mutate("PUT", ["groups", self.gid], {"archived": True})
        self.assertTrue(state["groups"][0]["archived"])
        state = self.store.mutate("PUT", ["groups", self.gid], {"archived": False})
        self.assertFalse(state["groups"][0]["archived"])
        self.assertEqual(state["groups"][0]["name"], "采购组")

    def test_group_with_records_cannot_be_deleted(self):
        state = self.store.mutate("POST", ["groups", self.gid, "nodes"], {"title": "节点", "templates": []})
        nid = state["groups"][0]["nodes"][0]["id"]
        self.store.mutate("POST", ["groups", self.gid, "nodes", nid, "records"], {"expected_version": 0, "author": "老师", "status": "已完成"})
        with self.assertRaises(AppError) as caught:
            self.store.mutate("DELETE", ["groups", self.gid], {})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(len(self.store.state()["groups"]), 1)

    def test_group_without_records_can_be_deleted(self):
        state = self.store.mutate("POST", ["groups"], {"name": "临时项目组"})
        gid = [g["id"] for g in state["groups"] if g["name"] == "临时项目组"][0]
        store = self.store.mutate("DELETE", ["groups", gid], {})
        self.assertEqual([g["id"] for g in store["groups"]], [self.gid])


def create_v3_database(folder):
    path = Path(folder) / "projects.sqlite3"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("CREATE TABLE folders (id TEXT PRIMARY KEY, name TEXT NOT NULL, order_index INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    con.execute("ALTER TABLE groups ADD COLUMN folder_id TEXT")
    con.execute("ALTER TABLE nodes ADD COLUMN parent_id TEXT")
    con.execute("ALTER TABLE nodes ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE nodes ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE nodes ADD COLUMN planned_date TEXT")
    con.execute("INSERT INTO metadata VALUES ('schema_version','3')")
    con.execute("INSERT INTO metadata VALUES ('initialized','1')")
    con.execute("INSERT INTO folders VALUES ('old-folder','旧文件夹',0,'2026-10-01T09:00:00+08:00')")
    con.execute("INSERT INTO groups VALUES ('v3-group','三版项目组','老师','说明','{}',0,'2026-10-01T09:00:00+08:00','2026-10-02T09:00:00+08:00','old-folder')")
    con.execute("INSERT INTO nodes VALUES ('v3-node','v3-group','节点','说明','材料',0,0,'[]',0,NULL,0,0,NULL)")
    con.commit()
    con.close()
    return path


def create_v4_database(folder):
    path = Path(folder) / "projects.sqlite3"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("CREATE TABLE folders (id TEXT PRIMARY KEY, name TEXT NOT NULL, order_index INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    con.execute("ALTER TABLE groups ADD COLUMN folder_id TEXT")
    con.execute("ALTER TABLE groups ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE nodes ADD COLUMN parent_id TEXT")
    con.execute("ALTER TABLE nodes ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE nodes ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE nodes ADD COLUMN planned_date TEXT")
    con.execute("INSERT INTO metadata VALUES ('schema_version','4')")
    con.execute("INSERT INTO metadata VALUES ('initialized','1')")
    con.execute("INSERT INTO folders VALUES ('old-folder','旧文件夹',0,'2026-10-01T09:00:00+08:00')")
    con.execute("INSERT INTO groups VALUES ('v4-group','四版项目组','四老师','说明','{}',0,'2026-10-01T09:00:00+08:00','2026-10-02T09:00:00+08:00','old-folder',0)")
    con.execute("INSERT INTO nodes VALUES ('v4-node','v4-group','节点','说明','材料',0,0,'[]',0,NULL,0,0,NULL)")
    con.commit()
    con.close()
    return path


def create_v5_database(folder):
    path = Path(folder) / "projects.sqlite3"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("CREATE TABLE folders (id TEXT PRIMARY KEY, name TEXT NOT NULL, order_index INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    con.execute("ALTER TABLE groups ADD COLUMN folder_id TEXT")
    con.execute("ALTER TABLE groups ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE nodes ADD COLUMN parent_id TEXT")
    con.execute("ALTER TABLE nodes ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE nodes ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE nodes ADD COLUMN planned_date TEXT")
    con.execute("INSERT INTO metadata VALUES ('schema_version','5')")
    con.execute("INSERT INTO metadata VALUES ('initialized','1')")
    con.execute("INSERT INTO folders VALUES ('old-folder','旧文件夹',0,'2026-10-01T09:00:00+08:00')")
    con.execute("INSERT INTO groups VALUES ('v5-group','五老师','','说明','{}',0,'2026-10-01T09:00:00+08:00','2026-10-02T09:00:00+08:00','old-folder',0)")
    con.execute("INSERT INTO nodes VALUES ('v5-node','v5-group','节点','说明','',0,0,'[]',0,NULL,0,0,NULL)")
    for version, day, note in ((1, "2026-10-03", "上午"), (2, "2026-10-03", "下午"), (3, "2026-10-05", "复查")):
        snapshot = {"id": "v5-record-{}".format(version), "version": version, "created_at": "{}T09:0{}:00+08:00".format(day, version),
                    "author": "王老师", "status": "进行中", "note": note, "documents": [],
                    "node_title": "节点", "node_description": "说明"}
        con.execute("INSERT INTO records VALUES (?,?,?,?)",
                    (snapshot["id"], "v5-node", version, json.dumps(snapshot, ensure_ascii=False)))
    con.commit()
    con.close()
    return path


def create_legacy_database(folder):
    path = Path(folder) / "projects.sqlite3"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("INSERT INTO metadata VALUES ('schema_version','1')")
    con.execute("INSERT INTO metadata VALUES ('initialized','1')")
    con.execute("INSERT INTO groups VALUES ('legacy-group','原有项目组','原老师','已保存的项目','{}',0,'2026-11-01T09:00:00+08:00','2026-11-02T09:00:00+08:00')")
    con.execute("INSERT INTO nodes VALUES ('legacy-node','legacy-group','原有节点','原说明','材料',80,100,?,0)", (json.dumps([{"id": "legacy-document", "name": "原模板"}], ensure_ascii=False),))
    snapshot = {"id": "legacy-record", "version": 1, "created_at": "2026-11-02T09:00:00+08:00", "author": "原老师", "status": "需修改", "note": "原检查意见", "documents": [{"template_id": "legacy-document", "name": "原模板", "status": "需修改", "note": "原说明"}], "node_title": "原有节点", "node_description": "原说明"}
    con.execute("INSERT INTO records VALUES ('legacy-record','legacy-node',1,?)", (json.dumps(snapshot, ensure_ascii=False),))
    template_nodes = [{"id": "legacy-template-node", "title": "旧模板节点", "description": "", "category": "", "x": 0, "y": 0, "templates": [], "archived": False}]
    con.execute("INSERT INTO templates VALUES ('legacy-template','旧流程模板','',?,'[]',0)", (json.dumps(template_nodes, ensure_ascii=False),))
    con.commit()
    con.close()
    return path, snapshot


class MigrationTest(unittest.TestCase):
    def test_existing_database_gets_builtin_folders_and_templates(self):
        with tempfile.TemporaryDirectory() as folder:
            create_legacy_database(folder)
            store = Store(folder)
            try:
                state = store.state()
                names = [f["name"] for f in state["folders"]]
                for expected in ("2026项目组·重要级", "2026项目组·一般级", "2026全校管理"):
                    self.assertIn(expected, names)
                self.assertEqual(state["groups"][0]["folder_id"], None)
                template_names = [t["name"] for t in state["templates"]]
                self.assertIn("全校 · 科研院", template_names)
            finally:
                store.close()

    def test_existing_database_upgrade_preserves_groups_and_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path, snapshot = create_legacy_database(folder)
            before = path.read_bytes()
            store = Store(folder)
            try:
                state = store.state()
                self.assertEqual(state["storage"]["schema_version"], "8")
                self.assertEqual(len(state["groups"]), 1)
                self.assertEqual(state["groups"][0]["name"], "原老师")
                self.assertEqual(state["groups"][0]["teacher"], "")
                node = state["groups"][0]["nodes"][0]
                self.assertEqual(node["records"], [dict(snapshot, day="2026-11-02")])
                self.assertEqual((node["parent_id"], node["order_index"], node["favorite"], node["planned_date"]), (None, 0, False, None))
                self.assertEqual(state["templates"][0]["nodes"][0]["parent_id"], None)
                backups = list((Path(folder) / "backups").glob("升级前-*.sqlite3"))
                self.assertEqual(len(backups), 1)
                backup = sqlite3.connect(backups[0])
                self.assertEqual(backup.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0], "1")
                backup.close()
                store.mutate("POST", ["groups"], {"name": "升级后创建", "template_id": "legacy-template"})
            finally:
                store.close()
            reopened = Store(folder)
            self.assertEqual(len(reopened.state()["groups"]), 2)
            self.assertEqual(reopened.state()["groups"][0]["name"], "原老师")
            self.assertEqual(len(list((Path(folder) / "backups").glob("升级前-*.sqlite3"))), 1)
            reopened.close()

    def test_v3_database_gets_archived_column(self):
        with tempfile.TemporaryDirectory() as folder:
            create_v3_database(folder)
            store = Store(folder)
            try:
                state = store.state()
                self.assertEqual(state["storage"]["schema_version"], "8")
                self.assertFalse(state["groups"][0]["archived"])
                self.assertEqual(state["groups"][0]["folder_id"], "old-folder")
                self.assertEqual(state["folders"][0]["name"], "旧文件夹")
                self.assertEqual(state["groups"][0]["name"], "老师")
                self.assertEqual(state["groups"][0]["teacher"], "")
                self.assertEqual(len(list((Path(folder) / "backups").glob("升级前-*.sqlite3"))), 1)
            finally:
                store.close()

    def test_v4_database_uses_teacher_name_for_group(self):
        with tempfile.TemporaryDirectory() as folder:
            create_v4_database(folder)
            store = Store(folder)
            try:
                state = store.state()
                self.assertEqual(state["storage"]["schema_version"], "8")
                group = state["groups"][0]
                self.assertEqual(group["name"], "四老师")
                self.assertEqual(group["teacher"], "")
                self.assertEqual(group["folder_id"], "old-folder")
                self.assertFalse(group["archived"])
                self.assertEqual(len(list((Path(folder) / "backups").glob("升级前-*.sqlite3"))), 1)
            finally:
                store.close()

    def test_v5_database_collapses_same_day_records(self):
        with tempfile.TemporaryDirectory() as folder:
            create_v5_database(folder)
            store = Store(folder)
            try:
                state = store.state()
                self.assertEqual(state["storage"]["schema_version"], "8")
                records = state["groups"][0]["nodes"][0]["records"]
                self.assertEqual([r["note"] for r in records], ["下午", "复查"])
                self.assertEqual([r["day"] for r in records], ["2026-10-03", "2026-10-05"])
                self.assertEqual([r["version"] for r in records], [1, 2])
                self.assertEqual(len(list((Path(folder) / "backups").glob("升级前-*.sqlite3"))), 1)
                store.mutate("POST", ["groups", state["groups"][0]["id"], "nodes", "v5-node", "records"], {
                    "expected_version": 2, "author": "王老师", "status": "已完成", "note": "今天补完", "documents": []})
                records = store.state()["groups"][0]["nodes"][0]["records"]
                self.assertEqual(len(records), 3)
                self.assertEqual(records[2]["note"], "今天补完")
                self.assertEqual(records[2]["version"], 3)
            finally:
                store.close()

    def test_restoring_v5_backup_upgrades_it(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as target:
            source = create_v5_database(folder)
            store = Store(target)
            try:
                store.restore_bytes(source.read_bytes())
                state = store.state()
                self.assertEqual(state["storage"]["schema_version"], "8")
                records = state["groups"][0]["nodes"][0]["records"]
                self.assertEqual([r["day"] for r in records], ["2026-10-03", "2026-10-05"])
                self.assertEqual([r["note"] for r in records], ["下午", "复查"])
            finally:
                store.close()

    def test_restart_does_not_restore_legacy_triggers(self):
        with tempfile.TemporaryDirectory() as folder:
            create_v5_database(folder)
            Store(folder).close()
            # 模拟一次重启：SCHEMA 的 IF NOT EXISTS 会把旧触发器重新建出来。
            raw = sqlite3.connect(Path(folder) / "projects.sqlite3")
            with raw:
                raw.executescript(SCHEMA)
            raw.close()
            store = Store(folder)
            try:
                names = {row[0] for row in store.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'")}
                self.assertNotIn("immutable_record_update", names)
                gid = store.state()["groups"][0]["id"]
                out = store.mutate("POST", ["groups", gid, "nodes", "v5-node", "records"], {
                    "expected_version": 2, "author": "王老师", "status": "进行中",
                    "note": "今天第一次", "documents": []})
                out = store.mutate("POST", ["groups", gid, "nodes", "v5-node", "records"], {
                    "expected_version": 3, "author": "王老师", "status": "进行中",
                    "note": "同一天再改一次", "documents": []})
                records = out["groups"][0]["nodes"][0]["records"]
                self.assertEqual(len(records), 3)
                self.assertEqual(records[-1]["note"], "同一天再改一次")
            finally:
                store.close()

    def test_restoring_legacy_backup_upgrades_it_and_preserves_current_backup(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            path, snapshot = create_legacy_database(source)
            store = Store(target)
            try:
                store.mutate("POST", ["groups"], {"name": "恢复前项目"})
                before = copy.deepcopy(store.state()["groups"])
                state = store.restore_bytes(path.read_bytes())
                self.assertEqual(state["storage"]["schema_version"], "8")
                self.assertEqual(state["groups"][0]["nodes"][0]["records"], [dict(snapshot, day="2026-11-02")])
                backups = list((Path(target) / "backups").glob("恢复前-*.sqlite3"))
                self.assertEqual(len(backups), 1)
                store.restore_bytes(backups[0].read_bytes())
                self.assertEqual(store.state()["groups"], before)
            finally:
                store.close()


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        empty = Path(self.folder.name) / "empty.json"
        empty.write_text('{"templates":[],"demo_groups":[]}', encoding="utf-8")
        self.server = create_server(port=0, data_dir=self.folder.name, presets_path=empty)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.token = self.server.store.csrf_token

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.folder.cleanup()

    def request(self, method, path, value=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        actual_headers = {"Content-Type": "application/json", "X-App-Token": self.token}
        actual_headers.update(headers or {})
        body = raw if raw is not None else json.dumps(value).encode() if value is not None else None
        connection.request(method, path, body, actual_headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_state_and_write(self):
        code, headers, raw = self.request("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["csrf_token"], self.token)
        code, headers, raw = self.request("POST", "/api/groups", {"name": "中文项目组"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["groups"][0]["name"], "中文项目组")

    def test_cross_origin_and_forged_host_denied(self):
        for headers in ({"Origin": "https://example.com"}, {"Host": "example.com"}, {"Sec-Fetch-Site": "cross-site"}):
            code, _, _ = self.request("POST", "/api/groups", {"name": "外部写入"}, headers)
            self.assertEqual(code, 403)
        self.assertEqual(self.server.store.state()["groups"], [])

    def test_missing_token_denied(self):
        code, _, _ = self.request("POST", "/api/groups", {"name": "无令牌"}, {"X-App-Token": ""})
        self.assertEqual(code, 403)

    def test_invalid_json_and_body_type(self):
        self.assertEqual(self.request("POST", "/api/groups", raw=b"{")[0], 400)
        self.assertEqual(self.request("POST", "/api/groups", value=[])[0], 400)
        self.assertEqual(self.request("POST", "/api/groups", value={"name": "x"}, headers={"Content-Type": "text/plain"})[0], 415)

    def test_static_traversal_and_unknown_api(self):
        self.assertEqual(self.request("GET", "/%2e%2e/backend.py")[0], 404)
        self.assertEqual(self.request("GET", "/api/missing")[0], 404)

    def test_backup_download_and_restore_http(self):
        self.request("POST", "/api/groups", {"name": "备份前"})
        code, headers, payload = self.request("GET", "/api/backup")
        self.assertEqual(code, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.request("POST", "/api/groups", {"name": "备份后"})
        code, _, raw = self.request("POST", "/api/restore", headers={"Content-Type": "application/octet-stream"}, raw=payload)
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(raw)["groups"]), 1)

    def test_hierarchy_organize_and_grouping_http(self):
        _, _, raw = self.request("POST", "/api/groups", {"name": "分层项目"})
        gid = json.loads(raw)["groups"][0]["id"]
        for title in ("第一节点", "第二节点"):
            code, _, raw = self.request("POST", f"/api/groups/{gid}/nodes", {"title": title})
            self.assertEqual(code, 200)
        ids = [n["id"] for n in json.loads(raw)["groups"][0]["nodes"]]
        code, _, raw = self.request("POST", f"/api/groups/{gid}/organize", {"parent_id": None, "node_ids": ids[::-1]})
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(raw)["groups"][0]["edges"]), 1)
        code, _, raw = self.request("POST", f"/api/groups/{gid}/group-nodes", {"title": "父流程", "parent_id": None, "node_ids": ids})
        self.assertEqual(code, 200)
        nodes = json.loads(raw)["groups"][0]["nodes"]
        parent = next(n for n in nodes if n["title"] == "父流程")
        self.assertTrue(all(n["parent_id"] == parent["id"] for n in nodes if n["id"] in ids))


if __name__ == "__main__":
    unittest.main()
