"""Workbook integrity, latest-record semantics, hierarchy, and literal text."""

import copy
from io import BytesIO
import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from export_xlsx import export_workbook, MAIN, CELL_LIMIT

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


def node(ident, title, parent=None, order=0, **extra):
    result = {"id": ident, "title": title, "parent_id": parent, "order_index": order,
              "templates": [], "records": [], "description": "", "archived": False}
    result.update(extra)
    return result


def record(version=1, **extra):
    result = {"version": version, "status": "需修改", "note": "请补充日期", "author": "张老师",
              "created_at": "2026-11-07T01:30:00+00:00", "node_title": "采购", "node_description": "采购说明",
              "documents": [{"template_id": "doc-a", "name": "供方评价单", "status": "需修改", "note": "补充签署日期"}]}
    result.update(extra)
    return result


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.group = {"name": "测试项目组", "teacher": "李老师", "nodes": [
            node("late", "售后", order=2),
            node("purchase", "采购", "parent", 1, templates=[{"id": "doc-a", "name": "供方评价单"}], records=[record()]),
            node("parent", "研制阶段", order=0),
            node("input", "输入评审", "parent", 0),
        ]}

    def cells(self, group=None, sheet=1):
        data = export_workbook(group or self.group)
        with ZipFile(BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())
            root = ET.fromstring(archive.read("xl/worksheets/sheet{}.xml".format(sheet)))
        ns = {"s": MAIN}
        cells = {element.attrib["r"]: "".join(element.itertext()) for element in root.findall(".//s:c", ns)}
        return cells, root

    def test_hierarchy_and_sibling_order_are_preserved(self):
        cells, root = self.cells()
        self.assertEqual(cells["D2"], "研制阶段 / 输入评审")
        self.assertEqual(cells["E2"], "研制阶段 / 采购")
        self.assertEqual(cells["F2"], "售后")
        self.assertNotIn("G2", cells)
        pane = root.find(".//{{{}}}pane".format(MAIN))
        self.assertEqual(pane.attrib["topLeftCell"], "D4")
        self.assertEqual(pane.attrib["xSplit"], "3")
        self.assertIn("导出时间", cells["A1"])

    def test_parent_with_own_work_is_included(self):
        self.group["nodes"][2]["templates"] = [{"id": "parent-doc", "name": "阶段总表"}]
        cells, _ = self.cells()
        self.assertEqual(cells["D2"], "研制阶段")
        self.assertEqual(cells["E2"], "研制阶段 / 输入评审")

    def test_archived_subtree_is_excluded(self):
        self.group["nodes"][2]["archived"] = True
        cells, _ = self.cells()
        self.assertEqual(cells["D2"], "售后")
        self.assertNotIn("E2", cells)

    def test_latest_version_selected_and_saved_names_kept(self):
        target = self.group["nodes"][1]
        target["records"] = [record(3, note="最新意见"), record(1, note="旧意见")]
        target["templates"] = [{"id": "doc-a", "name": "改名后的模板"}, {"id": "doc-b", "name": "新增模板"}]
        cells, _ = self.cells()
        self.assertEqual(cells["E3"], "供方评价单\n新增模板")
        self.assertIn("最新意见", cells["E4"])
        self.assertNotIn("旧意见", cells["E4"])
        self.assertIn("2026-11-07 09:30:00", cells["E4"])
        details, _ = self.cells(sheet=2)
        self.assertEqual(details["E3"], "供方评价单")
        self.assertEqual(details["L3"], "3")
        self.assertEqual(details["F4"], "尚未记录")
        self.assertEqual(details["K4"], "")

    def test_removed_template_retains_latest_record_details(self):
        self.group["nodes"][1]["templates"] = []
        cells, _ = self.cells()
        self.assertEqual(cells["E3"], "供方评价单")
        self.assertIn("补充签署日期", cells["E4"])

    def test_nodes_without_documents_have_detail_row(self):
        cells, _ = self.cells(sheet=2)
        self.assertEqual(cells["C2"], "输入评审")
        self.assertEqual(cells["E2"], "未设置文档模板")
        self.assertEqual(cells["C4"], "售后")

    def test_text_is_literal_and_xml_controls_are_removed(self):
        dangerous = '=HYPERLINK("https://example.invalid","查看")'
        self.group["name"] = dangerous
        self.group["nodes"][1]["records"][0]["note"] = "文字<&>\x00\x01\n第二行"
        cells, root = self.cells()
        self.assertEqual(cells["A4"], dangerous)
        self.assertIn("文字<&>\n第二行", cells["E4"])
        self.assertIsNone(root.find(".//{{{}}}f".format(MAIN)))
        self.assertTrue(all(c.attrib["t"] == "inlineStr" for c in root.findall(".//{{{}}}c".format(MAIN))))

    def test_long_wide_content_preserved_in_detail(self):
        target = self.group["nodes"][1]
        target["records"][0]["documents"] = [{"template_id": "long-{}".format(i), "name": "材料{}".format(i),
                                                "status": "需修改", "note": str(i) * 20000} for i in range(3)]
        target["templates"] = []
        cells, _ = self.cells()
        self.assertLessEqual(len(cells["E4"]), CELL_LIMIT)
        self.assertIn("完整内容请查看文档明细表", cells["E4"])
        details, _ = self.cells(sheet=2)
        self.assertEqual(details["G3"], "0" * 20000)
        self.assertEqual(details["G4"], "1" * 20000)
        self.assertEqual(details["G5"], "2" * 20000)

    def test_export_does_not_mutate_input(self):
        before = copy.deepcopy(self.group)
        export_workbook(self.group)
        self.assertEqual(before, self.group)

    def test_empty_group_is_valid(self):
        self.group["nodes"] = []
        cells, _ = self.cells()
        self.assertEqual(cells["A4"], "测试项目组")
        self.assertNotIn("D2", cells)

    @unittest.skipUnless(load_workbook, "openpyxl available only in the validation environment")
    def test_openpyxl_reads_styles_text_and_freeze_panes(self):
        self.group["name"] = "=1+1"
        workbook = load_workbook(BytesIO(export_workbook(self.group)))
        self.assertEqual(workbook.sheetnames, ["节点情况汇总", "文档明细"])
        self.assertEqual(workbook.worksheets[0]["A4"].value, "=1+1")
        self.assertEqual(workbook.worksheets[0]["A4"].data_type, "s")
        self.assertEqual(workbook.worksheets[0].freeze_panes, "D4")
        self.assertEqual(workbook.worksheets[1].freeze_panes, "D2")
        self.assertTrue(workbook.worksheets[0]["E4"].alignment.wrap_text)
        self.assertEqual(workbook.worksheets[0]["E4"].fill.fgColor.rgb, "FFFAE9D9")


if __name__ == "__main__":
    unittest.main()
