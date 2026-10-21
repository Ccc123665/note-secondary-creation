# -*- coding: utf-8 -*-
"""relayout_pdf.py —— PDF 二创（文档重排）渲染器

面向「发一个 PDF 来做二创」的场景：把原 PDF 的**全部内容**重新排版成一份
朴素、专业、重点突出的 A4 文档 PDF。

原则：
  - 不做总结：doc_spec.json 里装的是全文，一条不删；本脚本只负责排版
  - 不出图片：输出矢量文本 PDF（字体嵌入、文字可选中/可搜索、体积小），不是图片拼版
  - 重点突出：数字 / 日期 / 比例 / 关键词自动加粗；关键数据用 callout 强调框
  - 字体：方正兰亭黑系列（assets/fonts，可商用）
  - 品牌：页脚中公品牌 + 小鹿形象

doc_spec.json 结构：
{
  "meta": {"title": "…", "subtitle": "…", "source": "来源：…",
           "brand": "中公教育", "deer": "cheer", "accent": "tea"},
  "sections": [
    {"heading": "一、……",
     "paras": ["正文段……"],
     "bullets": ["要点……"],
     "table": {"cols": ["列A","列B"], "rows": [["…","…"]]},
     "callout": {"label": "关键时间", "text": "……"}}
  ]
}

用法：
    python relayout_pdf.py --spec doc_spec.json --out 排版版.pdf
"""
import argparse
import json
import os
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether,
                                Image as RLImage)

W, H = A4
ML = MR = 20 * mm
MT = 18 * mm
MB = 24 * mm
INK = colors.HexColor("#1A1D21")
SUB = colors.HexColor("#5A626B")
RULE = colors.HexColor("#D8DCDF")

TINTS = {
    "tea":     {"deep": "#1E4B3E", "soft": "#EDF2EF", "line": "#CFE0D7"},
    "pine":    {"deep": "#144A47", "soft": "#EBF3F2", "line": "#CCE0DD"},
    "inkblue": {"deep": "#1B3550", "soft": "#EDF1F6", "line": "#CFDCE8"},
    "brick":   {"deep": "#7E2A23", "soft": "#F7EFEC", "line": "#E8D2CC"},
    "slate":   {"deep": "#2A2F36", "soft": "#F1F2F4", "line": "#DBDEE2"},
}

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FDIR = os.path.join(_HERE, "assets", "fonts")


def _reg(name, fname, fallback):
    p = os.path.join(_FDIR, fname)
    if not os.path.exists(p):
        p = fallback
    try:
        pdfmetrics.registerFont(TTFont(name, p))
    except Exception:
        pass


# 方正兰亭黑系列：常规 / 粗黑 / 准黑；缺失回退系统黑体
_reg("LT", "FZLTHJW.TTF", r"C:/Windows/Fonts/simhei.ttf")
_reg("LTB", "FZLTCHJW.TTF", r"C:/Windows/Fonts/simhei.ttf")
_reg("LTH", "FZLTTHJW.TTF", r"C:/Windows/Fonts/simhei.ttf")

# 重点突出：数字 / 日期 / 比例 / 高频资格词自动加粗
_EMPH = re.compile(
    r"(20\d{2}\s*年|\d{1,2}\s*月\d{1,2}\s*日|\d{1,2}\s*月|\d+\s*(?:\.\d+)?\s*"
    r"(?:%|％|人|名|个|位|万|亿|分|分钟|小时|日|天|年|月|周|名)|"
    r"本科及以上|不限|应届|往届|毕业\s*2\s*年内|事业编|编制|合格|资格|条件|截止|仅限|须|必须)")


def _xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def emph(s):
    """转义 XML 后，把数字/日期/关键词包进 <b>，实现重点突出。"""
    return _EMPH.sub(r"<b>\1</b>", _xml(s))


def styles(deep):
    base = dict(wordWrap="CJK")
    return {
        "title":    ParagraphStyle("t", fontName="LTH", fontSize=16.5, leading=22,
                                   textColor=INK, spaceAfter=3, **base),
        "subtitle": ParagraphStyle("s", fontName="LT", fontSize=10, leading=15,
                                   textColor=SUB, spaceAfter=8, **base),
        "h2":       ParagraphStyle("h2", fontName="LTB", fontSize=12.5, leading=18,
                                   textColor=colors.HexColor(deep), spaceBefore=11, spaceAfter=5, **base),
        "body":     ParagraphStyle("b", fontName="LT", fontSize=10.5, leading=17.5,
                                   textColor=INK, alignment=TA_JUSTIFY, spaceAfter=5, **base),
        "bullet":   ParagraphStyle("bu", fontName="LT", fontSize=10.5, leading=16.5,
                                   textColor=INK, leftIndent=13, bulletIndent=2, spaceAfter=3, **base),
        "co_lab":   ParagraphStyle("cl", fontName="LTB", fontSize=10, leading=14,
                                   textColor=colors.HexColor(deep), spaceAfter=2, **base),
        "co_txt":   ParagraphStyle("ct", fontName="LT", fontSize=10.5, leading=16,
                                   textColor=INK, **base),
        "cell":     ParagraphStyle("c", fontName="LT", fontSize=9.5, leading=13.5,
                                   textColor=INK, **base),
        "cellh":    ParagraphStyle("ch", fontName="LTB", fontSize=9.5, leading=13.5,
                                   textColor=colors.white, **base),
    }


def _logo_hdr(st, accent):
    meta_path = os.path.join(_HERE, "assets", "logo", "offcn_dark.png")
    cells = []
    logo_w = 0
    try:
        ir = ImageReader(meta_path)
        iw, ih = ir.getSize()
        lh = 26
        logo_w = iw / ih * lh
        cells.append(RLImage(meta_path, width=logo_w, height=lh))
    except Exception:
        cells.append("")
    return cells, logo_w


def build_story(spec):
    meta = spec.get("meta") or {}
    accent = TINTS.get(meta.get("accent", "tea"), TINTS["tea"])
    st = styles(accent["deep"])
    story = []

    # ---- 标题区：logo + 主标题 + 副标题 ----
    logo_cell, logo_w = _logo_hdr(st, accent)
    title_p = Paragraph(_xml(meta.get("title", "")), st["title"])
    sub_p = Paragraph(_xml(meta.get("subtitle", "")), st["subtitle"])
    gap = 8
    head = Table([[logo_cell[0], [title_p, sub_p]]],
                 colWidths=[logo_w + gap, W - ML - MR - logo_w - gap])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(head)
    bar = Table([[""]], colWidths=[W - ML - MR], rowHeights=[3])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(accent["deep"])),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(Spacer(1, 4))
    story.append(bar)
    story.append(Spacer(1, 8))

    # ---- 各章节 ----
    for sec in spec.get("sections", []):
        flows = []
        head_txt = sec.get("heading")
        if head_txt:
            flows.append(Paragraph(_xml(head_txt), st["h2"]))
        for p in sec.get("paras", []):
            flows.append(Paragraph(emph(p), st["body"]))
        for b in sec.get("bullets", []):
            flows.append(Paragraph("•&nbsp;" + emph(b), st["bullet"]))
        tbl = sec.get("table")
        if tbl and tbl.get("cols"):
            cols = tbl["cols"]
            data = [[Paragraph(_xml(c), st["cellh"]) for c in cols]]
            for r in tbl.get("rows", []):
                data.append([Paragraph(emph(c), st["cell"]) for c in r])
            ncol = len(cols)
            t = Table(data, colWidths=[(W - ML - MR) / ncol] * ncol, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(accent["deep"])),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(accent["soft"])]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(accent["line"])),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flows.append(t)
            flows.append(Spacer(1, 5))
        co = sec.get("callout")
        if co:
            inner = [[Paragraph(_xml(co.get("label", "重点")), st["co_lab"])],
                     [Paragraph(emph(co.get("text", "")), st["co_txt"])]]
            t = Table(inner, colWidths=[W - ML - MR])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(accent["soft"])),
                ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(accent["deep"])),
                ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            flows.append(t)
            flows.append(Spacer(1, 6))
        # 标题不孤行：标题与紧跟的第一块同页
        if head_txt and len(flows) >= 2:
            story.append(KeepTogether(flows[:2]))
            story.extend(flows[2:])
        else:
            story.extend(flows)
    return story


def make_onpage(spec):
    meta = spec.get("meta") or {}
    source = meta.get("source", "")
    brand = meta.get("brand", "中公教育")
    deer_path = os.path.join(_HERE, "assets", "deer", (meta.get("deer", "cheer")) + ".png")

    def _draw(canv, doc):
        canv.saveState()
        base = 11 * mm
        canv.setStrokeColor(RULE)
        canv.setLineWidth(0.6)
        canv.line(ML, base + 8 * mm, W - MR, base + 8 * mm)
        canv.setFont("LT", 8.5)
        canv.setFillColor(SUB)
        if source:
            canv.drawString(ML, base, source[:90])
        bw = canv.stringWidth(brand, "LT", 8.5)
        canv.drawString(W - MR - bw, base, brand)
        try:
            ir = ImageReader(deer_path)
            iw, ih = ir.getSize()
            dh = 11 * mm
            dw = iw / ih * dh
            canv.drawImage(deer_path, W - MR - dw, base - 2 * mm, dw, dh, mask="auto")
        except Exception:
            pass
        canv.restoreState()

    return _draw


class NumberedCanvas(pdfcanvas.Canvas):
    """两遍构建，拿到总页数，页脚居中输出「第 X 页 / 共 Y 页」。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("LT", 8.5)
            self.setFillColor(SUB)
            self.drawCentredString(W / 2, 11 * mm, "第 %d 页 / 共 %d 页" % (self._pageNumber, total))
            super().showPage()
        super().save()


def main():
    ap = argparse.ArgumentParser(description="PDF 二创：文档重排为 A4 专业 PDF")
    ap.add_argument("--spec", required=True, help="doc_spec.json")
    ap.add_argument("--out", required=True, help="输出 排版版.pdf")
    a = ap.parse_args()

    spec = json.load(open(a.spec, encoding="utf-8"))
    meta = spec.get("meta") or {}
    doc = BaseDocTemplate(
        a.out, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB,
        title=meta.get("title", "二创文档"), author=meta.get("brand", "中公教育"),
        subject="素材排版二创 · 文档重排")
    frame = Frame(ML, MB, W - ML - MR, H - MT - MB, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=make_onpage(spec))])
    doc.build(build_story(spec), canvasmaker=NumberedCanvas)
    print("pdf ->", a.out)


if __name__ == "__main__":
    main()
