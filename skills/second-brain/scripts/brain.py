#!/usr/bin/env python3
"""第二大脑的检索与体检。只做确定性的事：找书、建索引、查卡片。

判断书里说了什么、该怎么用，是模型的事，这个脚本不碰。

用法：
  python3 brain.py recall "问题" [--top 6] [--json]   多路召回 + RRF 融合（默认）
  python3 brain.py recall --dim 尺度 [--dim 假两难]   直接取某维度下的书
  python3 brain.py recall --topic "问题"              按话题字面打分（查事实时用）
  python3 brain.py recall --all                       列出全部书的视野行
  python3 brain.py index                              重生成 index.md 与 index.json
  python3 brain.py check                              体检卡片、索引与关系边
  python3 brain.py eval [--k 3] [--baseline|--check]  跑检索评测（题在 evals/recall.jsonl）
  python3 brain.py add --notes P [--slug S]           从 read-a-book 笔记生成卡片骨架

扩展性原则：书涨到几百上千本，进上下文的量也不涨。
  - 路由走 references/dimensions.md 的**维度表**；维度数是人为固定的，
    所以 index.md 的大小只随维度数变化，不随书数变化。
  - 书级检索读 index.json（机器层，模型永远不看），不再逐本 parse markdown。
  - 模型永远只读 1–2 张卡。

检索是谁排出来的：四路各投一票，按名次做 RRF 融合，不手调权重。
  1) 维度路由  2) 字面（触发词／书名／别名／立场）  3) 小节级命中  4) 沿「对撞」边拉反方
每次 recall 追加一行到 .recall-log.jsonl（本地日志，不入库），供 check 找"从没被取用的卡"。

字段口径见 references/cards.md。

书库（数据）不在 skill 目录里：默认取仓库根的 library/，可用 $SECOND_BRAIN_HOME 指向别处。
分开是为了 skill 目录能单独复制/安装，不会把书库一起 fork 一份。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]


def resolve_library() -> Path:
    """书库（数据）在哪。顺序：$SECOND_BRAIN_HOME → 仓库布局的 library/ → ~/.local/share/second-brain。"""
    env = os.environ.get("SECOND_BRAIN_HOME")
    if env:
        return Path(env).expanduser()
    sibling = SKILL_DIR.parent.parent / "library"
    if sibling.is_dir():
        return sibling
    return Path.home() / ".local" / "share" / "second-brain"


LIBRARY = resolve_library()
BOOKS_DIR = LIBRARY / "books"
NOTES_DIR = LIBRARY / "notes"
INDEX = LIBRARY / "index.md"
MACHINE = LIBRARY / "index.json"
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

# index.json 的 schema 版本。加了 sections / relations / confidence 之后，
# 旧文件必须重建——只比 count 会让旧索引被当成新鲜的。
INDEX_VERSION = 2

EVAL_FILE = LIBRARY / "evals" / "recall.jsonl"
BASELINE_FILE = LIBRARY / "evals" / "baseline.json"
LOG_FILE = LIBRARY / ".recall-log.jsonl"

# RRF（倒数排名融合）的 k。多路各投一票、按名次融合，不给任何一路全局权重——
# 手调权重就是在评测集上过拟合。
RRF_K = 60

# 「与其他书」小节里承认的关系类型（受控词表）。卡片里的写法不统一，左边是可能出现的词。
REL_TYPES = ("对撞", "上游", "下游", "同体例", "自查", "相关")
REL_ALIASES = {
    "对撞": "对撞", "对立": "对撞", "冲突": "对撞", "相反": "对撞", "反向": "对撞",
    "上游": "上游", "来源": "上游", "承自": "上游", "上游加厚": "上游",
    "下游": "下游", "衍生": "下游",
    "同体例": "同体例", "同脉络": "同体例", "同向": "同体例", "呼应": "同体例",
    "互补": "同体例", "语境": "同体例", "类比": "同体例",
    "自查": "自查", "软肋": "自查",
}
# 挑反方先看对撞，再看同体例（"可互借读法"的另一面）。
REL_PRIORITY = {"对撞": 0, "上游": 1, "下游": 1, "同体例": 2, "自查": 3, "相关": 4}

# 卡片正文的小节（口径见 references/cards.md「正文六节」）。
SECTION_KEYS = (
    ("想起", "什么时候该想起它"),
    ("边界", "什么时候别用它"),
    ("命题", "核心命题"),
    ("原句", "常被引用的原句"),
    ("其他书", "与其他书"),
    ("判断", "我的判断"),
)
TITLE_RE = re.compile(r"《([^》]{2,40})》")

# 参与"小节级命中"的小节。「其他书」是关系元数据、「判断」是逐本评论，
# 拿它们匹配问题只会引入噪声（「其他书」里全是书名）。
SECTION_MATCH_KEYS = ("想起", "边界", "命题", "原句")


def die(msg: str, code: int = 2):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def no_cards_hint(prefix: str = "") -> str:
    """空书库时统一指路：找的是哪、怎么指过去。"""
    return (f"{prefix}书库 = {LIBRARY}"
            "（顺序：$SECOND_BRAIN_HOME → 兄弟目录 library/ → ~/.local/share/second-brain）。"
            "如果书库在别处，`export SECOND_BRAIN_HOME=<书库路径>`。")


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


# ---------------------------------------------------------------- 卡片正文：小节与关系边


def parse_sections(body: str) -> dict:
    """把卡片正文按 `## 小节名` 切开。只取 cards.md 定的那六节，缺的给空串。"""
    found: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    for raw in body.splitlines():
        if raw.startswith("## "):
            if cur is not None:
                found[cur] = "\n".join(buf).strip()
            cur, buf = raw[3:].strip(), []
        elif cur is not None:
            buf.append(raw.rstrip())
    if cur is not None:
        found[cur] = "\n".join(buf).strip()
    return {key: found.get(name, "") for key, name in SECTION_KEYS}


def resolve_title(ref: str, books: dict) -> str | None:
    """《书名》→ slug。卡片的 title 常带副标题（「纳瓦尔宝典：财富与幸福指南」），
    所以用互相包含来匹配，别名也参与。找不到返回 None——大概率是库外的书，不是错。"""
    r = norm(ref)
    if len(r) < 2:
        return None
    for slug, b in books.items():
        for cand in (b.get("title"), b.get("original_title")):
            c = norm(str(cand or ""))
            if c and (c.startswith(r) or r.startswith(c)):
                return slug
        for a in b.get("aliases") or []:
            c = norm(str(a))
            if c and (c == r or c.startswith(r)):
                return slug
    return None


def parse_relations(body: str, books: dict) -> list[dict]:
    """从「与其他书」小节抽类型边（零 LLM：只认字面格式）。

    卡片里的写法并不统一（`**对撞 · 《X》**`、`**与《X》**`、`**对撞｜《X》**`…），
    所以判据是"这一条里出现了哪个类型词 + 出现了哪些《书名》"。认不出类型记「相关」；
    一条里一个书名都没有（比如只写了库外作者）就整条丢掉。
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for line in parse_sections(body)["其他书"].splitlines():
        line = line.strip()
        if not line.startswith(("-", "*")):
            continue
        text = line.lstrip("-* ").strip()
        rel = "相关"
        for word in ("对撞", "对立", "冲突", "相反", "反向", "上游", "下游", "同体例",
                     "同脉络", "同向", "呼应", "互补", "自查", "软肋", "语境"):
            if word in text[:60]:
                rel = REL_ALIASES[word]
                break
        why = ""
        m = re.search(r"[：:](.+)$", text)
        if m:
            why = re.sub(r"\s+", " ", m.group(1)).strip()[:120]
        for t in TITLE_RE.findall(text):
            key = (rel, t)
            if key in seen:
                continue
            seen.add(key)
            out.append({"type": rel, "ref": t, "slug": resolve_title(t, books), "why": why})
    return out


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
            "original_title": m.get("original_title"),
            "author": m.get("author"),
            "editor": m.get("editor"),
            "lens": m.get("lens"),
            "thesis": m.get("thesis"),
            "dimensions": ds,
            "triggers": as_list(m, "triggers"),
            "domains": as_list(m, "domains"),
            "aliases": as_list(m, "aliases"),
            "source_type": m.get("source_type"),
            "source_warning": m.get("source_warning"),
            "confidence": m.get("confidence"),
            "read_at": m.get("read_at"),
            "notes": m.get("notes"),
            "card": m["_path"].name,
            "weight": weight_of(m),
            "card_tokens_est": est_tokens(m["_path"].read_text(encoding="utf-8")),
            "sections": parse_sections(m["_body"]),
        }
        for d in ds:
            inv[d].append(slug)
    # 关系边要等所有 title 都在 books 里才解析得出 slug，所以单独一遍。
    for m in cards:
        books[slug_of(m)]["relations"] = parse_relations(m["_body"], books)
    return {"version": INDEX_VERSION, "count": len(books), "dimensions": inv, "books": books}


def dump_machine(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def load_machine_index(cards: list[dict], dims: dict) -> tuple[dict, bool]:
    """读 index.json。缺失或与卡片数不一致时现场重建（不写盘），返回 (索引, 是否陈旧)。"""
    if MACHINE.exists():
        try:
            obj = json.loads(MACHINE.read_text(encoding="utf-8"))
            if obj.get("count") == len(cards) and obj.get("version") == INDEX_VERSION:
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


def score_card_topic(meta: dict, q: str, trigger_ratio: float = 0.5) -> tuple[float, list[str], int]:
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
            if ratio >= trigger_ratio:
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


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).replace("**", "")).strip()


def _boundary_line(b: dict, limit: int = 120) -> str:
    """卡片「什么时候别用它」压成一行。SKILL.md 把它叫护栏，那工具就得先把它摆出来。"""
    text = (b.get("sections") or {}).get("边界") or ""
    items = [_plain(x.lstrip("-* ")) for x in text.splitlines() if x.strip().startswith(("-", "*"))]
    joined = "；".join([x for x in items if x]) or _plain(text)
    return joined[:limit] + ("…" if len(joined) > limit else "")


def _book_block(i: int, slug: str, b: dict, ev: dict) -> str:
    title = b.get("title") or slug
    author = b.get("author") or "?"
    if b.get("editor"):
        author += f"（{b['editor']} 编）"
    lines = [f"### {i}. 《{title}》（{slug}）"]
    lines.append(f"- 作者：{author}")
    if b.get("lens"):
        lines.append(f"- 视野：{b['lens']}")
    why = []
    if ev.get("dims"):
        why.append("维度 " + "、".join(ev["dims"]))
    if ev.get("triggers"):
        why.append("字面 " + "、".join(str(t) for t in ev["triggers"][:3]))
    if ev.get("sections"):
        why.append("小节 " + "、".join(f"{k}({v:.0%})" for k, v in ev["sections"][:2]))
    if ev.get("reversed_by"):
        why.append("反方来源 " + "、".join(f"《{x['from_title']}》" for x in ev["reversed_by"]))
    if why:
        lines.append("- 命中：" + "｜".join(why))
    if b.get("confidence"):
        lines.append(f"- 置信：{_plain(b['confidence'])}")
    boundary = _boundary_line(b)
    if boundary:
        lines.append(f"- 边界（引用前先看这条）：{boundary}")
    opp = [o for o in (ev.get("opponents") or []) if o.get("slug")][:2]
    if opp:
        lines.append("- 可当反方（库内、卡片已登记）：" + "；".join(
            f"《{o['title']}》（{o['slug']}）" + (f"——{_plain(o['why'])}" if o.get("why") else "")
            for o in opp))
    lines.append(f"- 卡片：{b.get('card')}｜≈{b.get('card_tokens_est', 0)} tokens"
                 + (f"｜原笔记：{b['notes']}" if b.get("notes") else ""))
    src = _source_note(b)
    if src:
        lines.append(src.lstrip("\n"))
    return "\n".join(lines)


def _date_key(s) -> int:
    """'2026-10-05' → 20261005，用来把"读完日期近的在前"塞进升序排序。"""
    digits = re.sub(r"\D", "", str(s or ""))
    return int(digits) if len(digits) >= 8 else 0


def _fuse(arms: dict) -> list[tuple[str, float, dict]]:
    """RRF：每路按名次投一票，score = Σ 1/(K + rank)。返回 (slug, 分数, 各路名次)。
    不手调权重：调权重就是在评测集上过拟合，要改就改词表与阈值。"""
    scores: dict[str, float] = {}
    where: dict[str, dict] = {}
    for arm, ranks in arms.items():
        for slug, r in ranks.items():
            scores[slug] = scores.get(slug, 0.0) + 1.0 / (RRF_K + r)
            where.setdefault(slug, {})[arm] = r
    order = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(slug, sc, where[slug]) for slug, sc in order]


def _rank_of(scores: dict, books: dict | None = None) -> dict:
    """{slug: 分数} → {slug: 名次}（1 起）。分数不大于 0 的不进榜。
    同分按 weight 高的在前、读完日期近的在前、最后 slug——与 index.md 的代表位同一套规则。"""
    pairs = [(sc, slug) for slug, sc in scores.items() if sc > 0]
    if books is None:
        ranked = sorted(pairs, key=lambda kv: (-kv[0], kv[1]))
    else:
        ranked = sorted(pairs, key=lambda kv: (
            -kv[0], -books.get(kv[1], {}).get("weight", 0),
            -_date_key(books.get(kv[1], {}).get("read_at")), kv[1]))
    return {slug: i for i, (_, slug) in enumerate(ranked, 1)}


def section_hits(b: dict, qb: set, min_shared: int = 3, min_cover: float = 0.2) -> list[tuple[str, float]]:
    """问题落在哪几个小节上。长小节用"问题被覆盖了多少"打分，不用重合率——
    重合率在 600 字的「核心命题」上永远很低，量不出东西。"""
    out: list[tuple[str, float]] = []
    if not qb:
        return out
    for key in SECTION_MATCH_KEYS:
        text = (b.get("sections") or {}).get(key) or ""
        tb = bigrams(text) - STOP_BIGRAMS
        if len(tb) < 3:
            continue
        shared = tb & qb
        cover = len(shared) / len(qb)
        if len(shared) >= min_shared and cover >= min_cover:
            out.append((key, cover))
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


def opponents_of(slug: str, idx: dict) -> list[dict]:
    """这本书在库里、可当反方的那几本（先对撞，再同体例）。"""
    out: list[dict] = []
    for rel in idx["books"].get(slug, {}).get("relations", []):
        tgt = rel.get("slug")
        if not tgt or tgt == slug or tgt not in idx["books"]:
            continue
        if rel.get("type") not in ("对撞", "同体例"):
            continue
        out.append({"slug": tgt, "title": idx["books"][tgt].get("title") or tgt,
                    "type": rel["type"], "why": rel.get("why", ""),
                    "pri": REL_PRIORITY.get(rel["type"], 4)})
    out.sort(key=lambda o: (o["pri"], o["slug"]))
    return out


def rank_books(query: str, dims: dict, idx: dict, top: int, dim_hits=None,
               relaxed: bool = False) -> tuple[list[dict], list]:
    """四路召回 → RRF 融合。返回 (候选, 命中的维度)。

    1) dim     维度路由：问题→维度的匹配强度（同分按 weight／读完日期排，与 index.md 一致）
    2) topic   字面：触发词／书名／别名／立场
    3) section 小节级命中：问题落在「边界」「命题」「原句」哪一节
    4) edge    沿「对撞」边把反方拉进来——挑反方是这套 skill 最贵的一步，不该靠人肉记

    relaxed=True 是兜底：四路都没候到书时放宽阈值再来一遍。宁可给弱候选并标明，
    也不要让模型对判断型问题回一句「书里没有」——那是 SKILL.md 明令禁止的失败形态。
    """
    qb = bigrams(norm(query)) - STOP_BIGRAMS
    if dim_hits is None:
        dim_hits = score_dimensions(query, dims, floor=0.6 if relaxed else 1.0)
    books = idx["books"]
    sec_min, sec_cover = (2, 0.12) if relaxed else (3, 0.2)

    dim_scores: dict[str, float] = {}
    dims_of: dict[str, list[str]] = {}
    for s, name, _ in dim_hits[:4]:
        for slug in idx["dimensions"].get(name, []):
            dim_scores[slug] = dim_scores.get(slug, 0.0) + s
            dims_of.setdefault(slug, []).append(name)

    topic_scores: dict[str, float] = {}
    topic_hits: dict[str, list[str]] = {}
    for slug, b in books.items():
        sc, hits, strong = score_card_topic(b, query, trigger_ratio=0.34 if relaxed else 0.5)
        if sc > 0:
            topic_scores[slug] = sc + (2.0 if strong else 0.0)
            topic_hits[slug] = hits

    sec_scores: dict[str, float] = {}
    sec_top: dict[str, list] = {}
    for slug, b in books.items():
        hs = section_hits(b, qb, sec_min, sec_cover)
        if hs:
            sec_scores[slug] = hs[0][1]
            sec_top[slug] = hs

    arms = {"dim": _rank_of(dim_scores, books), "topic": _rank_of(topic_scores),
            "section": _rank_of(sec_scores)}

    # 反方臂：先看前三路挑出的种子，再沿边拉一跳（只拉库里的书）。
    seeds = [(slug, rank.get("dim") or rank.get("topic") or rank.get("section") or 99)
             for slug, _, rank in _fuse(arms)[:3]]
    edge_scores: dict[str, float] = {}
    edge_via: dict[str, list[dict]] = {}
    for src, srank in seeds:
        for rel in books.get(src, {}).get("relations", []):
            tgt = rel.get("slug")
            if not tgt or tgt == src or tgt not in books:
                continue
            pen = REL_PRIORITY.get(rel["type"], 4)
            edge_scores[tgt] = max(edge_scores.get(tgt, 0.0), 10.0 - pen * 2 - srank * 0.5)
            edge_via.setdefault(tgt, []).append(
                {"from": src, "from_title": books[src].get("title") or src,
                 "type": rel["type"], "why": rel.get("why", "")})
    arms["edge"] = _rank_of(edge_scores)

    out: list[dict] = []
    for slug, sc, where in _fuse(arms)[:top]:
        out.append({
            "slug": slug, "rrf": sc, "arms": where, "weak": relaxed,
            "dims": dims_of.get(slug, []),
            "triggers": topic_hits.get(slug, []),
            "sections": sec_top.get(slug, []),
            "reversed_by": edge_via.get(slug, []),
            "opponents": opponents_of(slug, idx),
        })
    if not out and not relaxed:
        return rank_books(query, dims, idx, top, dim_hits=None, relaxed=True)
    return out, dim_hits


def _log_recall(query: str, cand: list[dict]) -> None:
    """每次 recall 追加一行。日志不入库（.recall-log.jsonl），用来找"从没被取用的卡"。"""
    from datetime import datetime
    try:
        row = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
               "query": query, "top": [c["slug"] for c in cand]}
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def cmd_recall(args) -> int:
    cards = all_cards()
    if not cards:
        die(no_cards_hint("还没有卡片。先用 `brain.py add` 加一本；"))
    dims = load_dimensions()
    if not dims:
        die(f"读不到维度表 {DIM_FILE}")
    idx, stale = load_machine_index(cards, dims)

    # --all：列出全部书的视野行（小库用；书多时会截断）
    if args.all:
        print(f"# 全部视野（{len(idx['books'])} 本）\n")
        shown = list(idx["books"].items())
        if len(shown) > 40:
            print("书多于 40 本，只显示前 40 本；其余用 `--dim` 或 `--topic` 取。\n")
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
            ev = {"dims": [d for d in args.dims if slug in idx["dimensions"].get(d, [])]}
            print(_book_block(i, slug, idx["books"][slug], ev))
            print("")
        return 0

    # --topic：只用字面那一路（查事实、找原句、点名某本书时用）
    if args.topic:
        ranked = sorted((score_card_topic(m, args.query) + (m,) for m in cards),
                        key=lambda r: -r[0])
        print(f"# 话题候选（问题：{args.query}）\n")
        if not ranked or not ranked[0][2]:
            print("**字面没有对得上的书。**判断类问题请用默认的四路召回"
                  "（不带 --topic），或直接读 index.md 挑维度。\n")
        for i, (sc, hits, strong, m) in enumerate(ranked[:args.top], 1):
            mark = "强" if strong else "弱"
            slug = slug_of(m)
            print(f"### {i}. 《{m.get('title')}》（{slug}）  [{mark}] score={sc:.1f}")
            print(f"- 立场：{m.get('thesis')}")
            print(f"- 命中：{'、'.join(hits) if hits else '（无强命中，只有零散字重合）'}")
            edge = idx["books"].get(slug, {}).get("sections", {}).get("边界")
            if edge:
                print(f"- 边界（引用前先看这条）：{_boundary_line(idx['books'][slug])}")
            print("")
        return 0

    # 默认：四路召回 + RRF 融合
    cand, dim_hits = rank_books(args.query, dims, idx, args.top)

    if args.json:
        payload = {
            "query": args.query,
            "dimensions": [{"name": n, "score": round(s, 2)} for s, n, _ in dim_hits[:4]],
            "candidates": [
                {"slug": c["slug"], "rrf": round(c["rrf"], 5), "arms": c["arms"],
                 "dims": c["dims"], "triggers": c["triggers"],
                 "sections": [{"key": k, "cover": round(v, 3)} for k, v in c["sections"]],
                 "reversed_by": c["reversed_by"],
                 "opponents": [o["slug"] for o in c["opponents"]]}
                for c in cand],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        if not args.no_log:
            _log_recall(args.query, cand)
        return 0

    print(f"# 视野候选（问题：{args.query}）\n")
    if not cand:
        print("**四路都没有候到书。** 通常意味着这个问题用的说法离书库很远。可以：")
        print("- 直接读 `index.md`（按维度排），人工挑 2–4 个维度；")
        print("- 用 `--topic` 做纯字面检索；")
        print("- 或者如实告诉用户：书库里没有覆盖这个方向的视野。\n")
        print(f"可用维度：{dimension_menu(dims)}")
        if not args.no_log:
            _log_recall(args.query, [])
        return 0

    if dim_hits:
        print("命中维度：")
        for s, name, _ in dim_hits[:4]:
            print(f"- {name}（{s:.1f}）——{dims[name]['desc']}")
    else:
        print("**没有维度命中**：下面是靠字面与小节捞到的候选。判断型问题别停在这里，"
              "再人工挑 2–3 个维度。")
    arms_used = sorted({a for c in cand for a in c["arms"]})
    print(f"\n候选书（{len(cand)} 本，读 1–2 本；第 2 本优先挑能形成对撞的那本）")
    print(f"（四路：{'、'.join(arms_used)}；RRF 融合，不手调权重）\n")
    for i, c in enumerate(cand, 1):
        print(_book_block(i, c["slug"], idx["books"][c["slug"]], c))
        print("")
    if stale:
        print("（提示：index.json 与卡片不一致，已现场重建；跑 `brain.py index` 写回。）")
    if not args.no_log:
        _log_recall(args.query, cand)
    return 0


# ---------------------------------------------------------------- index / check / add


def cmd_index(args) -> int:
    cards = all_cards()
    if not cards:
        die(no_cards_hint())
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
    if not cards:
        print(f"✗ 书库里一本卡片都没有——{no_cards_hint()}")
    idx_now = build_machine_index(cards, dims)
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
            if not (np if np.is_absolute() else LIBRARY / np).exists():
                warns.append(f"{name}: 找不到原笔记 {notes}（路径不对，检查 notes: 字段）")
        secs = parse_sections(m["_body"])
        if not secs["边界"].strip():
            problems.append(f"{name}: 缺「什么时候别用它」——cards.md 说这一节必须有")
        for key, label in (("命题", "核心命题"), ("原句", "常被引用的原句")):
            if not secs[key].strip():
                warns.append(f"{name}: 缺「{label}」小节，只能靠 frontmatter 回答")

    # 关系边：只有库内的书才解析得出 slug，解析不出的多半是库外引用，不算错。
    out_edges: dict[tuple[str, str], str] = {}
    for slug, b in idx_now["books"].items():
        rels = b.get("relations") or []
        if not rels:
            warns.append(f"{slug}.md: 「与其他书」里没有库内的书——孤立卡片，反方臂取不到它")
        for rel in rels:
            if rel.get("type") not in REL_TYPES:
                problems.append(f"{slug}.md: 关系类型「{rel.get('type')}」不在词表里"
                                f"（{'、'.join(REL_TYPES)}）")
            if rel.get("slug"):
                out_edges[(slug, rel["slug"])] = rel.get("type")
    one_way = [f"{a}→{other}" for (a, other), t in sorted(out_edges.items())
               if t == "对撞" and (other, a) not in out_edges]
    if one_way:
        warns.append(f"{len(one_way)} 组「对撞」只是单边写的（{('、'.join(one_way[:4]))}"
                     f"{'…' if len(one_way) > 4 else ''}）——反方臂是双向走的，"
                     f"单边会让「被对撞」的那本吃不到这条边")

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
        if MACHINE.read_text(encoding="utf-8") != dump_machine(idx_now):
            problems.append("index.json 与卡片不一致——跑 brain.py index")
    else:
        problems.append("index.json 不存在——跑 brain.py index")

    # 取用情况：日志攒够样本后，报"从没进过候选"的卡（rsi-reading 的「死卡」口径）。
    if LOG_FILE.exists():
        try:
            rows = [json.loads(x) for x in LOG_FILE.read_text(encoding="utf-8").splitlines() if x.strip()]
        except (json.JSONDecodeError, OSError):
            rows = []
        if len(rows) >= 15:
            hit = {s for r in rows for s in (r.get("top") or [])}
            dead = sorted(set(idx_now["books"]) - hit)
            if dead:
                warns.append(f"近 {len(rows)} 次 recall 里，{len(dead)} 本从没进过候选："
                             f"{'、'.join(dead[:8])}{'…' if len(dead) > 8 else ''}")

    for x in problems:
        print(f"✗ {x}")
    for x in warns:
        print(f"! {x}")
    print(f"\n{len(cards)} 本卡片，{len(problems)} 个问题"
          if problems else f"\n{len(cards)} 本卡片，全部通过")
    if warns:
        print(f"（另有 {len(warns)} 条提醒，不影响使用）")
    return 1 if problems else 0


# ---------------------------------------------------------------- 检索评测


EVAL_CAVEAT = (
    "这个数只回答「候选里有没有该出现的书」，不回答答案好不好。gold 是人读完卡片后写下的；"
    "其中 vocab 家族的题面有相当一部分取自卡片 triggers，所以整体分偏高，看 paraphrase 家族更接近真实。"
    "题量不大，一道题就值好几个百分点——别在小数点上做文章，只看「改词表前后同一套题有没有变好」。"
    "标了 tuned 的题，是因为它的问法后来被补进了 dimensions.md——这些题只证明词表补对了，"
    "不证明泛化；看 holdout 那一行才知道换一种说法还灵不灵。"
)


def load_eval_cases() -> list[dict]:
    """读 evals/recall.jsonl。一题一行：q / gold / accept / family / kind。"""
    if not EVAL_FILE.exists():
        return []
    out: list[dict] = []
    for i, line in enumerate(EVAL_FILE.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            die(f"{EVAL_FILE} 第 {i} 行不是合法 JSON：{exc}")
        if not row.get("q") or not (row.get("gold") or row.get("accept")):
            die(f"{EVAL_FILE} 第 {i} 行缺 q 或 gold")
        row.setdefault("family", "vocab")
        row.setdefault("kind", "判断")
        row.setdefault("id", f"q{i:02d}")
        out.append(row)
    return out


def _eval_rows(cases: list[dict], dims: dict, idx: dict, k: int) -> list[dict]:
    rows: list[dict] = []
    for c in cases:
        gold = set(c.get("gold") or [])
        ok = gold | set(c.get("accept") or [])
        cand, dim_hits = rank_books(c["q"], dims, idx, top=k)
        got = [x["slug"] for x in cand]
        hit = [s for s in got if s in ok]
        rr = 0.0
        for i, s in enumerate(got, 1):
            if s in ok:
                rr = 1.0 / i
                break
        gold_dims: set[str] = set()
        for g in ok:
            gold_dims |= set(idx["books"].get(g, {}).get("dimensions", []))
        picked = {n for _, n, _ in dim_hits[:4]}
        rows.append({"id": c["id"], "family": c["family"], "kind": c["kind"], "q": c["q"],
                     "tuned": bool(c.get("tuned")),
                     "gold": sorted(gold), "ok": sorted(ok), "got": got, "hit": hit, "rr": rr,
                     "dim_ok": bool(gold_dims & picked)})
    return rows


def _eval_summary(rows: list[dict], k: int) -> dict:
    n = len(rows)
    hits = sum(len(r["hit"]) for r in rows)
    golds = sum(len(r["ok"]) for r in rows)
    return {
        "cases": n, "k": k,
        "p_at_k": round(hits / (n * k), 4) if n and k else 0.0,
        "r_at_k": round(hits / golds, 4) if golds else 0.0,
        "mrr": round(sum(r["rr"] for r in rows) / n, 4) if n else 0.0,
        "dim_route_rate": round(sum(1 for r in rows if r["dim_ok"]) / n, 4) if n else 0.0,
    }


def cmd_eval(args) -> int:
    cases = load_eval_cases()
    if not cases:
        die(f"没有评测题。建 {EVAL_FILE}：一题一行 JSON，至少要有 q 与 gold。")
    dims = load_dimensions()
    if not dims:
        die(f"读不到维度表 {DIM_FILE}")
    idx, _ = load_machine_index(all_cards(), dims)
    k = max(1, args.k)

    rows = _eval_rows(cases, dims, idx, k)
    overall = _eval_summary(rows, k)
    fams = {fam: _eval_summary([r for r in rows if r["family"] == fam], k)
            for fam in sorted({r["family"] for r in rows})}
    # 补过问法的题（tuned）只能证明词表补对了，不能证明泛化；这批单独算一份。
    holdout = _eval_summary([r for r in rows if not r["tuned"]], k)
    misses = [r["id"] for r in rows if not r["hit"]]
    result = {"k": k, "overall": overall, "holdout": holdout, "by_family": fams,
              "misses": misses, "caveat": EVAL_CAVEAT}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"# 检索评测（{overall['cases']} 题，k={k}）\n")
        print(f"整体　P@{k}={overall['p_at_k']:.1%}　R@{k}={overall['r_at_k']:.1%}　"
              f"MRR={overall['mrr']:.3f}　维度命中率={overall['dim_route_rate']:.1%}")
        if holdout["cases"]:
            print(f"未调参　n={holdout['cases']}　P@{k}={holdout['p_at_k']:.1%}　"
                  f"R@{k}={holdout['r_at_k']:.1%}　MRR={holdout['mrr']:.3f}　"
                  f"维度命中率={holdout['dim_route_rate']:.1%}　← 泛化看这一行")
        for fam, m in fams.items():
            print(f"  {fam:<10} n={m['cases']:<3} P@{k}={m['p_at_k']:.1%}　"
                  f"R@{k}={m['r_at_k']:.1%}　MRR={m['mrr']:.3f}")
        if misses:
            print(f"\n没命中（{len(misses)} 题）：{'、'.join(misses)}")
        print(f"\n口径：{EVAL_CAVEAT}")

    if getattr(args, "baseline", False):
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8")
        print(f"\n基线已写入 {BASELINE_FILE}")
        return 0

    if getattr(args, "check", False):
        if not BASELINE_FILE.exists():
            die(f"还没有基线（{BASELINE_FILE}）。先跑一次 --baseline。")
        saved = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
        base = saved.get("overall", {})
        drops = []
        # 两份都比：overall 防倒退，holdout 防"只把题面的说法抄进词表"。
        for label, cur, old in (("整体", overall, base),
                                ("未调参", holdout, saved.get("holdout", {}))):
            for key in ("mrr", "p_at_k", "r_at_k"):
                if not old or key not in old:
                    continue
                delta = float(old[key]) - cur[key]
                if delta > 0.05:
                    drops.append(f"{label} {key} {old[key]} → {cur[key]}（跌 {delta:.3f}）")
        if drops:
            print("\n✗ 检索质量回退：" + "；".join(drops), file=sys.stderr)
            return 1
        print(f"\n✓ 没回退（基线 MRR={base.get('mrr')}，现在 {overall['mrr']}）")
    return 0


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
    notes_dir = NOTES_DIR
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

    p = sub.add_parser("recall", help="四路召回 + RRF 融合（默认）")
    p.add_argument("query", nargs="?", default=None, help="问题原话")
    p.add_argument("--top", type=int, default=6)
    p.add_argument("--json", action="store_true")
    p.add_argument("--dim", dest="dims", action="append", default=None,
                   help="直接取某维度下的书，可重复")
    p.add_argument("--topic", action="store_true", help="改用旧的按话题字面打分")
    p.add_argument("--all", action="store_true", help="列出全部书的视野行")
    p.add_argument("--no-log", action="store_true", help="不写 .recall-log.jsonl")
    p.set_defaults(fn=cmd_recall)

    p = sub.add_parser("index", help="重生成 index.md 与 index.json")
    p.add_argument("--check", action="store_true", help="只比对，不写")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("check", help="体检卡片与索引")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("eval", help="跑检索评测（题在 evals/recall.jsonl）")
    p.add_argument("--k", type=int, default=3, help="看前 k 个候选，默认 3")
    p.add_argument("--json", action="store_true")
    p.add_argument("--baseline", action="store_true", help="把本次结果写成基线")
    p.add_argument("--check", action="store_true", help="与基线比，回退就退出码 1")
    p.set_defaults(fn=cmd_eval)

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
