# -*- coding: utf-8 -*-
"""排版二创渲染器（小红书 1080×1440 固定尺寸 · 自动分页）

原则：**结构与文案不动，只换版式、配色、字体层级**。
输入一份 spec.json（照着原素材的段落顺序写），输出标准小红书图文：每张 1080×1440，
内容按区块自动分页，不会被裁切，也不会把一段话拆断。

用法：
    python relayout.py --spec spec.json --out 图片          # 输出 图片/01.png, 02.png ...
    python relayout.py --spec spec.json --out 图片/排版版.png --pdf 排版版.pdf
    python relayout.py --spec spec.json --out 长图.png --long   # 回退：单张长图（老用法）

spec.json 见 references/layout-recreation.md
"""
import argparse
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_BOLD = ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf"]
FONT_REG = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]

M = 64                 # 左右安全边距
TMP_H = 9000           # 单块测量画布高度（足够高，避免长块被截）
TOP = 56               # 续页内容起始
FOOT_H = 132           # 页脚预留高度
GAP = 30               # 块间距
BLK_TOP = 8            # 块内起始留白（防标题顶部被裁）
MINI_H = 96            # 续页页眉高度


def rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def load_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


class Doc:
    def __init__(self, spec, palettes_path):
        self.spec = spec
        sz = spec.get("size") or {}
        self.W = int(sz.get("width", 1080))
        self.H = int(round(self.W * 4 / 3))      # 固定 3:4
        self.target_h = sz.get("height")         # 仅 --long 模式使用
        self.style = spec.get("style", "band")
        palettes = {p["id"]: p for p in load_json(palettes_path)["palettes"]}
        pid = spec.get("palette", "forest")
        self.p = palettes.get(pid) or list(palettes.values())[0]
        self.mode = self.p.get("mode", "light")
        self.bg = rgb(self.p["bg"])
        self.surface = rgb(self.p["surface"])
        self.ink = rgb(self.p["ink"])
        self.sub = rgb(self.p["sub"])
        self.accent = rgb(self.p["accent"])
        self.accent2 = rgb(self.p["accent2"])
        self.line = rgb(self.p["line"])
        self.white = (255, 255, 255) if self.mode == "light" else self.bg
        self.logo_path = os.path.join(BASE, "assets", "logo",
                                     "offcn_light.png" if self.mode == "dark" else "offcn_dark.png")
        self._fc = {}
        self._logo = None
        self._header_img = None
        self._header_h = 0
        self.gap = GAP
        self.scale = 1.0
        self.cw = self.W - 2 * M

    # ---------- 基础 ----------
    def font(self, size, bold=False):
        size = max(12, int(size * self.scale))
        k = (size, bold)
        if k in self._fc:
            return self._fc[k]
        f = None
        for p in (FONT_BOLD if bold else FONT_REG):
            if os.path.exists(p):
                try:
                    f = ImageFont.truetype(p, size)
                    break
                except Exception:
                    continue
        self._fc[k] = f or ImageFont.load_default()
        return self._fc[k]

    def wrap(self, text, font, maxw):
        lines, cur = [], ""
        # 英文/数字/日期串整体不拆，避免 "2027" 被断成 "202" + "7"
        for tok in re.findall(r"[A-Za-z0-9]+(?:[.:%/\-—][A-Za-z0-9]+)*[%]?|[\s\S]", str(text)):
            if tok == "\n":
                lines.append(cur)
                cur = ""
                continue
            if font.getlength(cur + tok) <= maxw:
                cur += tok
            elif tok in "，。、；：？！）》」』”’,.;:?!)]}%":
                cur += tok  # 标点不另起一行
            elif font.getlength(tok) > maxw:   # 超长串逐字兜底
                for ch in tok:
                    if font.getlength(cur + ch) <= maxw:
                        cur += ch
                    else:
                        lines.append(cur)
                        cur = ch
            else:
                lines.append(cur)
                cur = tok
        if cur:
            lines.append(cur)
        return lines or [""]

    def text(self, d, xy, s, font, fill, maxw=None, lh=1.5):
        x, y = xy
        step = int(font.size * lh)
        for ln in self.wrap(s, font, maxw or self.cw):
            d.text((x, y), ln, font=font, fill=fill)
            y += step
        return y

    def logo(self, d, y):
        if not os.path.exists(self.logo_path):
            d.text((M, y), "offcn", font=self.font(24, True), fill=self.accent)
            return
        if self._logo is None:
            im = Image.open(self.logo_path).convert("RGBA")
            h = 46
            r = h / im.height
            self._logo = im.resize((int(im.width * r), h), Image.LANCZOS)
        d._image.paste(self._logo, (M, y), self._logo)

    # ---------- 页头 ----------
    def header(self, d):
        hd = self.spec.get("header") or {}
        f_t = self.font(hd.get("title_size", 58), True)
        title_lines = hd.get("title_lines") or []
        kicker = hd.get("kicker")
        f_k = self.font(23, True)
        band = 44 + (38 if kicker else 0) + len(title_lines) * int(f_t.size * 1.24)
        band += (44 if hd.get("sub") else 0) + 34
        if self.style == "band":
            d.rectangle([0, 0, self.W, band], fill=self.accent)
            ink = self.white
        elif self.style == "card":
            d.rounded_rectangle([M, 36, self.W - M, band + 16], radius=22, fill=self.accent)
            ink = self.white
        else:
            ink = self.ink

        x, y = M, 40
        if kicker:
            d.text((x, y), kicker, font=f_k, fill=self.accent2 if self.style == "minimal" else ink)
            y += 38
        for ln in title_lines:
            d.text((x, y), ln, font=f_t, fill=ink)
            y += int(f_t.size * 1.24)
        sub = hd.get("sub")
        if sub:
            y += 6
            d.text((x, y), sub, font=self.font(26),
                   fill=ink if self.style != "minimal" else self.sub)
        y = band + 20

        metrics = hd.get("metrics") or []
        if metrics:
            n = len(metrics)
            gap = 14
            bw = (self.cw - gap * (n - 1)) / n
            bh = 96
            for i, m in enumerate(metrics):
                bx = M + i * (bw + gap)
                if self.style == "minimal":
                    d.line([(bx, y), (bx, y + bh - 26)], fill=self.accent, width=4)
                    tx = bx + 16
                else:
                    d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=14, fill=self.surface)
                    tx = bx + 18
                d.text((tx, y + 14), str(m.get("v", "")), font=self.font(40, True), fill=self.accent)
                d.text((tx, y + 66), str(m.get("l", "")), font=self.font(22), fill=self.sub)
            y += bh + 6
        return y

    def mini_header(self, d, idx, total):
        hd = self.spec.get("header") or {}
        title = hd.get("short_title") or " ".join(hd.get("title_lines") or [])
        f = self.font(26, True)
        d.text((M, 32), title, font=f, fill=self.ink)
        no = f"{idx:02d}"
        f_no = self.font(30, True)
        d.text((self.W - M - f_no.getlength(no), 30), no, font=f_no, fill=self.accent2)
        d.line([(M, 78), (self.W - M, 78)], fill=self.line, width=1)
        return MINI_H

    # ---------- 各区块 ----------
    def block(self, d, b, y):
        t = b.get("type", "section")
        if t == "section":
            return self.sec(d, b, y)
        if t == "table":
            return self.table(d, b, y)
        if t == "quote":
            return self.quote(d, b, y)
        return self.note(d, b, y)

    def _head(self, d, b, y):
        no = b.get("no")
        f_t = self.font(b.get("title_size", 40), True)
        x = M
        if no:
            d.text((x, y - 2), str(no), font=self.font(38, True), fill=self.accent2)
            x += d.textlength(str(no), font=self.font(38, True)) + 16
        d.text((x, y), b.get("title", ""), font=f_t, fill=self.ink)
        y += int(f_t.size * 1.3) + 8
        if self.style != "card":
            d.rectangle([M, y, M + 84, y + 5], fill=self.accent)
        y += 22
        lead = b.get("lead")
        if lead:
            y = self.text(d, (M, y), lead, self.font(25), self.sub, lh=1.48) + 4
        return y

    def sec(self, d, b, y):
        y = self._head(d, b, y)
        for it in b.get("items") or []:
            d.rectangle([M + 3, y + 13, M + 13, y + 23], fill=self.accent)
            y = self.text(d, (M + 26, y), it, self.font(26), self.ink, maxw=self.cw - 26, lh=1.48) + 9
        bars = b.get("bars") or []
        if bars:
            f_lb = self.font(24, True)
            f_v = self.font(26, True)
            lab_w = max(f_lb.getlength(str(x.get("label", ""))) for x in bars)
            val_w = max(f_v.getlength(str(x.get("value", ""))) for x in bars)
            tx0 = M + int(lab_w) + 24
            tx1 = self.W - M - int(val_w) - 16
            mx = max([float(x.get("pct", 0)) for x in bars] + [1])
            for bar in bars:
                d.text((M + 4, y + 6), str(bar.get("label", "")), font=f_lb, fill=self.ink)
                d.rounded_rectangle([tx0, y + 12, tx1, y + 30], radius=9, fill=self.line)
                w = max(8, int((tx1 - tx0) * float(bar.get("pct", 0)) / mx))
                d.rounded_rectangle([tx0, y + 12, tx0 + w, y + 30], radius=9, fill=self.accent)
                d.text((tx1 + 14, y + 2), str(bar.get("value", "")), font=f_v, fill=self.accent)
                y += int(44 * self.scale)
        y = self._tail(d, b, y)
        return y

    def table(self, d, b, y):
        y = self._head(d, b, y)
        cols = b.get("columns") or []
        rows = b.get("rows") or []
        n = max(1, len(cols))
        cw = self.cw / n
        rh = int(b.get("row_h", 44))
        f_th, f_td, f_num = self.font(23, True), self.font(25), self.font(27, True)
        num_cols = set()
        if rows:
            for i in range(1, n):
                probe = str(rows[0][i]) if i < len(rows[0]) else ""
                if probe.replace(".", "").replace("%", "").isdigit():
                    num_cols.add(i)
        d.line([(M, y), (self.W - M, y)], fill=self.ink, width=2)
        y += 12
        for i, c in enumerate(cols):
            if i in num_cols:
                d.text((M + i * cw + cw - 20 - f_th.getlength(str(c)), y), str(c), font=f_th, fill=self.sub)
            else:
                d.text((M + i * cw + 8, y), str(c), font=f_th, fill=self.sub)
        y += 34
        for r, row in enumerate(rows):
            if r % 2 == 0:
                d.rectangle([M, y - 4, self.W - M, y + rh - 10], fill=self.surface)
            for i, cell in enumerate(row[:n]):
                x = M + i * cw + 8
                val = str(cell)
                if i == 0:
                    d.text((x, y + 6), val, font=f_td, fill=self.ink)
                elif val.replace(".", "").replace("%", "").isdigit():
                    d.text((x + cw - 20 - f_num.getlength(val), y + 4), val, font=f_num, fill=self.accent)
                else:
                    d.text((x, y + 6), val, font=f_td, fill=self.ink)
            y += rh
            d.line([(M, y - 6), (self.W - M, y - 6)], fill=self.line, width=1)
        y += 12
        y = self._tail(d, b, y)
        return y

    def _tail(self, d, b, y):
        call = b.get("callout")
        if call:
            f = self.font(26, True)
            lines = self.wrap(call, f, self.cw - 56)
            hh = len(lines) * int(f.size * 1.5) + 30
            d.rounded_rectangle([M, y + 10, self.W - M, y + 10 + hh], radius=12, fill=self.surface)
            d.rectangle([M, y + 10, M + 7, y + 10 + hh], fill=self.accent)
            yy = y + 27
            for ln in lines:
                d.text((M + 30, yy), ln, font=f, fill=self.ink)
                yy += int(f.size * 1.5)
            y += hh + 18
        nt = b.get("note")
        if nt:
            self.text(d, (M, y + 4), nt, self.font(21), self.sub, lh=1.5)
            y += 34
        return y

    def quote(self, d, b, y):
        lab = b.get("label") or "结论"
        d.text((M, y), lab, font=self.font(22, True), fill=self.accent2)
        d.rectangle([M, y + 36, M + 64, y + 41], fill=self.accent2)
        y += 60
        f = self.font(b.get("size", 36), True)
        y = self.text(d, (M, y), b.get("text", ""), f, self.ink, lh=1.6) + 18
        src = b.get("from")
        if src:
            d.rectangle([M, y + 8, M + 56, y + 12], fill=self.accent)
            d.text((M, y + 24), src, font=self.font(24), fill=self.sub)
            y += 62
        return y

    def note(self, d, b, y):
        return self.text(d, (M, y), b.get("text", ""), self.font(24), self.sub, lh=1.6) + 16

    # ---------- 分页 ----------
    def _canvas(self, h=TMP_H):
        im = Image.new("RGB", (self.W, h), self.bg)
        d = ImageDraw.Draw(im)
        d._image = im
        return im, d

    def page_avail(self, first):
        """单页可放内容的高度"""
        if first:
            return self.H - self._header_h - GAP - FOOT_H
        return self.H - MINI_H - GAP - FOOT_H

    def _prep(self, b):
        im, d = self._canvas()
        h = int(self.block(d, b, BLK_TOP))
        h = max(40, min(h, TMP_H - 20))
        return {"b": b, "img": im.crop((0, 0, self.W, h)), "h": h}

    def _prep_scaled(self, b, k):
        """按 k 倍字号重绘一块，用于单块页填充版面"""
        old = self.scale
        self.scale = k
        it = self._prep(b)
        self.scale = old
        return it

    def fill_solo(self, it, avail):
        """单块页：在剩余空间内逐级放大，避免大片留白"""
        if it["b"].get("type") in ("quote", "table"):
            return it
        best = it
        for k in (1.08, 1.16, 1.24):
            cand = self._prep_scaled(it["b"], k)
            if cand["h"] <= avail:
                best = cand
            else:
                break
        return best

    def _split(self, b):
        """块太高时按条目 / 表格行拆开，返回子块列表；不能拆则 None"""
        t = b.get("type", "section")
        key = "items" if t == "section" else ("rows" if t == "table" else None)
        if not key:
            return None
        seq = b.get(key) or []
        if len(seq) < 2:
            return None
        max_h = self.page_avail(False)
        head = {k: v for k, v in b.items() if k != key}
        best = 0
        for k in range(1, len(seq) + 1):
            probe = dict(head)
            probe[key] = seq[:k]
            if self._prep(probe)["h"] <= max_h:
                best = k
            else:
                break
        if best == 0:
            return None
        first = dict(head)
        first[key] = seq[:best]
        rest = dict(b)
        rest[key] = seq[best:]
        rest["title"] = str(b.get("title", "")) + "（续）"
        rest.pop("lead", None)
        return [first, rest]

    def _fit_to(self, b, max_h):
        it = self._prep(b)
        if it["h"] <= max_h:
            return [it]
        subs = self._split(b)
        if subs:
            out = []
            for s in subs:
                out.extend(self._fit_to(s, max_h))
            return out
        # 兜底：整块等比压缩，保证不越页
        it["img"] = it["img"].resize((self.W, int(max_h)), Image.LANCZOS)
        it["h"] = int(max_h)
        return [it]

    def build_header(self):
        if self._header_img is not None:
            return
        im, d = self._canvas()
        h = int(max(1, self.header(d)))
        self._header_h = h
        self._header_img = im.crop((0, 0, self.W, h))

    def paginate(self):
        self.build_header()
        items = []
        for b in self.spec.get("blocks") or []:
            items.extend(self._fit_to(b, self.page_avail(False)))
        pages, cur, used, first = [], [], 0, True
        for it in items:
            if cur and used + it["h"] > self.page_avail(first):
                pages.append(cur)
                cur, used, first = [], 0, False
            cur.append(it)
            used += it["h"] + GAP
        if cur:
            pages.append(cur)
        return pages

    def page_footer(self, d, idx, total, last):
        ft = self.spec.get("footer") or {}
        ly = self.H - 92
        src = ft.get("source")
        if last and src:
            f = self.font(20)
            lines = self.wrap(src, f, self.W - 2 * M - 130)
            step = int(f.size * 1.45)
            yy = ly - 16 - len(lines) * step
            for ln in lines:
                d.text((M, yy), ln, font=f, fill=self.sub)
                yy += step
        d.line([(M, ly), (self.W - M, ly)], fill=self.line, width=1)
        self.logo(d, ly + 20)
        brand = ft.get("brand")
        if brand:
            f = self.font(20, True)
            lw = self._logo.width if self._logo else 0
            d.text((M + lw + 20, ly + 28), brand, font=f, fill=self.sub)
        no = f"{idx:02d}/{total:02d}"
        f = self.font(20)
        d.text((self.W - M - f.getlength(no), ly + 26), no, font=f, fill=self.sub)

    def solo_quote(self, d, b):
        """结论单独成页时放大居中，做成收尾金句页"""
        lab = b.get("label") or "结论"
        f = self.font(52, True)
        lines = self.wrap(b.get("text", ""), f, self.cw)
        step = int(f.size * 1.7)
        src = b.get("from")
        total = len(lines) * step + (74 if src else 0)
        top = MINI_H + GAP + max(0, (self.H - FOOT_H - MINI_H - GAP - total) // 2 - 10)
        d.text((M, top - 64), lab, font=self.font(24, True), fill=self.accent2)
        d.rectangle([M, top - 22, M + 72, top - 16], fill=self.accent2)
        y = top
        for ln in lines:
            d.text((M, y), ln, font=f, fill=self.ink)
            y += step
        if src:
            d.rectangle([M, y + 16, M + 56, y + 20], fill=self.accent)
            d.text((M, y + 36), src, font=self.font(24), fill=self.sub)

    def draw_page(self, items, idx, total):
        canvas = Image.new("RGB", (self.W, self.H), self.bg)
        d = ImageDraw.Draw(canvas)
        d._image = canvas
        if idx == 1:
            canvas.paste(self._header_img, (0, 0))
            y = self._header_h + GAP
        else:
            self.mini_header(d, idx, total)
            y = MINI_H + GAP
        # 结论单独成页时放大居中，做成收尾金句页
        solo = len(items) == 1 and items[0]["b"].get("type") == "quote"
        if solo:
            self.solo_quote(d, items[0]["b"])
        else:
            if len(items) == 1:
                items = [self.fill_solo(items[0], self.H - FOOT_H - y - 24)]
            for it in items:
                if y >= self.H - FOOT_H:
                    break
                canvas.paste(it["img"], (0, int(y)))
                y += it["h"] + GAP
        self.page_footer(d, idx, total, idx == total)
        return canvas

    def render_pages(self):
        pages = self.paginate()
        return [self.draw_page(p, i + 1, len(pages)) for i, p in enumerate(pages)]

    # ---------- 长图模式（--long 回退） ----------
    def draw_all(self, canvas):
        d = ImageDraw.Draw(canvas)
        d._image = canvas
        y = self.header(d)
        for b in self.spec.get("blocks") or []:
            y = self.block(d, b, y + self.gap)
        y += self.gap
        d.line([(M, y), (self.W - M, y)], fill=self.line, width=2)
        y += 18
        ft = self.spec.get("footer") or {}
        if ft.get("source"):
            y = self.text(d, (M, y), ft["source"], self.font(21), self.sub, lh=1.5)
        self.logo(d, y + 10)
        brand = ft.get("brand")
        if brand:
            f = self.font(21, True)
            d.text((self.W - M - f.getlength(brand), y + 22), brand, font=f, fill=self.sub)
        return y + 70

    def render_long(self):
        probe = Image.new("RGB", (self.W, TMP_H), self.bg)
        d = ImageDraw.Draw(probe)
        d._image = probe
        heights = [self.block(d, b, 0) for b in self.spec.get("blocks") or []]
        ph = Image.new("RGB", (self.W, 760), self.bg)
        dh = ImageDraw.Draw(ph)
        dh._image = ph
        head_h = self.header(dh)
        foot_h = 110
        body = sum(heights)
        n = len(heights) + 2
        target = int(self.target_h or 0)
        if target and target > head_h + body + foot_h + n * 24:
            self.gap = min(56, int((target - head_h - body - foot_h) / n))
            H = target
        else:
            self.gap = 34
            H = head_h + body + foot_h + n * self.gap
        canvas = Image.new("RGB", (self.W, H), self.bg)
        used = self.draw_all(canvas)
        return [canvas], used


def main():
    ap = argparse.ArgumentParser(description="排版二创：只换版式与配色，输出小红书固定尺寸")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True, help="输出目录，或 .png 前缀（输出 01.png 02.png…）")
    ap.add_argument("--pdf", help="同时导出多页 PDF")
    ap.add_argument("--long", action="store_true", help="回退为单张长图")
    ap.add_argument("--palette-file", default=os.path.join(BASE, "assets", "palettes.json"))
    args = ap.parse_args()

    spec = load_json(args.spec)
    doc = Doc(spec, args.palette_file)
    if args.long:
        canvases, used = doc.render_long()
    else:
        canvases, used = doc.render_pages(), None

    raw = args.out.rstrip("/\\")
    ext = os.path.splitext(raw)[1].lower()
    if ext in (".png", ".jpg", ".jpeg"):
        out_dir, prefix = os.path.dirname(os.path.abspath(raw)), os.path.splitext(os.path.basename(raw))[0] + "_"
    else:
        out_dir, prefix = os.path.abspath(raw), ""
    os.makedirs(out_dir, exist_ok=True)

    files = []
    for i, cv in enumerate(canvases, 1):
        p = os.path.join(out_dir, f"{prefix}{i:02d}.png")
        cv.save(p, "PNG", optimize=True)
        files.append(p)
    out = {"ok": True, "pages": len(files), "size": [doc.W, doc.H],
           "style": doc.style, "palette": spec.get("palette"),
           "blocks": len(spec.get("blocks") or []), "files": files}
    if args.pdf:
        canvases[0].save(args.pdf, "PDF", resolution=150.0,
                         save_all=True, append_images=canvases[1:])
        out["pdf"] = args.pdf
    if used is not None:
        out["bottom"] = used
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
