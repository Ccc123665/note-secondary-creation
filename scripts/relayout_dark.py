# -*- coding: utf-8 -*-
"""relayout_dark.py —— 深色一页纸的轻改渲染器

对应素材类型：深色底 + 金/橙点缀 + 浅色表格块（如烟草考情一页纸）。

设计原则与 relayout_light.py 一致：
  1. 复刻原素材骨架：深色底就还是深色底，表格块保持「深表头 + 米白表体」
  2. 只动四个旋钮：主色相（暖棕黑/冷墨黑）、点缀色、序号形态、模块顺序
  3. 不换字号层级、不加装饰、不做海报化

输出：固定 1080×1440 分页。
"""

import argparse
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1440
M = 56
GAP = 16
FOOT_H = 72
CONT_TOP = 96
TMP_H = 9000

# 字体：中公宣传品唯一允许的可商用字体 = 方正兰亭黑系列（随包放 assets/fonts，见 fonts.json）。
# 包内优先，缺失回退 Windows 雅黑/黑体，保证换机器也能出图。
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FDIR = os.path.join(_HERE, "assets", "fonts")
FONT_B = [os.path.join(_FDIR, "FZLTCHJW.TTF"), r"C:/Windows/Fonts/msyhbd.ttc"]  # 兰亭粗黑 → 雅黑粗
FONT_R = [os.path.join(_FDIR, "FZLTHJW.TTF"),  r"C:/Windows/Fonts/msyh.ttc"]    # 兰亭黑   → 雅黑
FONT_H = [os.path.join(_FDIR, "FZLTTHJW.TTF"), r"C:/Windows/Fonts/simhei.ttf"]  # 兰亭准黑 → 黑体

PUNCT_TAIL = "，。、；：？！）》」』”’,.;:?!)]}%"
ASCII_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\.\-:/×%+—]*")

# 底色主题：暖棕黑（原素材）/ 冷墨黑（二创）
THEMES = {
    "warm": {"bg": "#191007", "card": "#231A12", "card2": "#1E1710", "border": "#463620",
             "rule": "#3A2E22", "txt": "#F5EFE3", "sub": "#A89D8C", "dim": "#CFC5B2"},
    "ink": {"bg": "#12151A", "card": "#1A1F26", "card2": "#161B21", "border": "#2F3742",
            "rule": "#2A313B", "txt": "#EFF2F5", "sub": "#9AA3AE", "dim": "#BCC5CF"},
    "forest": {"bg": "#0E1512", "card": "#16211C", "card2": "#131C18", "border": "#2C3B34",
               "rule": "#27332D", "txt": "#EEF3EF", "sub": "#9CA9A1", "dim": "#C4D0C8"},
    # 深靛蓝：冷色底 + 冷白表格，与原素材暖棕黑拉开最大
    "navy": {"bg": "#0C1424", "card": "#14203A", "card2": "#101A2E", "border": "#26374F",
             "rule": "#1F2C42", "txt": "#EEF3FA", "sub": "#8FA0B8", "dim": "#BCC9DA",
             "tbl": {"head": "#1D3050", "head_txt": "#E8F0FA", "body": "#F6F9FD",
                     "txt": "#101B2C", "sub": "#54677F", "rule": "#DCE6F1", "zebra": "#EDF3FA"}},
}

ACCENTS = {
    "gold": {"a": "#E4B95B", "b": "#FE9A3C", "c": "#7FC4E8"},
    "copper": {"a": "#E0A76A", "b": "#F07A4B", "c": "#89C6D8"},
    "jade": {"a": "#D8C89A", "b": "#E8A85C", "c": "#8FD0BE"},
    # 冰蓝 + 砂橙 + 薄荷：冷底上的冷点缀，与原素材金橙差异明显
    "ice": {"a": "#79B8F0", "b": "#F2A25C", "c": "#8FE0C4"},
}

# 表格块固定浅色（原素材如此，不随主题变）
TBL_HEAD = "#4A3113"
TBL_HEAD_TXT = "#F3E7D2"
TBL_BODY = "#F9F5EC"
TBL_TXT = "#241A0E"
TBL_SUB = "#6E5B41"
TBL_RULE = "#E2D5BE"
TBL_ZEBRA = "#F3ECDD"
TBL_TOTAL = "#4A3113"


def tokens(s):
    out, i, n = [], 0, len(s)
    while i < n:
        m = ASCII_RUN.match(s, i)
        if m:
            out.append(m.group())
            i = m.end()
        else:
            out.append(s[i])
            i += 1
    return out


class Doc:
    def __init__(self, spec):
        self.spec = spec
        self.W = int((spec.get("size") or {}).get("width", W))
        self.H = int((spec.get("size") or {}).get("height", H))
        self.M = M
        self.cw = self.W - 2 * self.M
        th = THEMES.get(spec.get("theme", "warm"), THEMES["warm"])
        self.C = dict(th)
        self.A = ACCENTS.get(spec.get("accent", "gold"), ACCENTS["gold"])
        self.T = th.get("tbl") or {"head": TBL_HEAD, "head_txt": TBL_HEAD_TXT, "body": TBL_BODY,
                                   "txt": TBL_TXT, "sub": TBL_SUB, "rule": TBL_RULE, "zebra": TBL_ZEBRA}
        self.blocks_src = spec.get("blocks") or []
        if spec.get("renumber", True):
            nums = "壹贰叁肆伍陆柒捌玖拾"
            n = 0
            for b in self.blocks_src:
                if b.get("type") == "sec":
                    b["no"] = nums[n] if n < len(nums) else str(n + 1)
                    n += 1
        self._fc = {}
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assets = os.path.join(here, "assets")
        self.header_img = None
        self.header_h = 0
        self._logo = {}
        self._deer_raw = None
        self.deer_on = bool(spec.get("deer", True))

    # ---------- 基础 ----------
    def font(self, size, bold=False):
        size = max(11, int(round(size)))
        key = (size, bold)
        if key in self._fc:
            return self._fc[key]
        f = None
        for p in ((FONT_B + FONT_H) if bold else (FONT_R + FONT_H)):
            try:
                f = ImageFont.truetype(p, size)
                break
            except Exception:
                continue
        self._fc[key] = f or ImageFont.load_default()
        return self._fc[key]

    def wrap(self, text, font, maxw):
        out, cur = [], ""
        for tk in tokens(str(text)):
            if tk == "\n":
                out.append(cur)
                cur = ""
                continue
            if font.getlength(cur + tk) <= maxw:
                cur += tk
            elif tk in PUNCT_TAIL and cur:
                cur += tk
            else:
                if font.getlength(tk) > maxw:
                    for ch in tk:
                        if font.getlength(cur + ch) <= maxw:
                            cur += ch
                        else:
                            out.append(cur)
                            cur = ch
                else:
                    if cur:
                        out.append(cur)
                    cur = tk
        if cur:
            out.append(cur)
        return out or [""]

    def text(self, d, xy, s, font, fill, maxw=None, lh=1.55, max_lines=None, align="l"):
        x, y = xy
        lines = self.wrap(s, font, maxw) if maxw else [str(s)]
        if max_lines:
            lines = lines[:max_lines]
        step = int(font.size * lh)
        for i, ln in enumerate(lines):
            yy = y + i * step
            if align == "r" and maxw:
                d.text((x + maxw - font.getlength(ln), yy), ln, font=font, fill=fill)
            elif align == "c" and maxw:
                d.text((x + (maxw - font.getlength(ln)) / 2, yy), ln, font=font, fill=fill)
            else:
                d.text((x, yy), ln, font=font, fill=fill)
        return y + len(lines) * step

    def canvas(self, h):
        im = Image.new("RGB", (self.W, h), self.C["bg"])
        return im, ImageDraw.Draw(im)

    def logo_width(self, h):
        p = os.path.join(self.assets, "logo", "offcn_dark.png")
        try:
            w, hh = Image.open(p).size
            return int(w / hh * h)
        except Exception:
            return int(h * 2.1)

    def logo(self, im, x, y, h=30, dark_card=True):
        key = (h, dark_card)
        if key not in self._logo:
            name = "offcn_dark.png" if dark_card else "offcn_light.png"
            p = os.path.join(self.assets, "logo", name)
            try:
                l = Image.open(p).convert("RGBA")
                r = h / l.size[1]
                l = l.resize((max(1, int(l.size[0] * r)), h), Image.LANCZOS)
            except Exception:
                l = False
            self._logo[key] = l
        l = self._logo[key]
        if l:
            im.paste(l, (int(x), int(y)), l)
            return l.size[0]
        return 0

    def deer(self, im, h=36):
        """小鹿形象：页脚右下角品牌位，默认 cheer.png；姿态用 footer.deer 指定。"""
        if not self.deer_on:
            return 0
        if self._deer_raw is None:
            pose = (self.spec.get("footer") or {}).get("deer", "cheer")
            p = os.path.join(self.assets, "deer", f"{pose}.png")
            try:
                self._deer_raw = Image.open(p).convert("RGBA")
            except Exception:
                self._deer_raw = False
        if not self._deer_raw:
            return 0
        raw = self._deer_raw
        r = h / raw.size[1]
        d2 = raw.resize((max(1, int(raw.size[0] * r)), h), Image.LANCZOS)
        x = self.W - self.M - d2.size[0]
        y = self.H - 6 - h
        im.paste(d2, (int(x), int(y)), d2)
        return d2.size[0]

    def pill(self, d, x, y, txt, bg, fg, fsize=15, padx=14, h=30):
        f = self.font(fsize, True)
        w = f.getlength(txt) + padx * 2
        d.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=bg)
        d.text((x + padx, y + (h - f.size) / 2 - 2), txt, font=f, fill=fg)
        return w

    # ---------- 页头 ----------
    def build_header(self):
        hd = self.spec.get("header") or {}
        im, d = self.canvas(TMP_H)
        y = 40
        # logo 白底小卡：框随 logo 尺寸走，不再留大片空白
        logoh = int(hd.get("logo_h", 36))
        lwid = self.logo_width(logoh)
        pad_x, pad_y = 16, 9
        box_w, box_h = lwid + pad_x * 2, logoh + pad_y * 2
        d.rounded_rectangle([self.M, y, self.M + box_w, y + box_h], radius=10, fill="#FFFFFF")
        self.logo(im, self.M + pad_x, y + pad_y, logoh)
        if hd.get("tag"):
            f = self.font(15, True)
            w = f.getlength(hd["tag"]) + 30
            ty = y + (box_h - 38) // 2
            d.rounded_rectangle([self.W - self.M - w, ty, self.W - self.M, ty + 38],
                                radius=19, outline=self.A["a"], width=1)
            d.text((self.W - self.M - w + 15, ty + 9), hd["tag"], font=f, fill=self.A["a"])
        y += box_h + 22

        if hd.get("kicker"):
            y = self.text(d, (self.M, y), hd["kicker"], self.font(16), self.C["sub"], maxw=self.cw, lh=1.5) + 10

        # 主标题：分段着色
        y += 6
        f_t = self.font(hd.get("title_size", 60), True)
        x = self.M
        for seg in hd.get("title", []):
            s, tone = seg[0], (seg[1] if len(seg) > 1 else "txt")
            fill = self.C["txt"] if tone == "txt" else self.A["a"] if tone == "a" else self.A["b"]
            d.text((x, y), s, font=f_t, fill=fill)
            x += f_t.getlength(s)
        y += int(f_t.size * 1.22)

        for ln in hd.get("lines") or []:
            y = self.text(d, (self.M, y), ln, self.font(20), self.C["txt"], maxw=self.cw, lh=1.6) + 2
        y += 14

        metrics = hd.get("metrics") or []
        if metrics:
            n = len(metrics)
            gap = 12
            bw = (self.cw - gap * (n - 1)) / n
            bh = 104
            for i, m in enumerate(metrics):
                bx = self.M + i * (bw + gap)
                d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=10,
                                    fill=self.C["card"], outline=self.C["border"], width=1)
                f = self.font(14)
                d.text((bx + 16, y + 16), str(m.get("l", "")), font=f, fill=self.C["sub"])
                fv = self.font(32, True)
                while fv.getlength(str(m.get("v", ""))) > bw - 32 and fv.size > 18:
                    fv = self.font(fv.size - 2, True)
                d.text((bx + 16, y + 52), str(m.get("v", "")), font=fv,
                       fill=self.A["a"] if m.get("tone", "a") == "a" else self.A["b"])
            y += bh + 20
        self.header_img = im.crop((0, 0, self.W, int(y) + 8))
        self.header_h = self.header_img.size[1]

    # ---------- 区块 ----------
    def _sec(self, d, b, y):
        no = b.get("no") or ""
        f = self.font(24, True)
        bw = 46
        d.rounded_rectangle([self.M, y + 2, self.M + bw, y + 42], radius=8, fill=self.A["a"])
        d.text((self.M + (bw - f.getlength(no)) / 2, y + 8), no, font=f, fill="#1A1208")
        ft = self.font(29, True)
        d.text((self.M + bw + 16, y + 4), b.get("title", ""), font=ft, fill=self.C["txt"])
        if b.get("right"):
            fr = self.font(15)
            d.text((self.W - self.M - fr.getlength(b["right"]), y + 16), b["right"], font=fr, fill=self.C["sub"])
        return y + 48

    def _callout(self, d, b, y):
        f = self.font(19)
        inner = self.cw - 48 - (self.font(15, True).getlength(b.get("label", "")) + 34 if b.get("label") else 0)
        lines = []
        for para in str(b.get("text", "")).split("\n"):
            lines += self.wrap(para, f, inner)
        lh = int(19 * 1.58)
        bh = 21 + len(lines) * lh + 11
        d.rounded_rectangle([self.M, y, self.W - self.M, y + bh], radius=12,
                            fill=self.C["card2"], outline=self.C["border"], width=1)
        x = self.M + 20
        if b.get("label"):
            w = self.pill(d, x, y + 21, b["label"], self.A.get(b.get("tone", "a"), self.A["a"]), "#1A1208", 15, 14, 30)
            x += w + 16
        ty = y + 21
        for ln in lines:
            d.text((x, ty), ln, font=f, fill=self.C["txt"])
            ty += lh
        return y + bh

    def _timeline(self, d, b, y):
        items = b.get("items") or []
        n = max(1, len(items))
        gap = 8
        bw = (self.cw - 16 - gap * (n - 1)) / n
        # 逐列量高
        f_h = self.font(19, True)
        f_s = self.font(13)
        hs = []
        for it in items:
            hh = 16 + 30 + 12 + int(19 * 1.35)
            for s in it.get("sub") or []:
                hh += len(self.wrap(s, f_s, bw - 6)) * int(13 * 1.62)
            hs.append(hh)
        bh = max(hs) + 22
        d.rounded_rectangle([self.M, y, self.W - self.M, y + bh], radius=12,
                            fill=self.C["card"], outline=self.C["border"], width=1)
        for i, it in enumerate(items):
            bx = self.M + 8 + i * (bw + gap)
            tone = it.get("tone", 0)
            bg = [self.A["a"], self.A["b"], self.A["c"]][tone % 3]
            fl = self.font(14, True)
            w = fl.getlength(it.get("d", "")) + 22
            d.rounded_rectangle([bx + (bw - w) / 2, y + 16, bx + (bw - w) / 2 + w, y + 46],
                                radius=15, fill=bg)
            d.text((bx + (bw - w) / 2 + 11, y + 24), it.get("d", ""), font=fl, fill="#1A1208")
            ty = y + 58
            for ln in self.wrap(it.get("h", ""), f_h, bw - 6):
                d.text((bx + (bw - self.font(19, True).getlength(ln)) / 2, ty), ln, font=f_h, fill=self.C["txt"])
                ty += int(19 * 1.35)
            for s in it.get("sub") or []:
                for ln in self.wrap(s, f_s, bw - 8):
                    d.text((bx + (bw - f_s.getlength(ln)) / 2, ty + 4), ln, font=f_s, fill=self.C["dim"])
                    ty += int(13 * 1.62)
        return y + bh


    def _vtimeline(self, d, b, y):
        """竖排时间轴：日期胶囊在左、轴线居中、标题与说明同行（放不下才换行）。"""
        items = b.get("items") or []
        f_d = self.font(13, True)
        f_h = self.font(19, True)
        f_s = self.font(14)
        axis = self.M + 92
        tx = axis + 22
        tw = self.W - self.M - tx
        rows, hs = [], []
        for it in items:
            hl = self.wrap(it.get("h", ""), f_h, tw)
            sub = " · ".join(it.get("sub") or [])
            inline = False
            sl = []
            if sub and len(hl) == 1:
                avail = tw - f_h.getlength(hl[0]) - 16
                cand = self.wrap(sub, f_s, avail) if avail > 200 else []
                if len(cand) == 1:
                    sl, inline = cand, True
            if not inline:
                sl = self.wrap(sub, f_s, tw) if sub else []
            hh = (max(32, len(hl) * 26) if inline else max(32, len(hl) * 26 + len(sl) * 21)) + 15
            rows.append((it, hl, sl, inline))
            hs.append(hh)
        total = sum(hs)
        d.line([(axis, y + 12), (axis, y + total - 26)], fill=self.C["border"], width=2)
        yy = y
        for i, (it, hl, sl, inline) in enumerate(rows):
            tone = it.get("tone", 0)
            bg = [self.A["a"], self.A["b"], self.A["c"]][tone % 3]
            d.rounded_rectangle([self.M, yy + 2, self.M + 78, yy + 32], radius=15, fill=bg)
            d.text((self.M + 39 - f_d.getlength(it.get("d", "")) / 2, yy + 9), it.get("d", ""),
                   font=f_d, fill="#0C1424")
            d.ellipse([axis - 5, yy + 12, axis + 5, yy + 22], fill=bg)
            ty = yy + 2
            for ln in hl:
                d.text((tx, ty), ln, font=f_h, fill=self.C["txt"])
                ty += 26
            if inline:
                d.text((tx + f_h.getlength(hl[0]) + 16, yy + 6), sl[0], font=f_s, fill=self.C["dim"])
            else:
                for ln in sl:
                    d.text((tx, ty + 1), ln, font=f_s, fill=self.C["dim"])
                    ty += 21
            yy += hs[i]
        return y + total

    def _table(self, d, b, y):
        if b.get("cont"):
            pass
        cols = b.get("cols") or []
        rows = b.get("rows") or []
        total = b.get("total")
        n = max(1, len(cols))
        ratios = b.get("widths") or [1.0] * n
        ssum = sum(ratios) or 1
        widths = [self.cw * r / ssum for r in ratios]
        xs = [self.M + sum(widths[:i]) for i in range(n)]
        padx, pady = 13, 9
        num_cols = set(b.get("num_cols") or [])
        bold_first = b.get("bold_first", True)

        f_hd = self.font(16, True)
        f_td = self.font(17)
        lh = int(17 * 1.45)

        # 表头
        hh = 42
        d.rounded_rectangle([self.M, y, self.W - self.M, y + hh], radius=8, fill=self.T["head"])
        d.rectangle([self.M, y + hh - 10, self.W - self.M, y + hh], fill=self.T["head"])
        for i, c in enumerate(cols):
            if i in num_cols:
                d.text((xs[i] + widths[i] - padx - f_hd.getlength(str(c)), y + 11), str(c), font=f_hd, fill=self.A["a"])
            else:
                d.text((xs[i] + padx, y + 11), str(c), font=f_hd, fill=self.T["head_txt"])
        yy = y + hh

        def draw_row(row, bg, fg, fg_sub, is_total=False):
            nonlocal yy
            cells, hrow = [], 30
            for i in range(n):
                val = str(row[i]) if i < len(row) else ""
                f = self.font(17, True) if (i == 0 and bold_first and not is_total) else f_td
                lines = self.wrap(val, f, widths[i] - 2 * padx)
                hrow = max(hrow, len(lines) * lh + 2 * pady)
                cells.append((lines, f))
            d.rectangle([self.M, yy, self.W - self.M, yy + hrow], fill=bg)
            for i, (lines, f) in enumerate(cells):
                ty = yy + pady
                for ln in lines:
                    if i in num_cols:
                        fn = self.font(19, True)
                        d.text((xs[i] + widths[i] - padx - fn.getlength(ln), ty - 1), ln, font=fn,
                               fill=self.A["a"] if not is_total else self.A["a"])
                    else:
                        d.text((xs[i] + padx, ty), ln, font=f,
                               fill=fg if (i == 0 and bold_first) else fg_sub)
                    ty += lh
            d.line([(self.M, yy + hrow), (self.W - self.M, yy + hrow)], fill=self.T["rule"], width=1)
            yy += hrow

        for r, row in enumerate(rows):
            draw_row(row, self.T["zebra"] if (r % 2 == 1) else self.T["body"], self.T["txt"], self.T["sub"])
        if total:
            draw_row(total, self.T["head"], self.T["head_txt"], self.T["head_txt"], is_total=True)
            d.rounded_rectangle([self.M, yy - 2, self.W - self.M, yy + 2], radius=4, fill=self.T["head"])
        note = b.get("note")
        if note:
            d.ellipse([self.M + 2, yy + 18, self.M + 10, yy + 26], fill=self.A["a"])
            yy = self.text(d, (self.M + 22, yy + 10), note, self.font(16), self.C["sub"], maxw=self.cw - 22, lh=1.55)
        return yy + 4

    def _cards(self, d, b, y):
        items = b.get("items") or []
        cols = int(b.get("cols", 3))
        gap = 12
        cw = (self.cw - gap * (cols - 1)) / cols
        pad = 16
        f_h = self.font(18, True)
        f_b = self.font(21, True)
        f_s = self.font(int(b.get("body_size", 15)))
        prep, hs = [], []
        for it in items:
            hh = 14
            hl = self.wrap(it.get("h", ""), f_h, cw - pad * 2)
            hh += len(hl) * int(18 * 1.4) + 6
            bl = self.wrap(it.get("b", ""), f_b, cw - pad * 2) if it.get("b") else []
            hh += len(bl) * int(21 * 1.45) + (6 if bl else 0)
            sl = []
            for s in it.get("sub") or []:
                sl += self.wrap(s, f_s, cw - pad * 2)
            hh += len(sl) * int(f_s.size * 1.5) + 12
            prep.append((it, hl, bl, sl))
            hs.append(hh)
        row_h = max(hs) if hs else 60
        rows = (len(items) + cols - 1) // cols
        for i, (it, hl, bl, sl) in enumerate(prep):
            r, c = divmod(i, cols)
            x = self.M + c * (cw + gap)
            yy = y + r * (row_h + gap)
            d.rounded_rectangle([x, yy, x + cw, yy + row_h], radius=10,
                                fill=self.C["card"], outline=self.C["border"], width=1)
            ty = yy + 12
            for ln in hl:
                d.text((x + pad, ty), ln, font=f_h, fill=self.C["sub"])
                ty += int(18 * 1.4)
            ty += 2
            for ln in bl:
                d.text((x + pad, ty), ln, font=f_b, fill=self.A["a"])
                ty += int(21 * 1.45)
            ty += 2
            for ln in sl:
                d.text((x + pad, ty), ln, font=f_s, fill=self.C["dim"])
                ty += int(f_s.size * 1.5)
        return y + rows * (row_h + gap) - gap

    def _list(self, d, b, y):
        items = b.get("items") or []
        for it in items:
            f_h = self.font(19, True)
            f_p = self.font(18)
            hl = self.wrap(it.get("h", ""), f_h, self.cw - 34)
            pl = self.wrap(it.get("p", ""), f_p, self.cw - 34) if it.get("p") else []
            bh = 14 + len(hl) * int(19 * 1.4) + 4 + len(pl) * int(18 * 1.55) + 12
            d.rounded_rectangle([self.M, y, self.W - self.M, y + bh], radius=10,
                                fill=self.C["card"], outline=self.C["border"], width=1)
            d.rectangle([self.M, y + 10, self.M + 4, y + bh - 10], fill=self.A["a"])
            ty = y + 14
            for ln in hl:
                d.text((self.M + 22, ty), ln, font=f_h, fill=self.A["a"])
                ty += int(19 * 1.45)
            ty += 4
            for ln in pl:
                d.text((self.M + 22, ty), ln, font=f_p, fill=self.C["txt"])
                ty += int(18 * 1.55)
            y += bh + 10
        return y - 10

    def _quote(self, d, b, y):
        f_l = self.font(15, True)
        f_t = self.font(21, True)
        inner = self.cw - 48
        lines = []
        for para in str(b.get("text", "")).split("\n"):
            lines += self.wrap(para, f_t, inner)
        lh = int(21 * 1.55)
        bh = 22 + 26 + len(lines) * lh + 18
        d.rounded_rectangle([self.M, y, self.W - self.M, y + bh], radius=12, fill=self.C["card"])
        d.rectangle([self.M, y + 10, self.M + 4, y + bh - 10], fill=self.A["a"])
        d.text((self.M + 24, y + 18), b.get("label", ""), font=f_l, fill=self.A["a"])
        ty = y + 46
        for ln in lines:
            d.text((self.M + 24, ty), ln, font=f_t, fill=self.C["txt"])
            ty += lh
        return y + bh

    def block(self, d, b, y):
        t = b.get("type")
        if t == "sec":
            return self._sec(d, b, y)
        if t == "callout":
            return self._callout(d, b, y) + GAP
        if t == "timeline":
            return self._timeline(d, b, y) + GAP
        if t == "vtimeline":
            return self._vtimeline(d, b, y) + GAP
        if t == "table":
            if b.get("title"):
                y = self._sec(d, b, y)
            return self._table(d, b, y) + GAP
        if t == "cards":
            if b.get("title"):
                y = self._sec(d, b, y)
            return self._cards(d, b, y) + GAP
        if t == "list":
            if b.get("title"):
                y = self._sec(d, b, y)
            return self._list(d, b, y) + GAP
        if t == "quote":
            return self._quote(d, b, y) + GAP
        return y

    # ---------- 分页 ----------
    def _prep(self, b):
        im, d = self.canvas(TMP_H)
        h = int(self.block(d, b, 12))
        h = max(30, min(h, TMP_H - 12))
        return {"b": b, "img": im.crop((0, 0, self.W, h)), "h": h}

    def _fit_items(self, b, room):
        items = b.get("items") or []
        best = 0
        for k in range(1, len(items) + 1):
            if self._prep(dict(b, items=items[:k]))["h"] <= room:
                best = k
            else:
                break
        return best

    def _fit_rows(self, b, room):
        rows = b.get("rows") or []
        best = 0
        for k in range(1, len(rows) + 1):
            sub = dict(b, rows=rows[:k])
            sub.pop("total", None)
            if self._prep(sub)["h"] <= room:
                best = k
            else:
                break
        return best

    def paginate(self):
        avail1 = self.H - FOOT_H - self.header_h - 20
        avail2 = self.H - FOOT_H - CONT_TOP - 10
        pages, cur, used, cap = [], [], 0, avail1
        memo = {}
        def prep(b):
            k = id(b)
            if k not in memo:
                memo[k] = self._prep(b)
            return memo[k]
        blocks = self.blocks_src
        i = 0
        while i < len(blocks):
            b = blocks[i]
            it = prep(b)
            # 小节标题不与正文分离：标题 + 紧随的实体块要一起装得下
            extra = 0
            if b.get("type") == "sec" and i + 1 < len(blocks):
                nb = blocks[i + 1]
                extra = prep(nb)["h"]
                # 下一块是表格且可拆：只要求表头 + 3 行跟标题同页
                if nb.get("type") == "table" and len(nb.get("rows") or []) > 3:
                    probe = dict(nb, rows=nb["rows"][:3])
                    probe.pop("total", None)
                    extra = self._prep(probe)["h"]
                elif nb.get("type") == "list" and len(nb.get("items") or []) > 2:
                    extra = self._prep(dict(nb, items=nb["items"][:2]))["h"]
            # 表格：剩余空间够就按行拆分，续页重复表头
            if cur and used + it["h"] > cap and b.get("type") == "table":
                room = cap - used
                if room > 300:
                    k = self._fit_rows(b, room)
                    if 0 < k < len(b.get("rows") or []):
                        head = dict(b, rows=b["rows"][:k], total_skip=True)
                        rest = dict(b, rows=b["rows"][k:], title=None, lead=None, cont=True)
                        head.pop("total", None) if b.get("total") else None
                        blocks[i:i + 1] = [head, rest]
                        continue
            # 卡片网格：按整行拆分，保持左右配对
            if cur and used + it["h"] > cap and b.get("type") == "cards":
                room = cap - used
                cols = max(1, int(b.get("cols", 3)))
                items = b.get("items") or []
                if room > 250 and len(items) > cols:
                    k = 0
                    for r in range(1, len(items) // cols + 1):
                        if self._prep(dict(b, items=items[:r * cols], title=None))["h"] <= room:
                            k = r * cols
                        else:
                            break
                    if 0 < k < len(items):
                        blocks[i:i + 1] = [dict(b, items=items[:k], title=None),
                                           dict(b, items=items[k:], title=None)]
                        continue
            # 长条目列表：剩余空间够就按条拆分
            if cur and used + it["h"] > cap and b.get("type") == "list":
                room = cap - used
                if room > 250:
                    k = self._fit_items(b, room)
                    if 0 < k < len(b.get("items") or []):
                        head = dict(b, items=b["items"][:k], title=None)
                        rest = dict(b, items=b["items"][k:], title=None)
                        blocks[i:i + 1] = [head, rest]
                        continue
            if cur and used + it["h"] + extra > cap:
                pages.append(cur)
                cur, used, cap = [], 0, avail2
                continue
            cur.append(it)
            used += it["h"]
            i += 1
        if cur:
            pages.append(cur)
        return pages

    def page_footer(self, im, d, idx, total, last=False):
        ft = self.spec.get("footer") or {}
        base = self.H - 30
        d.line([(self.M, base - 40), (self.W - self.M, base - 40)], fill=self.C["rule"], width=1)
        if last and ft.get("source"):
            self.text(d, (self.M, base - 32), ft["source"], self.font(13), self.C["sub"],
                      maxw=self.cw - 120, lh=1.5, max_lines=3)
        pg = f"{idx}/{total}"
        d.text((self.M, base), pg, font=self.font(13), fill=self.C["sub"])
        brand = ft.get("brand") or "中公教育"
        f_b = self.font(14)
        dw = self.deer(im, 36)  # 小鹿置于页脚右侧
        bx = self.W - self.M - f_b.getlength(brand) - (dw + 12 if dw else 0)
        d.text((bx, base), brand, font=f_b, fill=self.C["sub"])

    def draw_page(self, items, idx, total):
        im, d = self.canvas(self.H)
        if idx == 1 and self.header_img:
            im.paste(self.header_img, (0, 0))
            y = self.header_h + 20
        else:
            hd = self.spec.get("header") or {}
            d.rectangle([0, 0, self.W, 4], fill=self.A["a"])
            t = hd.get("short") or ""
            if t:
                d.text((self.M, 30), t, font=self.font(17, True), fill=self.C["sub"])
            y = CONT_TOP
        for it in items:
            if y + it["h"] > self.H - FOOT_H:
                break
            im.paste(it["img"], (0, int(y)))
            y += it["h"]
        self.page_footer(im, d, idx, total, idx == total)
        return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pdf")
    ap.add_argument("--no-deer", action="store_true", help="不在页脚放小鹿形象")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    doc = Doc(spec)
    if a.no_deer:
        doc.deer_on = False
    doc.build_header()
    pages = doc.paginate()
    os.makedirs(a.out, exist_ok=True)
    outs = []
    for i, p in enumerate(pages, 1):
        im = doc.draw_page(p, i, len(pages))
        path = os.path.join(a.out, f"{i:02d}.png")
        im.save(path)
        outs.append(path)
        print(f"page {i}: {len(p)} blocks -> {path}")
    if a.pdf:
        from PIL import Image as I
        ims = [I.open(p).convert("RGB") for p in outs]
        ims[0].save(a.pdf, save_all=True, append_images=ims[1:], resolution=150)
        print("pdf ->", a.pdf)
    print(json.dumps({"pages": len(outs), "header_h": doc.header_h}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
    main()
