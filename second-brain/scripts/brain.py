#!/usr/bin/env python3
"""第二大脑的检索与体检。只做确定性的事：找书、建索引、查卡片。

判断书里说了什么、该怎么用，是模型的事，这个脚本不碰。

用法：
  python3 brain.py recall "问题" [--top 6] [--json]   按思考维度路由到书（默认）
  python3 brain.py recall --dim 尺度 [--dim 假两难]   直接取某维度下的书
  python3 brain.py recall --topic "问题"              按话题字面打分（查事实时用）
  python3 brain.py recall --all                       列出全部书的视野行
  python3 brain.py index                              重生成 index.md 与 index.json
  python3 brain.py check                              体检卡片与索引
  python3 brain.py add --notes P [--slug S]           从 read-a-book 笔记生成卡片骨架

扩展性原则：书涨到几百上千本，进上下文的量也不涨。
  - 路由走 references/dimensions.md 的**维度表**；维度数是人为固定的，
    所以 index.md 的大小只随维度数变化，不随书数变化。
  - 书级检索读 index.json（机器层，模型永远不看），不再逐本 parse markdown。
  - 模型永远只读 1–2 张卡。

字段口径见 references/cards.md。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
BOOKS_DIR = SKILL_DIR / "books"
INDEX = SKILL_DIR / "index.md"
MACHINE = SKILL_DIR / "index.json"
DIM_FILE = SKILL_DIR / "references" / "dimensions.md"

REQUIRED = ("slug", "title", "author", "source_type", "read_at",
            "domains", "thesis", "triggers", "lens", "dimensions")
LIST_FIELDS = ("domains", "triggers", "aliases", "dimensions")

# 命中权重：触发词是作者/提炼者特意写下的检索入口，权重最高；
# 领域词宽泛，只作辅助。整句命中比零散字重合可信得多。
W_TRIGGER = 6.0
W_DOMAIN = 2.5
W_TITLE = 9.0
W_ALIAS = 7.0
W_BIGRAM = 1.5

# index.md 每维只列"有帮助的那几本"，不是全部——它是指路牌，不是书目。
EXEMPLARS = 4
INDEX_TOKEN_BUDGET = 3000


def die(msg: str, code: int = 2):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def norm(s: str) -> str:
    """只留中日韩文字与字母数字，其余（标点、空白、emoji）一律丢掉。"""
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (s or "").lower(), flags=re.UNICODE)


def bigrams(s: str) -> set[str]:
    n = norm(s)
    if len(n) < 2:
        return {n} if n else set()
    return {n[i:i + 2] for i in range(len(n) - 1)}


def _scalar(v: str):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
    return v.strip("'\"")


def parse_card(path: Path) -> dict:
    """解析卡片。只认一个很小的 YAML 子集：key: 值、key: [a, b]、key:\\n  - a。"""
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end == -1:
            die(f"{path} 的 frontmatter 没有收尾的 ---")
        fm, body = text[3:end], text[end + 4:]
        key = None
        for raw in fm.splitlines():
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            if raw.lstrip().startswith("- ") and key:
                meta.setdefault(key, [])
                if isinstance(meta[key], list):
                    meta[key].append(raw.lstrip()[2:].strip().strip("'\""))
                continue
            if ":" not in raw:
                continue
            key, _, val = raw.partition(":")
            key = key.strip()
            val = val.strip()
            if not val:
                meta[key] = []
            else:
                meta[key] = _scalar(val)
    meta["_path"] = path
    meta["_body"] = body
    return meta


def all_cards() -> list[dict]:
    if not BOOKS_DIR.is_dir():
        return []
    return [parse_card(p) for p in sorted(BOOKS_DIR.glob("*.md"))]


def as_list(meta: dict, key: str) -> list[str]:
    v = meta.get(key)
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    return [str(v)]


def short_name(s: str) -> str:
    """`埃里克·乔根森（Eric Jorgenson）` → `埃里克·乔根森`。"""
    return re.split(r"[（(]", str(s).strip())[0].strip()


def est_tokens(text: str) -> int:
    """粗估：中文约 1.5 字/token，混排取 1.6 作整体除数。只用来说明量级。"""
    return max(1, round(len(text) / 1.6))


def slug_of(meta: dict) -> str:
    return str(meta.get("slug") or meta["_path"].stem)


def weight_of(meta: dict) -> int:
    """卡片可选的 weight：越高越可能占 index.md 每维的代表位。缺省 0。"""
    try:
        return int(str(meta.get("weight") or "0").strip() or 0)
    except (TypeError, ValueError):
        return 0


# 这些二字组合几乎出现在任何中文句子里，留着会让"晚饭吃什么"也匹配上书。
STOP_BIGRAMS = {
    "什么", "时候", "自己", "还是", "一个", "我们", "他们", "可以", "因为", "所以",
    "但是", "如果", "这样", "那样", "怎么", "为什", "这个", "那个", "我的", "你的",
    "他的", "不是", "就是", "没有", "觉得", "应该", "到底", "其实", "现在", "已经",
    "问题", "事情", "东西", "地方", "知道", "想要", "需要", "可能", "一直", "有些",
}


# ---------------------------------------------------------------- 维度层


def load_dimensions() -> dict:
    """解析 references/dimensions.md。固定格式：## 名 / 说明：… / 问法：a · b"""
    if not DIM_FILE.exists():
        return {}
    dims: dict[str, dict] = {}
    cur = None
    for raw in DIM_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            cur = line[3:].strip()
            if cur:
                dims[cur] = {"desc": "", "ask": []}
        elif cur and line.startswith("说明："):
            dims[cur]["desc"] = line[len("说明："):].strip()
        elif cur and line.startswith("问法："):
            dims[cur]["ask"] = [x.strip() for x in line[len("问法："):].split("·") if x.strip()]
    return dims


def score_dimensions(q: str, dims: dict, floor: float = 1.0) -> list[tuple[float, str, list[str]]]:
    """把问题路由到维度。整句命中问法/维度名权重最高，字面近似只作补充。"""
    qn = norm(q)
    if not qn:
        return []
    qb = bigrams(qn) - STOP_BIGRAMS
    out: list[tuple[float, str, list[str]]] = []
    for name, d in dims.items():
        s, hits = 0.0, []
        nn = norm(name)
        if len(nn) >= 2 and nn in qn:
            s += 6.0
            hits.append(name)
        for a in d["ask"]:
            an = norm(a)
            if len(an) >= 2 and an in qn:
                s += 6.0 + min(len(an), 6) * 0.3
                hits.append(a)
        tb = bigrams(name + d["desc"]) - STOP_BIGRAMS
        if len(tb) >= 2:
            shared = tb & qb
            ratio = len(shared) / len(tb)
            if len(shared) >= 3 and ratio >= 0.2:
                s += 2.0 * ratio
                hits.append("字面：" + "/".join(sorted(shared)[:5]))
        if s >= floor:
            out.append((s, name, hits))
    out.sort(key=lambda r: (-r[0], r[1]))
    return out


def dimension_menu(dims: dict) -> str:
    return " · ".join(dims.keys())


# ---------------------------------------------------------------- 机器索引


def build_machine_index(cards: list[dict], dims: dict) -> dict:
    books: dict[str, dict] = {}
    inv: dict[str, list[str]] = {name: [] for name in dims}
    for m in cards:
        slug = slug_of(m)
        ds = [d for d in as_list(m, "dimensions") if d in dims]
        books[slug] = {
            "title": m.get("title"),
            "author": m.get("author"),
            "editor": m.get("editor"),
            "lens": m.get("lens"),
            "thesis": m.get("thesis"),
            "dimensions": ds,
            "triggers": as_list(m, "triggers"),
            "domains": as_list(m, "domains"),
            "source_type": m.get("source_type"),
            "source_warning": m.get("source_warning"),
            "read_at": m.get("read_at"),
            "notes": m.get("notes"),
            "card": m["_path"].name,
            "weight": weight_of(m),
            "card_tokens_est": est_tokens(m["_path"].read_text(encoding="utf-8")),
        }
        for d in ds:
            inv[d].append(slug)
    return {"version": 1, "count": len(books), "dimensions": inv, "books": books}


def dump_machine(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def load_machine_index(cards: list[dict], dims: dict) -> tuple[dict, bool]:
    """读 index.json。缺失或与卡片数不一致时现场重建（不写盘），返回 (索引, 是否陈旧)。"""
    if MACHINE.exists():
        try:
            obj = json.loads(MACHINE.read_text(encoding="utf-8"))
            if obj.get("count") == len(cards):
                return obj, False
        except (json.JSONDecodeError, OSError):
            pass
        return build_machine_index(cards, dims), True
    return build_machine_index(cards, dims), True


# ---------------------------------------------------------------- 渲染 index.md


INDEX_HEAD = """# 视野索引

**这个文件是生成的**，别手改——改 `books/<slug>.md` 的 frontmatter，再跑
`python3 scripts/brain.py index`。

这张表按**思考维度**排，不按书排。
- 大小只随维度数变化，**不随书数变化**：几百上千本时它仍是唯一常读的文件。
- 每维只列**有帮助的那几本**，不是全部——它是指路牌，不是书目。代表位按卡片
  `weight` 排（高的在前），同 weight 按读完日期近的在前；一本书没被列出，不等于它不重要。
- 用法：读这张表 → 挑 2–4 个维度 → `python3 scripts/brain.py recall --dim <维度>` 取书
  → 只读那 1–2 张卡。
"""


def render_index(cards: list[dict], dims: dict) -> str:
    info = {}
    for m in cards:
        slug = slug_of(m)
        info[slug] = {
            "w": weight_of(m),
            "r": str(m.get("read_at") or ""),
            "ds": [d for d in as_list(m, "dimensions") if d in dims],
        }
    per_dim: dict[str, list[str]] = {name: [] for name in dims}
    for slug, b in info.items():
        for d in b["ds"]:
            per_dim[d].append(slug)
    # 先按日期近的排，再按 weight 稳定排序 → weight 高的在前，同 weight 日期近的在前。
    for slugs in per_dim.values():
        slugs.sort(key=lambda s: info[s]["r"], reverse=True)
        slugs.sort(key=lambda s: info[s]["w"], reverse=True)
    blocks = [INDEX_HEAD.rstrip()]
    for name, d in dims.items():
        slugs = per_dim[name]
        block = [f"## {name}（{len(slugs)} 本）"]
        if d["desc"]:
            block.append(d["desc"])
        if slugs:
            line = " · ".join(slugs[:EXEMPLARS])
            if len(slugs) > EXEMPLARS:
                line += f" · …另有 {len(slugs) - EXEMPLARS} 本，用 --dim {name} 取"
            block.append(line)
        else:
            block.append("（暂无）")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------- 话题打分（旧路径）


def score_card_topic(meta: dict, q: str) -> tuple[float, list[str], int]:
    """字面打分：整句包含 + 二字组近似。只在 --topic 模式用。"""
    qn = norm(q)
    if not qn:
        return 0.0, [], 0
    qb = bigrams(qn) - STOP_BIGRAMS
    score, hits, strong = 0.0, [], 0

    for field, w in (("title", W_TITLE), ("original_title", W_TITLE)):
        v = norm(str(meta.get(field) or ""))
        if v and len(v) >= 2 and v in qn:
            score += w
            hits.append(f"{field}「{meta.get(field)}」")
            strong += 1
    for a in as_list(meta, "aliases") + as_list(meta, "author"):
        v = norm(a)
        if v and len(v) >= 2 and v in qn:
            score += W_ALIAS
            hits.append(f"「{a}」")
            strong += 1

    for t in as_list(meta, "triggers"):
        tn = norm(t)
        if not tn:
            continue
        if tn in qn:
            score += W_TRIGGER + min(len(tn), 8) * 0.5
            hits.append(t)
            strong += 1
            continue
        tb = bigrams(tn) - STOP_BIGRAMS
        shared = tb & qb
        if len(tb) >= 2 and len(shared) >= 2:
            ratio = len(shared) / len(tb)
            if ratio >= 0.5:
                score += W_TRIGGER * 0.6 * ratio
                hits.append(f"≈{t}（{ratio:.0%}）")
                strong += 1

    for d in as_list(meta, "domains"):
        dn = norm(d)
        if dn and dn in qn:
            score += W_DOMAIN
            hits.append(d)
            strong += 1

    shared = (bigrams(str(meta.get("thesis") or "")) - STOP_BIGRAMS) & qb
    if len(shared) >= 2:
        score += W_BIGRAM * len(shared)
        hits.append("立场字面近：" + "/".join(sorted(shared)[:6]))
    return score, hits, strong


# ---------------------------------------------------------------- recall


def _source_note(b: dict) -> str:
    st = str(b.get("source_type") or "")
    if not st or st == "一手":
        return ""
    note = f"\n- ⚠️ 来源：{st}"
    if b.get("source_warning"):
        note += f"——{b['source_warning']}"
    return note


def _book_block(i: int, slug: str, b: dict, hit_dims: list[str], trigger_hit: bool) -> str:
    title = b.get("title") or slug
    author = b.get("author") or "?"
    if b.get("editor"):
        author += f"（{b['editor']} 编）"
    lines = [f"### {i}. 《{title}》（{slug}）"]
    lines.append(f"- 作者：{author}")
    if b.get("lens"):
        lines.append(f"- 视野：{b['lens']}")
    if hit_dims:
        lines.append(f"- 命中维度：{'、'.join(hit_dims)}")
    if trigger_hit:
        lines.append("- 另有触发词命中")
    lines.append(f"- 卡片：{b.get('card')}｜≈{b.get('card_tokens_est', 0)} tokens"
                 + (f"｜原笔记：{b['notes']}" if b.get("notes") else ""))
    src = _source_note(b)
    if src:
        lines.append(src.lstrip("\n"))
    return "\n".join(lines)


def _route_books(hit_dims, idx: dict, q: str, top: int):
    qn = norm(q)
    qb = bigrams(qn) - STOP_BIGRAMS
    scores: dict[str, float] = {}
    dims_of: dict[str, list[str]] = {}
    trig: set[str] = set()
    for ds, name, _ in hit_dims:
        for slug in idx["dimensions"].get(name, []):
            scores[slug] = scores.get(slug, 0.0) + ds
            dims_of.setdefault(slug, [])
            if name not in dims_of[slug]:
                dims_of[slug].append(name)
    for slug, b in idx["books"].items():
        bonus = 0.0
        for t in b.get("triggers", []):
            tn = norm(t)
            if len(tn) >= 2 and tn in qn:
                bonus += 4.0
            else:
                tb = bigrams(t) - STOP_BIGRAMS
                if len(tb) >= 2 and len(tb & qb) / len(tb) >= 0.5:
                    bonus += 2.0
        if bonus:
            scores[slug] = scores.get(slug, 0.0) + bonus
            trig.add(slug)
    # 同分同 weight 时按读完日期近的在前（与 index.md 的代表位规则一致），
    # 再用 slug 兜底保证顺序确定。稳定排序：先 slug，再日期，最后分/weight。
    items = sorted(scores.items(), key=lambda kv: kv[0])
    items.sort(key=lambda kv: idx["books"].get(kv[0], {}).get("read_at") or "", reverse=True)
    ranked = sorted(items,
                    key=lambda kv: (-kv[1], -idx["books"].get(kv[0], {}).get("weight", 0)))[:top]
    return ranked, dims_of, trig


def cmd_recall(args) -> int:
    cards = all_cards()
    if not cards:
        die(f"{BOOKS_DIR} 里还没有卡片。先用 brain.py add 加一本。")
    dims = load_dimensions()
    if not dims:
        die(f"读不到维度表 {DIM_FILE}")
    idx, stale = load_machine_index(cards, dims)

    # --all：列出全部书的视野行（小库用；书多时会截断）
    if args.all:
        print(f"# 全部视野（{len(idx['books'])} 本）\n")
        shown = list(idx["books"].items())
        if len(shown) > 40:
            print(f"书多于 40 本，只显示前 40 本；其余用 `--dim` 或 `--topic` 取。\n")
            shown = shown[:40]
        for slug, b in shown:
            print(f"- 《{b.get('title')}》（{slug}）｜{b.get('author')}｜{b.get('lens')}")
        return 0

    # --dim：直接取某维度下的书
    if args.dims:
        unknown = [d for d in args.dims if d not in dims]
        if unknown:
            die(f"维度表里没有：{'、'.join(unknown)}。可选：{dimension_menu(dims)}")
        slugs: list[str] = []
        for d in args.dims:
            for s in idx["dimensions"].get(d, []):
                if s not in slugs:
                    slugs.append(s)
        slugs.sort(key=lambda s: (idx["books"][s].get("weight", 0),
                                  idx["books"][s].get("read_at") or ""), reverse=True)
        print(f"# 维度 {'、'.join(args.dims)}（{len(slugs)} 本）\n")
        for d in args.dims:
            print(f"- {d}：{dims[d]['desc']}")
        print("")
        if not slugs:
            print("这些维度上还没有书。")
            return 0
        for i, slug in enumerate(slugs[:args.top], 1):
            b = idx["books"][slug]
            print(_book_block(i, slug, b, [], False))
            print("")
        return 0

    # --topic：旧的按话题字面打分
    if args.topic:
        ranked = sorted((score_card_topic(m, args.query) + (m,) for m in cards),
                        key=lambda r: -r[0])
        print(f"# 话题候选（问题：{args.query}）\n")
        if not ranked or not ranked[0][2]:
            print("**字面没有对得上的书。**判断类问题请用默认的维度路由"
                  "（不带 --topic），或直接读 index.md 挑维度。\n")
        for i, (sc, hits, strong, m) in enumerate(ranked[:args.top], 1):
            mark = "强" if strong else "弱"
            print(f"### {i}. 《{m.get('title')}》（{slug_of(m)}）  [{mark}] score={sc:.1f}")
            print(f"- 立场：{m.get('thesis')}")
            print(f"- 命中：{'、'.join(hits) if hits else '（无强命中，只有零散字重合）'}")
            print("")
        return 0

    # 默认：维度路由
    hits = score_dimensions(args.query, dims)
    print(f"# 视野候选（问题：{args.query}）\n")
    if not hits:
        print("**没有维度命中。** 这通常意味着问题用的是书里没有的说法。可以：")
        print("- 直接读 `index.md`（按维度排），人工挑 2–4 个维度；")
        print("- 用 `--topic` 做字面检索；")
        print("- 或者如实告诉用户：书库里没有覆盖这个方向的视野。\n")
        print(f"可用维度：{dimension_menu(dims)}")
        return 0
    print("命中维度：")
    for s, name, why in hits[:4]:
        print(f"- {name}（{s:.1f}）——{dims[name]['desc']}")
    print("")
    ranked, dims_of, trig = _route_books(hits[:4], idx, args.query, args.top)
    if not ranked:
        print("这些维度上还没有书。")
        return 0
    print(f"候选书（{len(ranked)} 本，读 1–2 本；第 2 本只在能形成对撞时才读）：\n")
    for i, (slug, sc) in enumerate(ranked, 1):
        b = idx["books"][slug]
        print(_book_block(i, slug, b, dims_of.get(slug, []), slug in trig))
        print("")
    if stale:
        print("（提示：index.json 与卡片数不一致，已现场重建；跑 `brain.py index` 写回。）")
    return 0


# ---------------------------------------------------------------- index / check / add


def cmd_index(args) -> int:
    cards = all_cards()
    if not cards:
        die("books/ 里没有卡片")
    dims = load_dimensions()
    if not dims:
        die(f"读不到维度表 {DIM_FILE}")
    rendered = render_index(cards, dims)
    machine = dump_machine(build_machine_index(cards, dims))

    if args.check:
        ok = True
        if not INDEX.exists() or INDEX.read_text(encoding="utf-8") != rendered:
            print("index.md 与卡片不一致", file=sys.stderr)
            ok = False
        if not MACHINE.exists() or MACHINE.read_text(encoding="utf-8") != machine:
            print("index.json 与卡片不一致", file=sys.stderr)
            ok = False
        if ok:
            print(f"index.md / index.json 与卡片一致（{len(cards)} 本）")
            return 0
        return 1

    INDEX.write_text(rendered, encoding="utf-8")
    MACHINE.write_text(machine, encoding="utf-8")
    tok = est_tokens(rendered)
    print(f"已重写 {INDEX}（{len(cards)} 本，{len(dims)} 个维度，≈{tok} tokens）")
    print(f"已重写 {MACHINE}（机器层，模型不用读）")
    if tok > INDEX_TOKEN_BUDGET:
        print(f"警告：index.md 已 {tok} tokens（预算 {INDEX_TOKEN_BUDGET}）——"
              f"该合并维度了，或把每维代表数调小。", file=sys.stderr)
    return 0


def cmd_check(_args) -> int:
    cards = all_cards()
    dims = load_dimensions()
    problems: list[str] = []
    warns: list[str] = []
    seen: dict[str, str] = {}
    for m in cards:
        p = m["_path"]
        name = p.name
        slug = m.get("slug")
        if not slug:
            problems.append(f"{name}: 缺 slug")
        elif slug != p.stem:
            problems.append(f"{name}: slug「{slug}」与文件名不一致")
        if slug in seen:
            problems.append(f"{name}: slug 与 {seen[slug]} 重复")
        seen[slug] = name
        for f in REQUIRED:
            if not m.get(f):
                problems.append(f"{name}: 缺字段 {f}")
        for f in LIST_FIELDS:
            if m.get(f) and not isinstance(m[f], list):
                problems.append(f"{name}: {f} 应是列表")
        if len(as_list(m, "triggers")) < 5:
            problems.append(f"{name}: triggers 少于 5 条，检索会不准")
        for d in as_list(m, "dimensions"):
            if d not in dims:
                near = [k for k in dims if d in k or k in d]
                hint = f"，是不是 {near[0]}？" if near else ""
                problems.append(f"{name}: 维度「{d}」不在 dimensions.md 里{hint}")
        lens = str(m.get("lens") or "")
        if lens and len(lens) > 90:
            warns.append(f"{name}: lens 有 {len(lens)} 字，压到 60 字内更像「看问题的方向」")
        notes = m.get("notes")
        if notes:
            np = Path(str(notes)).expanduser()
            if not (np if np.is_absolute() else SKILL_DIR / np).exists():
                warns.append(f"{name}: 找不到原笔记 {notes}（路径不对，检查 notes: 字段）")

    if not dims:
        problems.append(f"读不到维度表 {DIM_FILE}")
    else:
        missing = [d for d in dims if not any(d in as_list(m, "dimensions") for m in cards)]
        if missing:
            warns.append(f"没有书挂在这些维度上（书库缺口）：{'、'.join(missing)}")

    if INDEX.exists():
        if INDEX.read_text(encoding="utf-8") != render_index(cards, dims):
            problems.append("index.md 与卡片不一致——跑 brain.py index")
    else:
        problems.append("index.md 不存在——跑 brain.py index")
    if MACHINE.exists():
        if MACHINE.read_text(encoding="utf-8") != dump_machine(build_machine_index(cards, dims)):
            problems.append("index.json 与卡片不一致——跑 brain.py index")
    else:
        problems.append("index.json 不存在——跑 brain.py index")

    for x in problems:
        print(f"✗ {x}")
    for x in warns:
        print(f"! {x}")
    print(f"\n{len(cards)} 本卡片，{len(problems)} 个问题"
          if problems else f"\n{len(cards)} 本卡片，全部通过")
    if warns:
        print(f"（另有 {len(warns)} 条提醒，不影响使用）")
    return 1 if problems else 0


SECTION_PAT = {
    "thesis": r"^#+\s*8\.[^\n]*\n+(.+?)(?=\n#|\Z)",
    "keywords": r"^#+\s*11\.[^\n]*\n+(.+?)(?=\n#+\s*12|\Z)",
    "unresolved": r"^#+\s*14\.[^\n]*\n+(.+?)(?=\n#+\s*15|\n---|\Z)",
}


def cmd_add(args) -> int:
    src = Path(args.notes).expanduser().resolve()
    if not src.is_file():
        die(f"找不到笔记：{src}")
    text = src.read_text(encoding="utf-8")
    slug = args.slug or src.parent.name
    out = BOOKS_DIR / f"{slug}.md"
    if out.exists() and not args.force:
        die(f"{out} 已存在。要覆盖加 --force。")

    title = src.parent.name
    m = re.search(r"^#\s+(.+?)\s*——", text, re.M)
    if m:
        title = m.group(1).strip()
    bib = re.search(r"^\*\*(.+?)\*\*", text, re.M)
    bib_line = bib.group(1).strip() if bib else ""

    def grab(key: str) -> str:
        mm = re.search(SECTION_PAT[key], text, re.M | re.S)
        return (mm.group(1).strip() if mm else "").strip()

    # 一句话主旨常常是带 ** 强调的多行段落，取整段再压平，
    # 只取第一行会得到半句话。
    thesis = " ".join(ln.strip() for ln in grab("thesis").splitlines() if ln.strip())
    thesis = re.sub(r"\*\*(.+?)\*\*", r"\1", thesis).strip("*_ ").strip()
    if len(thesis) > 160:
        print(f"提示：一句话主旨有 {len(thesis)} 字，填进卡片时压短一点", file=sys.stderr)
    keywords = grab("keywords")
    unresolved = grab("unresolved")
    # 原笔记收进 skill 自己的 notes/。
    notes_dir = SKILL_DIR / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    dest_note = notes_dir / f"{slug}.md"
    if src != dest_note:
        shutil.copy2(src, dest_note)
    rel_notes = Path("notes") / dest_note.name

    scaffold = f"""---
slug: {slug}
title: {title}
original_title:
author:
author_en:
editor:
translator:
publisher:
year:
edition_note:
source_type:
source_warning:
read_at: {args.read_at}
notes: {rel_notes}
domains: []
thesis: {thesis}
lens:
triggers: []
dimensions: []
confidence:
---

<!-- 骨架由 brain.py add 生成。下面标 TODO 的地方要人来判断，脚本填不了。 -->

## 什么时候该想起它
<!-- TODO: 3-5 条问题形态，写成"用户在问什么"的样子，不是章节标题 -->

## 什么时候别用它
<!-- TODO: 这本书的边界。没有这一节，第二大脑会变成"什么都往上套" -->

## 核心命题
<!-- TODO: 2-4 条，每条 = 主张 + 依据 + 出处（章节/页码）。要可反驳，不要金句 -->

## 常被引用的原句
<!-- 从笔记的"关键主旨"里搬，必须带位置 -->

## 与其他书
<!-- 上游 / 对立 / 同体例。只写有依据的，没有证据就留空 -->

---

## 待处理：从笔记机械提取的原料

**书目行**（用来填上面的 publisher / year / translator / editor）：
{bib_line or "（笔记里没有识别到）"}

**关键词表**（填 triggers 和 domains 的主要来源）：

{keywords or "（没提取到）"}

**未解决之处**（填「什么时候别用它」的主要来源）：

{unresolved or "（没提取到）"}
"""
    out.write_text(scaffold, encoding="utf-8")
    print(f"已生成 {out}")
    print(f"原笔记已收进 {dest_note}")
    print("接下来要手填：author / source_type / domains / triggers / lens / dimensions / 六节正文，"
          "然后把「待处理」整段删掉。")
    print("其中 lens 与 dimensions 的口径见 references/cards.md 和 references/dimensions.md。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="第二大脑：检索、索引、体检")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("recall", help="按思考维度路由到书（默认）")
    p.add_argument("query", nargs="?", default=None, help="问题原话")
    p.add_argument("--top", type=int, default=6)
    p.add_argument("--json", action="store_true")
    p.add_argument("--dim", dest="dims", action="append", default=None,
                   help="直接取某维度下的书，可重复")
    p.add_argument("--topic", action="store_true", help="改用旧的按话题字面打分")
    p.add_argument("--all", action="store_true", help="列出全部书的视野行")
    p.set_defaults(fn=cmd_recall)

    p = sub.add_parser("index", help="重生成 index.md 与 index.json")
    p.add_argument("--check", action="store_true", help="只比对，不写")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("check", help="体检卡片与索引")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("add", help="从 read-a-book 笔记生成卡片骨架")
    p.add_argument("--notes", required=True)
    p.add_argument("--slug", default=None)
    p.add_argument("--read-at", default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_add)

    args = ap.parse_args()
    if args.cmd == "add" and not args.read_at:
        from datetime import date
        args.read_at = date.today().isoformat()
    if args.cmd == "recall" and not args.all and not args.dims and not args.query:
        die("recall 需要一个问题原话（或 --dim / --all）")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
