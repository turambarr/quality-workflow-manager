"""Export a group's latest saved node records as an offline Excel workbook."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
import math
import re
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
CHINA_TIME = timezone(timedelta(hours=8))
CELL_LIMIT = 32767
REMARK = "本表按各节点最近一次保存的情况汇总。各节点的记录时间可能不同，请结合记录时间和版本查看。"
ET.register_namespace("", MAIN)
ET.register_namespace("r", REL)


def _tag(name):
    return "{{{}}}{}".format(MAIN, name)


def _xml(element):
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def _clean(value):
    text = "" if value is None else str(value)
    return re.sub(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]", "", text)


def _cell_text(value):
    text = _clean(value)
    if len(text) > CELL_LIMIT:
        suffix = "\n内容较长，完整内容请查看文档明细表。"
        text = text[:CELL_LIMIT - len(suffix)] + suffix
    return text


def _number(value, fallback=0):
    try:
        number = float(value)
        return number if math.isfinite(number) else fallback
    except (ValueError, TypeError):
        return fallback


def _ordered_nodes(group):
    nodes = [n for n in group.get("nodes", []) if isinstance(n, dict)]
    indexed = {n.get("id"): (i, n) for i, n in enumerate(nodes)}
    children = defaultdict(list)
    for n in nodes:
        children[n.get("parent_id")].append(n)
    hidden = {n.get("id") for n in nodes if n.get("archived")}
    pending = list(hidden)
    while pending:
        for child in children.get(pending.pop(), []):
            if child.get("id") not in hidden:
                hidden.add(child.get("id"))
                pending.append(child.get("id"))
    active = {ident: item for ident, item in indexed.items() if ident not in hidden}

    def order(n):
        original = indexed[n.get("id")][0]
        return _number(n.get("order_index"), original), original

    roots = sorted([n for _, n in active.values()
                    if n.get("parent_id") not in active or n.get("parent_id") == n.get("id")], key=order)
    visited, result = set(), []

    def walk(start):
        stack = [(n, []) for n in reversed(start)]
        while stack:
            node, parents = stack.pop()
            ident = node.get("id")
            if ident in visited or ident in hidden:
                continue
            visited.add(ident)
            path = parents + [_clean(node.get("title", "未命名节点"))]
            descendants = sorted([n for n in children.get(ident, []) if n.get("id") in active], key=order)
            if not children.get(ident) or node.get("templates") or node.get("records"):
                result.append((node, path))
            stack.extend((child, path) for child in reversed(descendants))

    walk(roots)
    walk(sorted([n for ident, (_, n) in active.items() if ident not in visited], key=order))
    return result


def _latest_record(node):
    records = [r for r in node.get("records", []) if isinstance(r, dict)]
    if not records:
        return None
    return max(enumerate(records), key=lambda item: (_number(item[1].get("version"), item[0]), item[0]))[1]


def _documents(node, record):
    result = []
    seen = set()
    if record:
        for document in record.get("documents", []):
            if not isinstance(document, dict):
                continue
            result.append(dict(document))
            seen.add(document.get("template_id"))
    for template in node.get("templates", []):
        if template.get("id") not in seen:
            result.append({"template_id": template.get("id"), "name": template.get("name", ""),
                           "status": "尚未记录", "note": "", "unrecorded": True})
    return result


def _date(value):
    if not value:
        return ""
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo:
            result = result.astimezone(CHINA_TIME)
        return result.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return _clean(value)


def _column(number):
    output = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        output = chr(65 + remainder) + output
    return output


def _status_style(status):
    if status == "已完成":
        return 5
    if status == "需修改":
        return 6
    return 0


def _cell(row, column, value, style=0):
    number = row.attrib["r"]
    element = ET.SubElement(row, _tag("c"), r="{}{}".format(_column(column), number), t="inlineStr", s=str(style))
    inline = ET.SubElement(element, _tag("is"))
    text = ET.SubElement(inline, _tag("t"), {XML_SPACE: "preserve"})
    text.text = _cell_text(value)


def _sheet(widths, rows, freeze_rows, merges=None, autofilter=None):
    sheet = ET.Element(_tag("worksheet"))
    ET.SubElement(sheet, _tag("dimension"), ref="A1:{}{}".format(_column(len(widths)), max(1, len(rows))))
    views = ET.SubElement(sheet, _tag("sheetViews"))
    view = ET.SubElement(views, _tag("sheetView"), workbookViewId="0", showGridLines="0")
    ET.SubElement(view, _tag("pane"), xSplit="3", ySplit=str(freeze_rows),
                  topLeftCell="D{}".format(freeze_rows + 1), activePane="bottomRight", state="frozen")
    ET.SubElement(view, _tag("selection"), pane="bottomRight", activeCell="D{}".format(freeze_rows + 1),
                  sqref="D{}".format(freeze_rows + 1))
    ET.SubElement(sheet, _tag("sheetFormatPr"), defaultRowHeight="22")
    columns = ET.SubElement(sheet, _tag("cols"))
    for i, width in enumerate(widths, 1):
        ET.SubElement(columns, _tag("col"), min=str(i), max=str(i), width=str(width), customWidth="1")
    data = ET.SubElement(sheet, _tag("sheetData"))
    for i, (values, height) in enumerate(rows, 1):
        attributes = {"r": str(i)}
        if height:
            attributes.update(ht=str(min(height, 409)), customHeight="1")
        row = ET.SubElement(data, _tag("row"), attributes)
        for j, (value, style) in enumerate(values, 1):
            _cell(row, j, value, style)
    if autofilter:
        ET.SubElement(sheet, _tag("autoFilter"), ref=autofilter)
    if merges:
        container = ET.SubElement(sheet, _tag("mergeCells"), count=str(len(merges)))
        for ref in merges:
            ET.SubElement(container, _tag("mergeCell"), ref=ref)
    ET.SubElement(sheet, _tag("pageMargins"), left="0.25", right="0.25", top="0.5", bottom="0.5", header="0.2", footer="0.2")
    ET.SubElement(sheet, _tag("pageSetup"), paperSize="9", orientation="landscape", fitToWidth="1", fitToHeight="0")
    return _xml(sheet)


def _styles():
    styles = ET.Element(_tag("styleSheet"))
    fonts = ET.SubElement(styles, _tag("fonts"), count="4")
    for size, bold, color in ((11, False, "FF343830"), (16, True, "FF35392F"),
                              (11, True, "FF343830"), (10, False, "FF65685F")):
        font = ET.SubElement(fonts, _tag("font"))
        ET.SubElement(font, _tag("sz"), val=str(size))
        ET.SubElement(font, _tag("color"), rgb=color)
        ET.SubElement(font, _tag("name"), val="微软雅黑")
        if bold:
            ET.SubElement(font, _tag("b"))
    fills = ET.SubElement(styles, _tag("fills"), count="7")
    for pattern, color in (("none", None), ("gray125", None), ("solid", "FFFFF3D9"),
                            ("solid", "FFFFFAEF"), ("solid", "FFF4F2ED"),
                            ("solid", "FFE7F0E7"), ("solid", "FFFAE9D9")):
        fill = ET.SubElement(fills, _tag("fill"))
        properties = ET.SubElement(fill, _tag("patternFill"), patternType=pattern)
        if color:
            ET.SubElement(properties, _tag("fgColor"), rgb=color)
            ET.SubElement(properties, _tag("bgColor"), indexed="64")
    borders = ET.SubElement(styles, _tag("borders"), count="2")
    for border_index in range(2):
        border = ET.SubElement(borders, _tag("border"))
        for side in ("left", "right", "top", "bottom", "diagonal"):
            edge = ET.SubElement(border, _tag(side), **({"style": "thin"} if border_index and side != "diagonal" else {}))
            if border_index and side != "diagonal":
                ET.SubElement(edge, _tag("color"), rgb="FFDDD9CF")
    base = ET.SubElement(styles, _tag("cellStyleXfs"), count="1")
    ET.SubElement(base, _tag("xf"), numFmtId="0", fontId="0", fillId="0", borderId="0")
    formats = ET.SubElement(styles, _tag("cellXfs"), count="8")
    for font_id, fill_id in ((0, 0), (1, 2), (2, 2), (0, 3), (0, 4), (0, 5), (0, 6), (3, 4)):
        xf = ET.SubElement(formats, _tag("xf"), numFmtId="0", fontId=str(font_id), fillId=str(fill_id),
                           borderId="1", xfId="0", applyAlignment="1", applyFill="1", applyFont="1", applyBorder="1")
        ET.SubElement(xf, _tag("alignment"), vertical="top", wrapText="1")
    named = ET.SubElement(styles, _tag("cellStyles"), count="1")
    ET.SubElement(named, _tag("cellStyle"), name="Normal", xfId="0", builtinId="0")
    return _xml(styles)


def _package(entries, exported):
    content = ET.Element("{{{}}}Types".format(CONTENT))
    for extension, kind in (("rels", "application/vnd.openxmlformats-package.relationships+xml"), ("xml", "application/xml")):
        ET.SubElement(content, "{{{}}}Default".format(CONTENT), Extension=extension, ContentType=kind)
    types = {
        "/xl/workbook.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        "/xl/styles.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml",
        "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
    }
    for i in (1, 2):
        types["/xl/worksheets/sheet{}.xml".format(i)] = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    for part, kind in types.items():
        ET.SubElement(content, "{{{}}}Override".format(CONTENT), PartName=part, ContentType=kind)
    entries["[Content_Types].xml"] = _xml(content)
    relationships = ET.Element("{{{}}}Relationships".format(PACKAGE_REL))
    for ident, target, kind in (("rId1", "xl/workbook.xml", REL + "/officeDocument"),
                                ("rId2", "docProps/core.xml", PACKAGE_REL + "/metadata/core-properties"),
                                ("rId3", "docProps/app.xml", REL + "/extended-properties")):
        ET.SubElement(relationships, "{{{}}}Relationship".format(PACKAGE_REL), Id=ident, Target=target, Type=kind)
    entries["_rels/.rels"] = _xml(relationships)
    workbook = ET.Element(_tag("workbook"))
    sheets = ET.SubElement(workbook, _tag("sheets"))
    workbook_relationships = ET.Element("{{{}}}Relationships".format(PACKAGE_REL))
    for i, name in enumerate(("节点情况汇总", "文档明细"), 1):
        ET.SubElement(sheets, _tag("sheet"), {"name": name, "sheetId": str(i), "{{{}}}id".format(REL): "rId{}".format(i)})
        ET.SubElement(workbook_relationships, "{{{}}}Relationship".format(PACKAGE_REL),
                      Id="rId{}".format(i), Target="worksheets/sheet{}.xml".format(i), Type=REL + "/worksheet")
    ET.SubElement(workbook_relationships, "{{{}}}Relationship".format(PACKAGE_REL), Id="rId3", Target="styles.xml", Type=REL + "/styles")
    entries["xl/workbook.xml"] = _xml(workbook)
    entries["xl/_rels/workbook.xml.rels"] = _xml(workbook_relationships)
    cp = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    dc = "http://purl.org/dc/elements/1.1/"
    dcterms = "http://purl.org/dc/terms/"
    xsi = "http://www.w3.org/2001/XMLSchema-instance"
    ET.register_namespace("cp", cp)
    ET.register_namespace("dc", dc)
    ET.register_namespace("dcterms", dcterms)
    ET.register_namespace("xsi", xsi)
    core = ET.Element("{{{}}}coreProperties".format(cp))
    ET.SubElement(core, "{{{}}}creator".format(dc)).text = "质量节点"
    ET.SubElement(core, "{{{}}}created".format(dcterms), {"{{{}}}type".format(xsi): "dcterms:W3CDTF"}).text = exported.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries["docProps/core.xml"] = _xml(core)
    appns = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
    app = ET.Element("{{{}}}Properties".format(appns))
    ET.SubElement(app, "{{{}}}Application".format(appns)).text = "质量节点"
    entries["docProps/app.xml"] = _xml(app)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return output.getvalue()


def export_workbook(group):
    """Return XLSX bytes containing latest node snapshots and document details."""
    exported = datetime.now(CHINA_TIME)
    export_time = exported.strftime("%Y-%m-%d %H:%M:%S")
    nodes = _ordered_nodes(group)
    if len(nodes) > 16381:
        raise ValueError("节点数量超过单张 Excel 工作表支持的列数。")
    name = _clean(group.get("name", "未命名项目组"))
    teacher = _clean(group.get("teacher", ""))
    width = 3 + len(nodes)
    headers = [("项目组（老师姓名）", 2), ("对接学生", 2), ("导出时间（北京时间）", 2)]
    template_row = [("项目基本信息", 3), ("", 3), ("", 3)]
    summary_row = [(name, 0), (teacher, 0), (export_time, 0)]
    details = []
    for node, path in nodes:
        record = _latest_record(node)
        documents = _documents(node, record)
        status = record.get("status", "未开始") if record else "未开始"
        note = _clean(record.get("note", "")) if record else "尚未保存情况记录。"
        description = _clean(record.get("node_description", node.get("description", ""))) if record else _clean(node.get("description", ""))
        author = record.get("author", "") if record else ""
        saved = _date(record.get("created_at")) if record else ""
        version = record.get("version", "") if record else ""
        headers.append((" / ".join(path), 2))
        template_row.append(("\n".join(d.get("name", "") for d in documents) or "未设置文档模板", 3))
        body = ["节点情况：" + status, "本次情况：" + (note or "未填写")]
        if record and record.get("node_title") and record["node_title"] != node.get("title"):
            body.append("记录时节点名称：" + record["node_title"])
        for document in documents:
            body.append("\n{}\n完成情况：{}\n修改意见：{}".format(
                document.get("name", ""), document.get("status", "尚未记录"), document.get("note") or "未填写"))
        if record:
            body.append("\n记录时间：{}\n记录人：{}\n版本：{}".format(saved, author, version))
        summary_row.append(("\n".join(body), _status_style(status)))
        for document in documents or [{}]:
            doc_status = document.get("status", "")
            row = [name, " / ".join(path), node.get("title", ""), status,
                   document.get("name", "未设置文档模板"), doc_status, document.get("note", ""),
                   description, note, author, saved, version]
            if document.get("unrecorded"):
                row[9:12] = ["", "", ""]
            details.append(([(value, _status_style(doc_status or status)) for value in row], 90))
    first_rows = [([(name + " · 节点完成情况    导出时间：" + export_time, 1)], 34), (headers, 75), (template_row, 125),
                  (summary_row, 300), ([(REMARK, 7)], 35)]
    detail_headers = ["项目组", "流程路径", "节点", "节点状态", "文档模板", "文档情况", "修改意见",
                      "节点说明", "本次情况", "记录人", "记录时间（北京时间）", "版本"]
    detail_rows = [([(value, 2) for value in detail_headers], 32)] + details
    entries = {
        "xl/styles.xml": _styles(),
        "xl/worksheets/sheet1.xml": _sheet([20, 16, 25] + [38] * len(nodes), first_rows, 3,
                                          ["A1:{}1".format(_column(width)), "A5:{}5".format(_column(width))]),
        "xl/worksheets/sheet2.xml": _sheet([20, 38, 28, 15, 42, 15, 48, 48, 48, 18, 24, 10], detail_rows, 1,
                                          autofilter="A1:L{}".format(max(1, len(detail_rows)))),
    }
    return _package(entries, exported)
