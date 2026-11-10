"""Workbook integrity, day-by-day matrix layout, hierarchy, and literal text."""

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
    result = {"version": version, "day": "2026-11-07", "status": "需修改", "note": "请补充日期", "author": "张老师",
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

    def test_node_columns_follow_hierarchy_and_sibling_order(self):
        cells, root = self.cells()
        self.assertEqual(cells["C3"], "研制阶段 / 输入评审")
        self.assertEqual(cells["D3"], "研制阶段 / 采购")
        self.assertEqual(cells["E3"], "售后")
        self.assertNotIn("F3", cells)
        pane = root.find(".//{{{}}}pane".format(MAIN))
        self.assertEqual(pane.attrib["topLeftCell"], "C5")
        self.assertEqual(pane.attrib["xSplit"], "2")
        self.assertIn("导出时间", cells["A2"])

    def test_one_row_per_inspection_day_with_status_and_note(self):
        cells, _ = self.cells()
        self.assertEqual(cells["A4"], "对应模板")
        self.assertEqual(cells["D4"], "供方评价单")
        self.assertEqual(cells["C4"], "")
        self.assertEqual(cells["A5"], "2026-11-07")
        self.assertEqual(cells["B5"], "张老师")
        self.assertEqual(cells["D5"], "需修改\n请补充日期")
        self.assertEqual(cells["C5"], "")
        self.assertEqual(cells["E5"], "")

    def test_days_are_sorted_latest_first_and_merged_per_node(self):
        target = self.group["nodes"][1]
        target["records"] = [
            record(2, day="2026-11-09", author="王老师", status="已完成", note="已经改好"),
            record(1, day="2026-11-07"),
        ]
        cells, _ = self.cells()
        self.assertEqual(cells["A5"], "2026-11-09")
        self.assertEqual(cells["D5"], "已完成\n已经改好")
        self.assertEqual(cells["A6"], "2026-11-07")
        self.assertEqual(cells["D6"], "需修改\n请补充日期")

    def test_parent_with_own_work_is_included(self):
        self.group["nodes"][2]["templates"] = [{"id": "parent-doc", "name": "阶段总表"}]
        cells, _ = self.cells()
        self.assertEqual(cells["C3"], "研制阶段")
        self.assertEqual(cells["D3"], "研制阶段 / 输入评审")

    def test_archived_subtree_is_excluded(self):
        self.group["nodes"][2]["archived"] = True
        cells, _ = self.cells()
        self.assertEqual(cells["C3"], "售后")
        self.assertNotIn("D3", cells)

    def test_document_columns_use_saved_names_and_status(self):
        target = self.group["nodes"][1]
        target["templates"] = [{"id": "doc-a", "name": "改名后的模板"}, {"id": "doc-b", "name": "新增模板"}]
        cells, _ = self.cells(sheet=2)
        self.assertEqual(cells["B3"], "研制阶段 / 采购 / 改名后的模板")
        self.assertEqual(cells["C3"], "研制阶段 / 采购 / 新增模板")
        self.assertEqual(cells["B4"], "需修改\n补充签署日期")
        self.assertEqual(cells["C4"], "")

    def test_removed_template_keeps_saved_document_column(self):
        self.group["nodes"][1]["templates"] = []
        cells, _ = self.cells(sheet=2)
        self.assertEqual(cells["B3"], "研制阶段 / 采购 / 供方评价单")
        self.assertEqual(cells["B4"], "需修改\n补充签署日期")

    def test_text_is_literal_and_xml_controls_are_removed(self):
        dangerous = '=HYPERLINK("https://example.invalid","查看")'
        self.group["name"] = dangerous
        self.group["nodes"][1]["records"][0]["note"] = "文字<&>\x00\x01\n第二行"
        cells, root = self.cells()
        self.assertEqual(cells["A1"], dangerous + " · 节点完成情况")
        self.assertIn("文字<&>\n第二行", cells["D5"])
        self.assertIsNone(root.find(".//{{{}}}f".format(MAIN)))
        self.assertTrue(all(c.attrib["t"] == "inlineStr" for c in root.findall(".//{{{}}}c".format(MAIN))))

    def test_long_content_is_capped_in_the_grid(self):
        target = self.group["nodes"][1]
        target["records"][0]["note"] = "长" * (CELL_LIMIT + 50)
        cells, _ = self.cells()
        self.assertLessEqual(len(cells["D5"]), CELL_LIMIT)
        self.assertIn("内容较长", cells["D5"])

    def test_export_does_not_mutate_input(self):
        before = copy.deepcopy(self.group)
        export_workbook(self.group)
        self.assertEqual(before, self.group)

    def test_empty_group_is_valid(self):
        self.group["nodes"] = []
        cells, _ = self.cells()
        self.assertEqual(cells["A1"], "测试项目组 · 节点完成情况")
        self.assertNotIn("C3", cells)
        self.assertIn("还没有保存过任何情况记录", cells["A5"])

    def test_group_without_records_shows_header_only(self):
        for item in self.group["nodes"]:
            item["records"] = []
        cells, _ = self.cells()
        self.assertIn("还没有保存过任何情况记录", cells["A5"])

    def test_node_note_sheet_is_flat_with_number_name_note_and_templates(self):
        self.group["nodes"][1]["description"] = "采购阶段要核对报价与合同。"
        cells, _ = self.cells(sheet=3)
        self.assertEqual(cells["A1"], "测试项目组 · 节点说明")
        self.assertEqual(cells["A3"], "序号")
        self.assertEqual(cells["B3"], "节点名称")
        self.assertEqual(cells["C3"], "节点说明")
        self.assertEqual(cells["D3"], "对应模板")
        self.assertEqual(cells["A4"], "1")
        self.assertEqual(cells["B4"], "输入评审")
        self.assertEqual(cells["B5"], "采购")
        self.assertEqual(cells["C5"], "采购阶段要核对报价与合同。")
        self.assertEqual(cells["D5"], "供方评价单")
        self.assertEqual(cells["B6"], "售后")
        self.assertIn("节点说明取自", cells["A7"])
        self.assertNotIn("研制阶段 / 采购", "".join(cells.values()))

    def test_template_row_is_left_blank_when_node_has_no_templates(self):
        cells, _ = self.cells()
        self.assertEqual(cells["E4"], "")

    @unittest.skipUnless(load_workbook, "openpyxl available only in the validation environment")
    def test_openpyxl_reads_styles_text_and_freeze_panes(self):
        self.group["name"] = "=1+1"
        workbook = load_workbook(BytesIO(export_workbook(self.group)))
        self.assertEqual(workbook.sheetnames, ["节点完成情况", "文档完成情况", "节点说明"])
        self.assertEqual(workbook.worksheets[0]["A1"].value, "=1+1 · 节点完成情况")
        self.assertEqual(workbook.worksheets[0]["A1"].data_type, "s")
        self.assertEqual(workbook.worksheets[0].freeze_panes, "C5")
        self.assertEqual(workbook.worksheets[1].freeze_panes, "B4")
        self.assertEqual(workbook.worksheets[2].freeze_panes, "C4")
        self.assertTrue(workbook.worksheets[0]["D5"].alignment.wrap_text)
        self.assertEqual(workbook.worksheets[0]["D5"].fill.fgColor.rgb, "FFFAE9D9")


if __name__ == "__main__":
    unittest.main()
