# -*- coding: utf-8 -*-
"""relayout_light.py —— 轻度二创渲染器

设计原则：**复刻原素材的视觉骨架，只做四类轻改**
  1. 主色（同明度区间内换色系）
  2. 序号形态（圆 / 描边圆 / 方 / 竖条）
  3. 卡片底（淡色 / 浅灰 / 描边）
  4. 模块顺序（spec 里 blocks 顺序即最终顺序）

不改：字号层级关系、区块形态、信息密度、留白比例。
输出：固定 1080×1440 分页。
"""

import argparse
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1440
M = 64
GAP = 20
FOOT_H = 76
CONT_TOP = 104
TMP_H = 6000

INK = "#15181B"
SUB = "#636A73"
FILL = "#F4F5F7"
RULE = "#E4E6E9"
WHITE = "#FFFFFF"

# 主色：明度都在同一区间，保证「换色不换调」
TINTS = {
    "tea":     {"deep": "#1E4B3E", "mid": "#2C6B57", "soft": "#EDF2EF", "line": "#D6E2DB"},
    "pine":    {"deep": "#144A47", "mid": "#1F6C66", "soft": "#EBF3F2", "line": "#D2E3E0"},
    "inkblue": {"deep": "#1B3550", "mid": "#2B5279", "soft": "#EDF1F6", "line": "#D4DFE9"},
    "brick":   {"deep": "#7E2A23", "mid": "#A93A2E", "soft": "#F7EFEC", "line": "#E9D6D1"},
    "slate":   {"deep": "#292E34", "mid": "#474F59", "soft": "#F1F2F4", "line": "#DCE0E4"},
}

# 字体：中公宣传品唯一允许的可商用字体 = 方正兰亭黑系列（随包放 assets/fonts，见 fonts.json）。
# 包内优先，缺失回退 Windows 雅黑/黑体，保证换机器也能出图。
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FDIR = os.path.join(_HERE, "assets", "fonts")
FONT_B = [os.path.join(_FDIR, "FZLTCHJW.TTF"), r"C:/Windows/Fonts/msyhbd.ttc"]  # 兰亭粗黑 → 雅黑粗
FONT_R = [os.path.join(_FDIR, "FZLTHJW.TTF"),  r"C:/Windows/Fonts/msyh.ttc"]    # 兰亭黑   → 雅黑
FONT_H = [os.path.join(_FDIR, "FZLTTHJW.TTF"), r"C:/Windows/Fonts/simhei.ttf"]  # 兰亭准黑 → 黑体

PUNCT_TAIL = "，。、；：？！）》」』”’,.;:?!)]}%"
ASCII_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\.\-:/×%]*")


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
    def __init__(self, spec, palettes_path=None):
        self.spec = spec
        self.W = int((spec.get("size") or {}).get("width", W))
        self.H = int((spec.get("size") or {}).get("height", H))
        self.M = M if self.W >= 900 else 48
        self.cw = self.W - 2 * self.M
        self.skin = spec.get("skin", "report")
        self.tint = TINTS.get(spec.get("tint", "tea"), TINTS["tea"])
        self.num_style = spec.get("num", "circle")
        self.tile_style = spec.get("tile", "tint")
        self.ts = float(spec.get("type_scale") or 1.0)   # 字号总控：越小越密
        # 间距总控：默认跟字号联动，字号小了留白也一起收，密度才真的变高
        self.ss = float(spec.get("space_scale") or self.ts)
        self.gap = max(int(GAP * self.ss), 10)
        self.zebra = bool(spec.get("zebra", True))
        self.rule_on = bool(spec.get("rule", True))
        self.deer_on = bool(spec.get("deer", True))
        self._fc = {}
        self._logo_d = None
        self._logo_l = None
        self._deer_raw = None
        self.header_img = None
        self.header_h = 0
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assets = os.path.join(here, "assets")
        self.blocks_src = spec.get("blocks") or []
        # 顺序重排后自动续号，保证视觉编号连续
        if spec.get("renumber", True):
            n = 0
            for b in self.blocks_src:
                if b.get("type") != "quote" and b.get("title"):
                    n += 1
                    b["no"] = str(n)

    # ---------------- 基础 ----------------
    def font(self, size, bold=False):
        return self._ttf(max(12, int(round(size * self.ts))), bold)

    def _ttf(self, size, bold=False):
        size = max(12, int(round(size)))
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
        if f is None:
            f = ImageFont.load_default()
        self._fc[key] = f
        return f

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
                if font.getlength(tk) > maxw:  # 超长串硬切
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

    def text(self, d, xy, s, font, fill, maxw=None, lh=1.5, max_lines=None, align="l"):
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

    def logo(self, canvas, x, y, h=30, light=False):
        if self._logo_d is None:
            p = os.path.join(self.assets, "logo", "offcn_dark.png")
            try:
                im = Image.open(p).convert("RGBA")
                r = h / im.size[1]
                self._logo_d = im.resize((max(1, int(im.size[0] * r)), h), Image.LANCZOS)
            except Exception:
                self._logo_d = False
            p2 = os.path.join(self.assets, "logo", "offcn_light.png")
            try:
                im2 = Image.open(p2).convert("RGBA")
                r2 = h / im2.size[1]
                self._logo_l = im2.resize((max(1, int(im2.size[0] * r2)), h), Image.LANCZOS)
            except Exception:
                self._logo_l = False
        im = self._logo_l if light else self._logo_d
        if im:
            canvas.paste(im, (int(x), int(y)), im)
            return im.size[0]
        return 0

    def deer(self, canvas, h=44):
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
        im = self._deer_raw
        r = h / im.size[1]
        im2 = im.resize((max(1, int(im.size[0] * r)), h), Image.LANCZOS)
        x = self.W - self.M - im2.size[0]
        y = self.H - FOOT_H + (FOOT_H - im2.size[1]) // 2 + 2
        canvas.paste(im2, (int(x), int(y)), im2)
        return im2.size[0]

    def canvas(self, h):
        im = Image.new("RGB", (self.W, h), WHITE)
        return im, ImageDraw.Draw(im)

    # ---------------- 页头 ----------------
    def build_header(self):
        hd = self.spec.get("header") or {}
        if self.skin == "sheet":
            im = self._header_sheet(hd)
        else:
            im = self._header_report(hd)
        self.header_img = im
        self.header_h = im.size[1]

    def _header_report(self, hd):
        im, d = self.canvas(TMP_H // 2)
        k = self.ts
        y = max(int(46 * k), 30)
        self.logo(im, self.M, y, max(int(28 * k), 20))
        kick = hd.get("kicker")
        if kick:
            f = self.font(19)
            d.text((self.W - self.M - f.getlength(kick), y + 5), kick, font=f, fill=SUB)

        y += max(int(52 * k), 34)
        tsize = hd.get("title_size", 64)
        f_t = self.font(tsize, True)
        corner = hd.get("corner")
        right_w = 196 if corner else 0
        maxw = self.cw - right_w - 16
        ty = y
        for ln in (hd.get("title_lines") or []):
            d.text((self.M, ty), ln, font=f_t, fill=INK)
            ty += int(tsize * k * 1.16)

        cbh = max(int(132 * k), 88)
        if corner:
            bw, bh = max(int(176 * k), 118), cbh
            bx = self.W - self.M - bw
            by = y - 6
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=max(int(14 * k), 8),
                                fill=self.tint["deep"])
            fv = self.font(50, True)
            fl = self.font(20)
            d.text((bx + 20, by + int(22 * k)), str(corner.get("v", "")), font=fv, fill=WHITE)
            d.text((bx + 22, by + int(88 * k)), str(corner.get("l", "")), font=fl, fill="#D6DFDB")

        y = max(ty, y + (cbh if corner else 0)) + 4

        sub = hd.get("sub")
        if sub:
            y += int(10 * k)
            y = self.text(d, (self.M, y), sub, self.font(21), SUB, maxw=self.cw, lh=1.45) + 4

        if self.rule_on:
            d.line([(self.M, y + 6), (self.W - self.M, y + 6)], fill=RULE, width=2)
            y += int(16 * k)
        else:
            y += int(16 * k)

        metrics = hd.get("metrics") or []
        if metrics:
            n = len(metrics)
            gap = int(14 * k)
            bw = (self.cw - gap * (n - 1)) / n
            f_l = self.font(18)
            f_v = self.font(36, True)
            inner_w = bw - 34
            labs = [self.wrap(str(m.get("l", "")), f_l, inner_w) for m in metrics]
            nrow = max(len(x) for x in labs)
            bh = int((14 + nrow * 24 + 8 + 44) * k)
            for i, m in enumerate(metrics):
                bx = self.M + i * (bw + gap)
                fill_bg = None
                if self.tile_style == "line":
                    d.line([(bx, y), (bx + bw - 12, y)], fill=self.tint["deep"], width=3)
                    tx = bx
                else:
                    fill_bg = FILL if self.tile_style == "gray" else self.tint["soft"]
                    d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=10, fill=fill_bg)
                    tx = bx + 17
                ty = y + int(14 * k)
                for ln in labs[i]:
                    d.text((tx, ty), ln, font=f_l, fill=SUB)
                    ty += int(24 * k)
                nv = str(m.get("v", ""))
                while f_v.getlength(nv) > bw - 30 and f_v.size > 20:
                    f_v = self._ttf(f_v.size - 2, True)
                d.text((tx, y + bh - int(48 * k)), nv, font=f_v,
                       fill=INK if self.tile_style == "gray" else self.tint["deep"])
            y += bh + int(22 * k)
        return im.crop((0, 0, self.W, int(y)))

    def _header_sheet(self, hd):
        im, d = self.canvas(TMP_H // 2)
        kick = hd.get("kicker")
        sub = hd.get("sub")
        lines = hd.get("title_lines") or []
        tsize = hd.get("title_size", 56)
        corner = hd.get("corner")

        band = 40 + (30 if kick else 0) + len(lines) * int(tsize * 1.2) + 36
        d.rectangle([0, 0, self.W, band], fill=self.tint["deep"])
        y = 34
        lw = self.logo(im, self.M, y - 6, 26, light=True) or 90
        if kick:
            f_k = self.font(18)
            d.text((self.M + lw + 14, y + 5), kick, font=f_k, fill="#C9D8D2")
        y += 34
        f_t = self.font(tsize, True)
        bw_est = 0
        if corner:
            f_cv = self.font(30, True)
            f_cl = self.font(17)
            bw_est = max(150, max(f_cv.getlength(str(corner.get("v", ""))),
                                 f_cl.getlength(str(corner.get("l", "")))) + 34)
        tw = self.cw - (int(bw_est) + 20 if corner else 0)
        for ln in lines:
            d.text((self.M, y), ln, font=f_t, fill=WHITE)
            y += int(tsize * 1.2)

        if corner:
            bw, bh = bw_est, 84
            bx, by = self.W - self.M - bw, 30
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=10, fill="#FFFFFF")
            d.text((bx + 16, by + 14), str(corner.get("v", "")), font=self.font(30, True), fill=self.tint["deep"])
            d.text((bx + 16, by + 54), str(corner.get("l", "")), font=self.font(18), fill=SUB)

        y = band
        if sub:
            d.rectangle([0, y, self.W, y + 56], fill=self.tint["soft"])
            f_s = self.font(22)
            d.text((self.M, y + 15), sub, font=f_s, fill="#4A5B55")
            y += 56
        return im.crop((0, 0, self.W, int(y) + 16))

    # ---------------- 区块 ----------------
    def block(self, d, b, y):
        t = b.get("type", "section")
        if t == "bars":
            return self._bars(d, b, y)
        if t == "tiles":
            return self._tiles(d, b, y)
        if t == "table":
            return self._table(d, b, y)
        if t == "quote":
            return self._quote(d, b, y)
        if t == "steps":
            return self._steps(d, b, y)
        if t == "notice":
            return self._notice(d, b, y)
        return self._section(d, b, y)

    def _head(self, d, b, y, top=True):
        ss = self.ss
        no = str(b.get("no") or "")
        fs = self.font(32, True)
        ns = max(int(40 * ss), 26)
        x = self.M
        if no:
            st = self.num_style
            if st in ("circle", "ring"):
                if st == "circle":
                    d.ellipse([x, y + 1, x + ns, y + 1 + ns], fill=self.tint["mid"])
                    fill_c = WHITE
                else:
                    d.ellipse([x, y + 1, x + ns, y + 1 + ns], outline=self.tint["mid"], width=2)
                    fill_c = self.tint["mid"]
                f_n = self.font(22, True)
                d.text((x + (ns - f_n.getlength(no)) / 2, y + 1 + (ns - f_n.size) / 2 - 2),
                       no, font=f_n, fill=fill_c)
                x += ns + int(14 * ss)
            elif st == "square":
                d.rounded_rectangle([x, y + 2, x + ns - 2, y + ns], radius=max(int(8 * ss), 5),
                                    fill=self.tint["mid"])
                f_n = self.font(22, True)
                d.text((x + (ns - 2 - f_n.getlength(no)) / 2, y + 2 + (ns - 2 - f_n.size) / 2 - 2),
                       no, font=f_n, fill=WHITE)
                x += ns + int(10 * ss)
            else:  # bar
                d.rectangle([x - int(18 * ss), y + 2, x - int(12 * ss), y + ns], fill=self.tint["mid"])
                d.text((x, y + 2), no, font=self.font(30, True), fill=self.tint["mid"])
                x += fs.getlength(no) + int(14 * ss)

        title = b.get("title") or ""
        chip = b.get("chip")
        chip_w = 0
        if chip:
            f_c = self.font(20, True)
            ch_h = max(int(36 * ss), 26)
            chip_w = f_c.getlength(chip) + int(30 * ss)
            d.rounded_rectangle([self.W - self.M - chip_w, y + 4, self.W - self.M, y + 4 + ch_h],
                                radius=ch_h / 2,
                                fill=self.tint["soft"] if self.tile_style != "gray" else FILL)
            d.text((self.W - self.M - chip_w + int(15 * ss), y + 4 + (ch_h - f_c.size) / 2 - 2),
                   chip, font=f_c, fill=self.tint["deep"])
        y2 = self.text(d, (x, y), title, fs, INK,
                       maxw=self.cw - (x - self.M) - chip_w - 20, lh=1.40)
        y = y2 + int(4 * ss)

        lead = b.get("lead")
        if lead:
            y = self.text(d, (self.M, y + int(5 * ss)), lead, self.font(22), SUB,
                          maxw=self.cw, lh=1.45) + int(2 * ss)
        return y + int(14 * ss)

    def _bars(self, d, b, y):
        ss = self.ss
        y = self._head(d, b, y)
        bars = b.get("items") or []
        mx = max([float(x.get("pct", 0)) for x in bars] + [1])
        f_v = self.font(23, True)
        lw = 0
        for bar in bars:
            lw = max(lw, self.font(22, True).getlength(str(bar.get("label", ""))))
        lw = int(min(max(96, lw + 20), 196))
        f_l = self.font(22, True)
        for bar in bars:
            if f_l.getlength(str(bar.get("label", ""))) > lw - 12 and f_l.size > 18:
                f_l = self._ttf(lw - 12 if lw < 160 else 20, True)
        rh = max(int(42 * ss), 24)
        g0 = int(12 * ss)
        gh = max(int(18 * ss), 10)
        for bar in bars:
            lab = str(bar.get("label", ""))
            val = str(bar.get("value", ""))
            while f_l.getlength(lab) > lw - 12 and f_l.size > 17:
                f_l = self._ttf(f_l.size - 1, True)
            d.text((self.M, y + int(8 * ss)), lab, font=f_l, fill=INK)
            tx0 = self.M + lw
            vw = f_v.getlength(val)
            tx1 = self.W - self.M - vw - 20
            d.rounded_rectangle([tx0, y + g0, tx1, y + g0 + gh], radius=gh / 2, fill="#EDEFF1")
            w = max(6, int((tx1 - tx0) * float(bar.get("pct", 0)) / mx))
            d.rounded_rectangle([tx0, y + g0, tx0 + w, y + g0 + gh], radius=gh / 2, fill=self.tint["mid"])
            d.text((tx1 + 12, y + int(8 * ss)), val, font=f_v, fill=self.tint["deep"])
            y += rh
        return y

    def _tiles(self, d, b, y):
        ss = self.ss
        y = self._head(d, b, y)
        items = b.get("items") or []
        cols = int(b.get("cols", 2))
        gap = max(int(14 * ss), 8)
        cw = (self.cw - gap * (cols - 1)) / cols
        pad = max(int(18 * ss), 11)
        f_h = self.font(23, True)
        f_s = self.font(19)
        base_h = int(b.get("row_h", 84) * ss)
        vpad = max(int(14 * ss), 9)
        # 统一卡高：按最长的一条 sub 计算
        prep = []
        for it in items:
            mv = it.get("m")
            mw = f_h.getlength(str(mv)) + 14 if mv else 0
            inner = cw - pad * 2 - mw
            hv = str(it.get("h", ""))
            hlines = self.wrap(hv, f_h, inner)[:2] if hv else []
            # lines：h 下方的明细行；head=True 时第 1 行作加粗小标题，其余灰色（不限行数）
            det = []
            for j, s in enumerate(it.get("lines") or []):
                lead_b = bool(it.get("head")) and j == 0 and bool(hv)
                f = self.font(21, True) if lead_b else f_s
                for ln in self.wrap(str(s), f, cw - pad * 2):
                    det.append((ln, f, int((29 if lead_b else 24) * ss)))
            sub = it.get("sub")
            slines = self.wrap(str(sub), f_s, cw - pad * 2)[:2] if sub else []
            need = (vpad + len(hlines) * int(30 * ss) + sum(x[2] for x in det)
                    + (len(slines) * int(24 * ss) + 2 if slines else 0) + vpad)
            prep.append((it, hlines, det, slines))
        row_h = max(base_h, max((vpad + len(p[1]) * int(30 * ss) + sum(x[2] for x in p[2])
                                 + (len(p[3]) * int(24 * ss) + 2 if p[3] else 0) + vpad) for p in prep))
        for i, (it, hlines, det, slines) in enumerate(prep):
            r, c = divmod(i, cols)
            x = self.M + c * (cw + gap)
            yy = y + r * (row_h + gap)
            if self.tile_style == "line":
                d.rectangle([x, yy, x + cw, yy + row_h], outline=self.tint["line"], width=2)
            elif self.tile_style == "gray":
                d.rounded_rectangle([x, yy, x + cw, yy + row_h], radius=10, fill=FILL)
            else:
                d.rounded_rectangle([x, yy, x + cw, yy + row_h], radius=10, fill=self.tint["soft"])
            d.rectangle([x, yy + vpad, x + 4, yy + row_h - vpad], fill=self.tint["mid"])
            mv = it.get("m")
            ty = yy + vpad + 1
            for ln in hlines:
                d.text((x + pad, ty), ln, font=f_h, fill=INK)
                ty += int(30 * ss)
            for ln, f, step in det:
                d.text((x + pad, ty + 2), ln, font=f, fill=SUB if f.size < 21 else INK)
                ty += step
            for ln in slines:
                d.text((x + pad, ty + 2), ln, font=f_s, fill=SUB)
                ty += int(24 * ss)
            if mv:
                d.text((x + cw - pad - f_h.getlength(str(mv)), yy + vpad + 1), str(mv), font=f_h,
                       fill=self.tint["deep"])
        rows = (len(items) + cols - 1) // cols
        y = y + rows * (row_h + gap) - gap
        note = b.get("note")
        if note:
            d.ellipse([self.M + 2, y + int(20 * ss), self.M + int(10 * ss), y + int(28 * ss)],
                      fill=self.tint["mid"])
            y = self.text(d, (self.M + int(22 * ss), y + int(12 * ss)), note, self.font(21), SUB,
                          maxw=self.cw - 22, lh=1.50)
        return y

    def _table(self, d, b, y):
        ss = self.ss
        if b.get("title"):
            y = self._head(d, b, y)
        cols = b.get("cols") or []
        rows = b.get("rows") or []
        groups = b.get("groups") or []
        n = max(1, len(cols))
        gcol = max(int(b.get("gcol", 104) * ss), 46) if groups else 0
        tw = self.cw - gcol
        ratios = b.get("widths") or [1.0] * n
        ssum = sum(ratios) or 1
        widths = [tw * r / ssum for r in ratios]
        xs = [self.M + gcol + sum(widths[:i]) for i in range(n)]
        f_td = self.font(21)
        lh = int(21 * self.ts * 1.45)
        padx, pady = int(13 * ss), max(int(13 * ss), 7)
        min_h = int(b.get("row_h", 40) * ss)
        hdr_h = max(int(40 * ss), 24)

        num_cols = set()
        if rows:
            for i in range(1, n):
                probe = str(rows[0][i]) if i < len(rows[0]) else ""
                if probe.replace(".", "").replace("%", "").isdigit():
                    num_cols.add(i)

        # 表头
        d.line([(self.M + gcol, y), (self.W - self.M, y)], fill=INK, width=2)
        for i, c in enumerate(cols):
            f = self.font(19, True)
            ty = y + (hdr_h - f.size) / 2 - 2
            if i in num_cols:
                d.text((xs[i] + widths[i] - padx - f.getlength(str(c)), ty), str(c), font=f, fill=SUB)
            else:
                d.text((xs[i] + padx, ty), str(c), font=f, fill=SUB)
        y += hdr_h

        # 先量每行高度
        cells, hs = [], []
        for row in rows:
            row_cells, hrow = [], min_h
            for i in range(n):
                val = str(row[i]) if i < len(row) else ""
                lines = self.wrap(val, f_td, widths[i] - 2 * padx)
                hrow = max(hrow, len(lines) * lh + 2 * pady)
                row_cells.append(lines)
            cells.append(row_cells)
            hs.append(hrow)

        # 画行
        yy = y
        for r, row_cells in enumerate(cells):
            hrow = hs[r]
            if self.zebra and r % 2 == 1:
                d.rectangle([self.M + gcol, yy, self.W - self.M, yy + hrow], fill="#F7F8F9")
            for i, lines in enumerate(row_cells):
                ty = yy + pady
                for ln in lines:
                    if i in num_cols:
                        f = self.font(21, True)
                        d.text((xs[i] + widths[i] - padx - f.getlength(ln), ty), ln, font=f,
                               fill=self.tint["deep"])
                    else:
                        d.text((xs[i] + padx, ty), ln, font=f_td, fill=INK if i == 0 else SUB)
                    ty += lh
            d.line([(self.M + gcol, yy + hrow), (self.W - self.M, yy + hrow)], fill=RULE, width=1)
            yy += hrow

        # 左侧合并分组栏（竖排文字）
        if groups:
            i = 0
            while i < len(rows):
                g = str(groups[i]) if i < len(groups) else ""
                j = i
                while j + 1 < len(rows) and j + 1 < len(groups) and str(groups[j + 1]) == g:
                    j += 1
                top = y + sum(hs[:i])
                bot = y + sum(hs[:i + j + 1])
                d.rectangle([self.M, top, self.M + gcol - int(14 * ss), bot], fill=self.tint["soft"])
                d.rectangle([self.M, top, self.M + 3, bot], fill=self.tint["mid"])
                box_h = bot - top
                step = min(int(24 * ss), max(int((box_h - 10) / max(1, len(g))), 12))
                fsize = max(12, min(19, int(step * 0.86)))
                f_g = self.font(fsize, True)
                ty = top + max(4, int((box_h - len(g) * step) / 2))
                for ch in g:
                    d.text((self.M + (gcol - int(14 * ss) - f_g.getlength(ch)) / 2, ty), ch, font=f_g,
                           fill=self.tint["deep"])
                    ty += step
                i = j + 1
        return yy + int(6 * ss)

    def _quote(self, d, b, y):
        ss = self.ss
        lab = b.get("label") or "一句话结论"
        txt = b.get("text") or ""
        dark = bool(b.get("dark", True))
        f_l = self.font(19, True)
        f_t = self.font(25, True)
        pad = int(34 * ss)
        inner = self.cw - pad * 2
        lines = self.wrap(txt, f_t, inner)
        lh = int(25 * self.ts * 1.48)
        top = int(20 * ss)
        box_h = top + int(24 * ss) + len(lines) * lh + int(18 * ss)
        fill_c = self.tint["deep"] if dark else self.tint["soft"]
        d.rounded_rectangle([self.M, y, self.W - self.M, y + box_h], radius=14, fill=fill_c)
        d.text((self.M + pad, y + top), lab, font=f_l, fill="#B9CCC4" if dark else self.tint["deep"])
        yy = y + top + int(24 * ss)
        for ln in lines:
            d.text((self.M + pad, yy), ln, font=f_t, fill=WHITE if dark else INK)
            yy += lh
        return y + box_h

    def _steps(self, d, b, y):
        ss = self.ss
        items = b.get("items") or []
        n = max(1, len(items))
        gap = max(int(10 * ss), 6)
        cw = (self.cw - gap * (n - 1)) / n
        hh = max(int(104 * ss), 66)
        pad = max(int(16 * ss), 10)
        for i, it in enumerate(items):
            x = self.M + i * (cw + gap)
            d.rounded_rectangle([x, y, x + cw, y + hh], radius=10, fill=self.tint["soft"])
            d.text((x + pad, y + int(12 * ss)), str(it.get("no", i + 1)),
                   font=self.font(24, True), fill=self.tint["deep"])
            d.text((x + pad, y + int(48 * ss)), str(it.get("h", "")),
                   font=self.font(21, True), fill=INK)
            sub = it.get("sub")
            if sub:
                d.text((x + pad, y + int(74 * ss)), str(sub), font=self.font(17), fill=SUB)
        return y + hh

    def _notice(self, d, b, y):
        ss = self.ss
        txt = b.get("text") or ""
        f = self.font(22)
        pad = max(int(28 * ss), 16)
        lines = self.wrap(txt, f, self.cw - pad * 2)
        lh = int(22 * self.ts * 1.50)
        bh = len(lines) * lh + int(26 * ss)
        d.rounded_rectangle([self.M, y, self.W - self.M, y + bh], radius=10, fill=self.tint["soft"])
        yy = y + int(13 * ss)
        for ln in lines:
            d.text((self.M + pad, yy), ln, font=f, fill="#3D5148")
            yy += lh
        return y + bh

    def _section(self, d, b, y):
        ss = self.ss
        y = self._head(d, b, y)
        for it in (b.get("items") or []):
            r0 = int(11 * ss)
            d.ellipse([self.M + 4, y + r0, self.M + 4 + int(9 * ss), y + r0 + int(9 * ss)],
                      fill=self.tint["mid"])
            y = self.text(d, (self.M + int(26 * ss), y), it, self.font(23), INK,
                          maxw=self.cw - int(26 * ss), lh=1.50, max_lines=2) + int(8 * ss)
        return y

    def _prep(self, b, scale=1.0):
        im, d = self.canvas(TMP_H)
        h = int(self.block(d, b, 10))
        h = max(40, min(h, TMP_H - 10))
        return {"b": b, "img": im.crop((0, 0, self.W, h)), "h": h}

    def _row_h(self, b, row):
        n = max(1, len(b.get("cols") or []))
        gcol = int(b.get("gcol", 104)) if b.get("groups") else 0
        tw = self.cw - gcol
        ratios = b.get("widths") or [1.0] * n
        ssum = sum(ratios) or 1
        widths = [tw * r / ssum for r in ratios]
        f = self.font(21)
        lh = int(21 * self.ts * 1.55)
        h = int(b.get("row_h", 40))
        for i in range(n):
            val = str(row[i]) if i < len(row) else ""
            lines = self.wrap(val, f, widths[i] - 26)
            h = max(h, len(lines) * lh + int(26 * self.ts))
        return h

    def _split(self, b, cap):
        h = self._prep(b)["h"]
        if h <= cap:
            return [b]
        t = b.get("type")
        if t in ("bars", "tiles", "section") and (b.get("items") or []):
            items = b["items"]
            size = 3 if t == "section" else (2 if t == "tiles" else 2)
            out, i, first = [], 0, True
            while i < len(items):
                chunk = dict(b)
                chunk["items"] = items[i:i + size]
                if not first:
                    chunk["no"] = ""
                    chunk["title"] = (b.get("title") or "接上页") + "（续）"
                    chunk["chip"] = None
                    chunk["lead"] = None
                else:
                    chunk["chip"] = b.get("chip")
                out.append(chunk)
                i += size
                first = False
            return out
        if t == "table" and (b.get("rows") or []):
            rows = b["rows"]
            gs = b.get("groups") or []
            out, i, first = [], 0, True
            while i < len(rows):
                chunk_rows, chunk_gs, ch = [], [], 92
                while i < len(rows):
                    rh = self._row_h(b, rows[i])
                    if ch + rh > cap and chunk_rows:
                        break
                    chunk_rows.append(rows[i])
                    chunk_gs.append(gs[i] if i < len(gs) else "")
                    ch += rh
                    i += 1
                if not chunk_rows:
                    chunk_rows.append(rows[i])
                    chunk_gs.append(gs[i] if i < len(gs) else "")
                    i += 1
                chunk = dict(b)
                chunk["rows"] = chunk_rows
                if gs:
                    chunk["groups"] = chunk_gs
                if not first:
                    chunk["no"] = ""
                    chunk["title"] = (b.get("title") or "接上页") + "（续）"
                    chunk["lead"] = None
                out.append(chunk)
                first = False
            return out
        return [b]

    def paginate(self):
        avail1 = self.H - FOOT_H - self.header_h - max(int(22 * self.ss), 12)
        avail2 = self.H - FOOT_H - int(CONT_TOP * self.ss) - max(int(10 * self.ss), 6)
        pages, cur, used, cap = [], [], 0, avail1
        queue = list(self.blocks_src)
        guard = 0
        while queue and guard < 400:
            guard += 1
            b = queue.pop(0)
            it = self._prep(b)
            # 表格类可以拆开填满当前页
            if cur and used + it["h"] + self.gap > cap and b.get("type") == "table":
                room = cap - used - self.gap
                if room > 260:
                    pieces = self._split(b, room)
                    # 只有切出来的第一段真的塞得进这点空位，才值得切；
                    # 否则会切出一段放不下、下一段又带「（续）」的残表。
                    if len(pieces) > 1 and self._prep(pieces[0])["h"] <= room:
                        queue = pieces + queue
                        continue
            # 当前页放不下 → 换页后重试同一块（不拆）
            if cur and used + it["h"] + self.gap > cap:
                pages.append(cur)
                cur, used, cap = [], 0, avail2
                queue.insert(0, b)
                continue
            # 整页都装不下才拆
            if not cur and it["h"] > cap:
                pieces = self._split(b, cap)
                if len(pieces) > 1:
                    queue = pieces + queue
                    continue
            cur.append(it)
            used += it["h"] + (self.gap if len(cur) > 1 else 0)
        if cur:
            pages.append(cur)
        return pages

    # ---------------- 出图 ----------------
    def page_footer(self, im, d, idx, total, last=False):
        ft = self.spec.get("footer") or {}
        base = self.H - max(int(34 * self.ss), 24)
        d.line([(self.M, base - int(40 * self.ss)), (self.W - self.M, base - int(40 * self.ss))],
               fill=RULE, width=1)
        if last and ft.get("source"):
            self.text(d, (self.M, base - 38), ft["source"], self.font(15), "#636A73",
                      maxw=self.cw, lh=1.5, max_lines=2)
        pg = f"{idx:02d}/{total:02d}"
        d.text((self.M, base), pg, font=self.font(15), fill="#6A717A")
        brand = ft.get("brand") or "中公教育"
        f_b = self.font(16)
        dw = self.deer(im, max(int(40 * self.ss), 28))  # 小鹿置于页脚右侧
        bx = self.W - self.M - f_b.getlength(brand) - (dw + 12 if dw else 0)
        d.text((bx, base + 1), brand, font=f_b, fill="#6A717A")

    def draw_page(self, items, idx, total):
        im, d = self.canvas(self.H)
        if idx == 1 and self.header_img:
            im.paste(self.header_img, (0, 0))
            y = self.header_h + max(int(22 * self.ss), 12)
        else:
            hd = self.spec.get("header") or {}
            t = hd.get("short") or "".join(hd.get("title_lines") or [])[:16]
            d.rectangle([0, 0, self.W, 6], fill=self.tint["deep"])
            d.text((self.M, 36), t, font=self.font(21, True), fill=SUB)
            y = int(CONT_TOP * self.ss)
        for it in items:
            if y + it["h"] > self.H - FOOT_H:
                break
            im.paste(it["img"], (0, int(y)))
            y += it["h"] + self.gap
        self.page_footer(im, d, idx, total, idx == total)
        return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True, help="输出目录；给 .png 则输出单张长图")
    ap.add_argument("--pdf")
    ap.add_argument("--only", type=int, default=0)
    ap.add_argument("--no-deer", action="store_true", help="不在页脚放小鹿形象")
    a = ap.parse_args()

    spec = json.load(open(a.spec, encoding="utf-8"))
    doc = Doc(spec)
    if a.no_deer:
        doc.deer_on = False
    doc.build_header()
    pages = doc.paginate()
    if a.only:
        pages = pages[a.only - 1:a.only]

    os.makedirs(a.out if not a.out.lower().endswith(".png") else os.path.dirname(a.out) or ".", exist_ok=True)
    outs = []
    total = len(pages)
    for i, p in enumerate(pages, 1):
        im = doc.draw_page(p, i if not a.only else a.only, total if not a.only else total)
        if a.out.lower().endswith(".png"):
            path = a.out
        else:
            path = os.path.join(a.out, f"{i:02d}.png")
        im.save(path)
        outs.append(path)
        print(f"page {i}: {len(p)} blocks -> {path}")

    if a.pdf:
        ims = [Image.open(p).convert("RGB") for p in outs]
        ims[0].save(a.pdf, save_all=True, append_images=ims[1:], resolution=150)
        print("pdf ->", a.pdf)

    print(json.dumps({"pages": total, "files": len(outs)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
