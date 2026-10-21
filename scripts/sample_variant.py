# -*- coding: utf-8 -*-
"""变量采样器：同一份素材每次产出不同的表达组合，并靠历史指纹去重。

用法：
    python sample_variant.py --out output/x/v1              # 采一份
    python sample_variant.py --out output/x --n 3           # 一次出 3 份互斥组合
    python sample_variant.py --out output/x --set tone=干货直给 --set palette=navy_gold
    python sample_variant.py --seed 1734 --out output/x     # 复现某次
    python sample_variant.py --commit output/x/variant.json # 交付后记指纹

退出码 0 成功，1 参数错误。
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(BASE, "history", "fingerprints.jsonl")
PALETTES = os.path.join(BASE, "assets", "palettes.json")

# (id, 中文标签) —— 中文标签给 AI 读，id 给去重比
DIMENSIONS = {
    "perspective": [
        ("testifier", "备考者自述"), ("veteran", "过来人复盘"), ("observer", "数据观察者"),
        ("teacher", "老师答疑"), ("lister", "清单罗列"), ("dialogue", "场景对话"),
    ],
    "hook": [
        ("counterintuitive", "反常识"), ("number", "数字冲击"), ("painpoint", "痛点共鸣"),
        ("urgent", "时间紧迫"), ("conclusion", "结论前置"), ("question", "提问"), ("contrast", "对比"),
    ],
    "structure": [
        ("general", "总分总"), ("timeline", "时间线"), ("qa", "问题-解答"),
        ("list", "清单体"), ("compare", "对比拆解"), ("steps", "步骤流"),
    ],
    "tone": [
        ("sister", "姐妹口语"), ("calm", "冷静分析"), ("dry", "干货直给"),
        ("gentle", "温和陪伴"), ("sharp", "犀利提醒"),
    ],
    "rhythm": [
        ("short", "短句密排"), ("block", "长段+小标题"),
        ("numbered", "编号列表"), ("quote", "引号对话"),
    ],
    "title_pattern": [
        ("number", "数字型"), ("question", "疑问型"), ("contrast", "对比型"),
        ("conclusion", "结论型"), ("identity", "身份型"), ("urgent", "紧迫型"),
    ],
    "palette": [
        ("cream_orange", "奶油橙"), ("mist_blue", "雾霾蓝"), ("mint", "薄荷青"),
        ("paper_pink", "藕粉纸"), ("kraft", "牛皮纸"), ("sky", "天空白"),
        ("forest", "森茶绿"), ("lilac", "藕荷紫"), ("ink_red", "墨黑正红"),
        ("navy_gold", "深海金"), ("black_lime", "黑青柠"), ("wine", "酒红米"),
    ],
    "layout": [
        ("magazine", "杂志刊头"), ("card", "卡片流"), ("bigtype", "大字报"),
        ("memo", "手账便签"), ("data", "数据页"), ("index", "目录索引"),
    ],
    "cover": [
        ("stat", "数字卡"), ("bigword", "关键词大字"),
        ("question", "问题句"), ("toc", "目录预告"),
    ],
    "font_pair": [
        ("yahei_bold", "雅黑粗+雅黑"), ("hei_bold", "黑体+雅黑"),
        ("yahei_only", "雅黑粗+细"), ("hei_only", "黑体+黑体"), ("mixed", "雅黑+黑体"),
    ],
    "deer": [
        ("study", "看书"), ("cheer", "点赞"), ("sprint", "冲刺"),
        ("harvest", "耕耘"), ("board", "举牌"), ("rest", "休息"),
    ],
}

KEY_ORDER = list(DIMENSIONS.keys())
LABEL2ID = {label: vid for k, vals in DIMENSIONS.items() for vid, label in vals}
# 全局标签查表（--set 时用，不区分维度）
ALL_LABEL2ID = {}
for k, vals in DIMENSIONS.items():
    for vid, label in vals:
        ALL_LABEL2ID[label] = vid
        ALL_LABEL2ID[vid] = vid

# 弱约束维度：这些重合不算"撞衫"
WEAK = {"font_pair", "deer", "rhythm"}


def load_history(path=HISTORY, limit=20):
    if not os.path.exists(path):
        return []
    recs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return recs[-limit:][::-1]  # 最近的在前


def weight_for(value, key, history):
    w = 1.0
    for i, rec in enumerate(history[:12]):
        dims = rec.get("dimensions", rec)
        if dims.get(key) == value:
            w *= 0.35 if i < 3 else 0.72
    return max(w, 0.02)


def weighted_pick(rng, key, history):
    vals = DIMENSIONS[key]
    weights = [weight_for(vid, key, history) for vid, _ in vals]
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for (vid, label), w in zip(vals, weights):
        acc += w
        if r <= acc:
            return vid
    return vals[-1][0]


def overlap(v, rec_dims):
    keys = [k for k in KEY_ORDER if k not in WEAK]
    return sum(1 for k in keys if rec_dims.get(k) == v.get(k))


def valid(v, history):
    for rec in history[:3]:
        if overlap(v, rec.get("dimensions", rec)) > 2:
            return False
    triple = (v.get("structure"), v.get("layout"), v.get("palette"))
    for rec in history[:10]:
        d = rec.get("dimensions", rec)
        if (d.get("structure"), d.get("layout"), d.get("palette")) == triple:
            return False
    return True


def sample_one(rng, history, overrides, relaxed=False):
    for _ in range(200):
        v = {}
        for key in KEY_ORDER:
            v[key] = overrides[key] if key in overrides else weighted_pick(rng, key, history)
        if relaxed or valid(v, history):
            return v, relaxed
    # 兜底：强制换三个强维度，其余随机
    v = {k: (overrides[k] if k in overrides else rng.choice([x[0] for x in DIMENSIONS[k]]))
         for k in KEY_ORDER}
    for key in ("structure", "layout", "palette", "perspective"):
        if key not in overrides:
            used = {r.get("dimensions", r).get(key) for r in history[:10]}
            for vid, _ in DIMENSIONS[key]:
                if vid not in used:
                    v[key] = vid
                    break
    return v, True


def decorate(v):
    return {
        "seed": v.pop("_seed") if "_seed" in v else None,
        "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "dimensions": {
            k: {"id": v[k], "label": dict(DIMENSIONS[k])[v[k]]} for k in KEY_ORDER
        },
    }


def parse_overrides(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--set 格式应为 key=值，收到：{it}")
        k, raw = it.split("=", 1)
        k, raw = k.strip(), raw.strip()
        if k not in DIMENSIONS:
            raise SystemExit(f"未知维度 {k}，可选：{', '.join(KEY_ORDER)}")
        vid = ALL_LABEL2ID.get(raw)
        if vid is None:
            valid_ids = ", ".join(v for v, _ in DIMENSIONS[k])
            raise SystemExit(f"维度 {k} 不支持取值 {raw}，可选：{valid_ids}")
        out[k] = vid
    return out


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def commit(variant_path, history=HISTORY):
    with open(variant_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    dims = {k: v["id"] for k, v in data.get("dimensions", {}).items()}
    rec = {"ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
           "seed": data.get("seed"), "dimensions": dims,
           "source": data.get("source", ""), "out": os.path.dirname(os.path.abspath(variant_path))}
    os.makedirs(os.path.dirname(history), exist_ok=True)
    lines = []
    if os.path.exists(history):
        with open(history, "r", encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
    lines.append(json.dumps(rec, ensure_ascii=False) + "\n")
    lines = lines[-500:]
    with open(history, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(json.dumps({"committed": True, "history_size": len(lines)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="笔记二创变量采样器")
    ap.add_argument("--out", help="输出目录，或 .json 文件路径")
    ap.add_argument("--n", type=int, default=1, help="一次生成几份互斥组合")
    ap.add_argument("--seed", type=int, help="复现用")
    ap.add_argument("--set", action="append", help="定向指定维度，可多次，如 --set tone=干货直给")
    ap.add_argument("--force", action="store_true", help="忽略最近用过的提示")
    ap.add_argument("--commit", help="把指定 variant.json 写入历史指纹")
    ap.add_argument("--source", default="", help="素材名，写入指纹便于回溯")
    args = ap.parse_args()

    if args.commit:
        commit(args.commit)
        return

    if not args.out:
        ap.error("需要 --out")

    history = load_history()
    overrides = parse_overrides(args.set)
    seed = args.seed if args.seed is not None else random.SystemRandom().randint(1, 10 ** 9)
    rng = random.Random(seed)
    n = 1 if str(args.out).lower().endswith(".json") else max(1, args.n)

    results = []
    batch = []
    for i in range(n):
        v, relaxed = sample_one(rng, history + batch, overrides)
        if n > 1:  # 批次内强维度必须两两不同
            tries = 0
            while any(v["perspective"] == b["perspective"] or v["structure"] == b["structure"]
                      or v["palette"] == b["palette"] for b in batch) and tries < 100:
                v, relaxed = sample_one(rng, history + batch, overrides)
                tries += 1
        v["_seed"] = seed + i
        data = decorate(v)
        data["relaxed"] = relaxed
        data["source"] = args.source
        data["n_index"] = i + 1
        batch.append({k: data["dimensions"][k]["id"] for k in KEY_ORDER})
        results.append(data)

    for i, data in enumerate(results):
        if str(args.out).lower().endswith(".json") and n == 1:
            path = args.out
        else:
            path = os.path.join(args.out, f"variant_v{i + 1}.json" if n > 1 else "variant.json")
        write_json(path, data)
        print(f"OK  {path}")

    print(json.dumps({
        "seed": seed,
        "count": n,
        "relaxed": any(r["relaxed"] for r in results),
        "summary": [{k: r["dimensions"][k]["label"] for k in ("perspective", "structure", "palette", "layout")}
                    for r in results],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
