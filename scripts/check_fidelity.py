# -*- coding: utf-8 -*-
"""保真闸门：校验文案是否覆盖全部 must 事实、是否篡改数字、长度是否匹配。

用法：
    python check_fidelity.py --facts facts.json --copy 文案.md
    python check_fidelity.py --facts facts.json --copy 文案.md --strip-out 文案_纯文本.txt

退出码：0 全过 / 1 有硬失败 / 2 仅有待确认项
"""
import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TAG_PAT = re.compile(r"\[\[(F\d{2,3})\]\]")
NUM_PAT = re.compile(r"\d+(?:\.\d+)?")
YEAR_PAT = re.compile(r"20\d{2}")


def load_facts(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("facts", [])


def cn_len(text):
    t = TAG_PAT.sub("", text)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"[*_>`~\[\]()#]", "", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\s+", "", t)
    return len(t)


def body_only(text):
    """剥掉标题区/标签区，粗略取正文：去掉 # 开头的行和纯标签行。"""
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(">"):
            continue
        if s.startswith("#") and " " not in s:
            continue
        if re.fullmatch(r"[#\w\u4e00-\u9fa5\s]+", s) and s.count("#") >= 5:
            continue
        lines.append(s)
    return "\n".join(lines)


def normalize(s):
    return re.sub(r"[\s，。,．.、；;：:（）()「」“”\"'·\-—]", "", s)


def keyword_hit(fact, text):
    """宽松语义匹配：数字全中 + 关键词覆盖 >=60%"""
    stmt = fact.get("statement", "")
    words = [w for w in re.split(r"[，。、；：（）()\s]+", stmt) if len(w) >= 2]
    if not words:
        return False
    hit = sum(1 for w in words if normalize(w) in normalize(text))
    nums = fact.get("numbers") or []
    num_ok = all(n in text for n in nums) if nums else True
    return num_ok and hit / len(words) >= 0.6


def close_enough(a, b):
    """a 是否为 b 的合理换算写法（万/千/百分比/四舍五入）"""
    try:
        fa, fb = float(a), float(b)
    except ValueError:
        return False
    if fa == fb:
        return True
    for scale in (1, 100, 1000, 10000):
        if fb and abs(fa * scale - fb) / max(abs(fb), 1e-6) <= 0.05:
            return True
        if fa and abs(fb * scale - fa) / max(abs(fa), 1e-6) <= 0.05:
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description="事实保真校验")
    ap.add_argument("--facts", required=True)
    ap.add_argument("--copy", required=True)
    ap.add_argument("--variant", help="variant.json，用于读取长度档位（可选）")
    ap.add_argument("--strip-out", help="把清除 [[Fxx]] 标记后的正文写到该文件")
    ap.add_argument("--json", help="报告写入该 json 文件")
    args = ap.parse_args()

    facts = load_facts(args.facts)
    with open(args.copy, "r", encoding="utf-8") as f:
        raw = f.read()

    tags = set(TAG_PAT.findall(raw))
    body = TAG_PAT.sub("", body_only(raw))  # 去掉 [[Fxx]] 标记，避免 F10+ 被当成数字
    length = cn_len(body)

    must = [x for x in facts if x.get("level") == "must"]
    should = [x for x in facts if x.get("level") != "must"]

    # 1) 覆盖检查
    use_tag_mode = len(tags) > 0
    covered, missing = [], []
    for fact in must:
        fid = fact["id"]
        ok = fid in tags if use_tag_mode else keyword_hit(fact, body)
        (covered if ok else missing).append(fid)

    should_covered = sum(1 for x in should if (x["id"] in tags or keyword_hit(x, body)))

    # 2) 数字比对
    allowed = set()
    for fact in facts:
        for n in fact.get("numbers") or []:
            allowed.add(str(n))
    allowed_num = {n for n in allowed if NUM_PAT.fullmatch(n)}

    suspicious = []
    years = []
    for m in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)(%?)", body):
        val, pct = m.group(1), m.group(2)
        if YEAR_PAT.fullmatch(val):
            years.append(val)  # 年份单独记录，不当篡改
            continue
        if val in allowed:
            continue
        if any(close_enough(val, a) for a in allowed_num):
            continue
        try:
            f = float(val)
        except ValueError:
            continue
        if not pct and f < 10:
            continue  # 序号/量词，忽略
        ctx = body[max(0, m.start() - 12): m.start() + len(val) + 8].replace("\n", " ")
        suspicious.append({"value": val + pct, "context": ctx})

    # 3) 长度
    target = int(min(1000, max(350, len(must) * 45 + len(should) * 15 + 120)))
    lo, hi = int(target * 0.8), int(target * 1.2)
    length_ok = lo <= length <= hi

    # 结论
    hard_fail = bool(missing) or not length_ok
    warn = bool(suspicious)

    report = {
        "ok": not hard_fail,
        "facts_total": len(facts),
        "must_total": len(must),
        "must_covered": len(covered),
        "must_missing": missing,
        "should_total": len(should),
        "should_covered": should_covered,
        "coverage_rate": round(len(covered) / len(must), 3) if must else 1.0,
        "tag_mode": "标记" if use_tag_mode else "语义匹配",
        "length": length,
        "length_target": target,
        "length_range": [lo, hi],
        "length_ok": length_ok,
        "suspicious_numbers": suspicious,
        "years_mentioned": sorted(set(years)),
        "verdict": "PASS" if not hard_fail and not warn else ("FAIL" if hard_fail else "WARN"),
    }

    if args.strip_out:
        cleaned = TAG_PAT.sub("", raw)
        with open(args.strip_out, "w", encoding="utf-8") as f:
            f.write(cleaned)
        report["stripped_to"] = args.strip_out

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not use_tag_mode:
        print("\n[提示] 文案里没有 [[Fxx]] 标记，已退化为语义匹配，建议补标记以提高准确性。",
              file=sys.stderr)

    if hard_fail:
        sys.exit(1)
    if warn:
        sys.exit(2)


if __name__ == "__main__":
    main()
