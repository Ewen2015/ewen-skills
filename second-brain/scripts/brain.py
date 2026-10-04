#!/usr/bin/env python3
"""第二大脑的检索与体检。只做确定性的事：找书、建索引、查卡片。

判断书里说了什么、该怎么用，是模型的事，这个脚本不碰。

用法：
  python3 brain.py recall "问题" [--top 3] [--json]   按问题给候选书打分排序
  python3 brain.py index [--check]                    用卡片 frontmatter 重生成 index.md
  python3 brain.py check                              体检：字段、slug、索引同步、笔记路径
  python3 brain.py add --notes P [--slug S]           从 read-a-book 笔记生成卡片骨架

设计目标只有一个：**别把整个书库塞进上下文**。recall 只返回候选和命中理由，
让模型去读那一两张卡，而不是把 books/ 全读一遍。

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

REQUIRED = ("slug", "title", "author", "source_type", "read_at",
            "domains", "thesis", "triggers")
LIST_FIELDS = ("domains", "triggers", "aliases")

# 命中权重：触发词是作者/提炼者特意写下的检索入口，权重最高；
# 领域词宽泛，只作辅助。整句命中比零散字重合可信得多。
W_TRIGGER = 6.0
W_DOMAIN = 2.5
W_TITLE = 9.0
W_ALIAS = 7.0
W_THEAD = 2.0
W_BIGRAM = 1.5


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
    """`埃里克·乔根森（Eric Jorgenson）` → `埃里克·乔根森`。索引里不重复外文名。"""
    return re.split(r"[（(]", str(s).strip())[0].strip()


def summary_line(meta: dict) -> str:
    """index.md 里每本书压成 4 行，这是常读文件，必须小。"""
    slug = meta.get("slug") or meta["_path"].stem
    domains = "·".join(as_list(meta, "domains")[:6])
    parts = [meta.get("author") or "?"]
    editor, translator = meta.get("editor"), meta.get("translator")
    if editor and short_name(editor) != short_name(meta.get("author") or ""):
        parts.append(f"编 {short_name(editor)}")
    if translator:
        parts.append(f"译 {short_name(translator)}")
    line1 = f"《{meta.get('title', '?')}》｜" + "｜".join(parts)
    if domains:
        line1 += f"｜{domains}"
    source = short_name(str(meta.get("source_type") or ""))
    if source:
        line1 += f"｜{source}"
    thesis = (meta.get("thesis") or "").strip()
    trig = " · ".join(as_list(meta, "triggers")[:12])
    out = [f"## {slug}", line1]
    if thesis:
        out.append(thesis)
    if trig:
        out.append(f"问：{trig}")
    return "\n".join(out)


def render_index(cards: list[dict]) -> str:
    head = """# 书库索引

**这个文件是生成的**，别手改——改 `books/<slug>.md` 的 frontmatter，然后跑
`python3 scripts/brain.py index`。

每本 4 行，是唯一常读的文件：先看这里挑书，再去读那一两张卡。
`thesis` 是这本书的立场（可反驳的那种），`问` 下面是它的检索入口。
"""
    blocks = [summary_line(m) for m in cards]
    return head + "\n" + "\n\n".join(blocks) + "\n"


def est_tokens(text: str) -> int:
    """粗估：中文约 1.5 字/token，混排取 1.6 作整体除数。只用来说明量级。"""
    return max(1, round(len(text) / 1.6))


# 这些二字组合几乎出现在任何中文句子里，留着会让"晚饭吃什么"也匹配上书。
STOP_BIGRAMS = {
    "什么", "时候", "自己", "还是", "一个", "我们", "他们", "可以", "因为", "所以",
    "但是", "如果", "这样", "那样", "怎么", "为什", "这个", "那个", "我的", "你的",
    "他的", "不是", "就是", "没有", "觉得", "应该", "到底", "其实", "现在", "已经",
    "问题", "事情", "东西", "地方", "知道", "想要", "需要", "可能", "一直", "有些",
}


def score_card(meta: dict, q: str) -> tuple[float, list[str], int]:
    """返回 (分数, 命中理由, 强命中数)。

    中文没法靠空格分词，所以走两条路：**整句包含**（trigger 原样出现在问题里）
    和**字面近似**（trigger 的二字组有一半以上落在问题里）。后者能接住
    "辞职"↔"离职"、"做自己的产品"↔"独立开发"这类换词——但仍然接不住
    完全不同的说法，那要靠把 trigger 写全（见 references/cards.md）。
    """
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


def cmd_recall(args) -> int:
    cards = all_cards()
    if not cards:
        die(f"{BOOKS_DIR} 里还没有卡片。先用 brain.py add 加一本。")
    ranked = []
    for m in cards:
        sc, hits, strong = score_card(m, args.query)
        ranked.append((sc, hits, strong, m))
    ranked.sort(key=lambda r: -r[0])

    if args.json:
        print(json.dumps([{
            "slug": m.get("slug") or m["_path"].stem,
            "title": m.get("title"), "author": m.get("author"),
            "score": round(sc, 1), "strong": strong, "hits": hits,
            "card": str(m["_path"]),
            "card_tokens_est": est_tokens(m["_path"].read_text(encoding="utf-8")),
            "notes": m.get("notes"),
            "source_type": m.get("source_type"),
        } for sc, hits, strong, m in ranked[:args.top]], ensure_ascii=False, indent=1))
        return 0

    top = ranked[:args.top]
    if not top or not top[0][2]:
        print(f"# 候选（问题：{args.query}）")
        print("")
        print("**没有明显对得上的书。**先如实说这句，不要硬凑一本上来——"
              "没有书能回答也是答案。")
        print("")
    else:
        print(f"# 候选（问题：{args.query}）")
        print("")
    for i, (sc, hits, strong, m) in enumerate(top, 1):
        slug = m.get("slug") or m["_path"].stem
        card_tok = est_tokens(m["_path"].read_text(encoding="utf-8"))
        mark = "强" if strong else "弱"
        print(f"## {i}. {m.get('title')}（{slug}）  [{mark}] score={sc:.1f}")
        print(f"- 作者：{m.get('author')}"
              + (f"（{m.get('editor')} 编）" if m.get("editor") else ""))
        print(f"- 立场：{m.get('thesis')}")
        print(f"- 命中：{'、'.join(hits) if hits else '（无强命中，只有零散字重合）'}")
        print(f"- 读它要花：≈{card_tok} tokens｜卡：{m['_path'].name}"
              + (f"｜原笔记：{m.get('notes')}" if m.get("notes") else ""))
        if m.get("source_type") and m["source_type"] != "一手":
            print(f"- ⚠️ 来源：{m['source_type']}"
                  + (f"——{m['source_warning']}" if m.get("source_warning") else ""))
        print("")
    if top and top[0][2]:
        print("加载建议：读第 1 名；第 2 名只在它能和第 1 名形成对照或冲突时读。"
              "第 3 名以后除非用户点名，否则不要读。")
        print("弱匹配（[弱]）的一律先不读——读它只会把不相干的话塞进回答里。")
    return 0


def cmd_index(args) -> int:
    cards = all_cards()
    if not cards:
        die("books/ 里没有卡片")
    rendered = render_index(cards)
    if args.check:
        current = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
        if current == rendered:
            print(f"index.md 与卡片一致（{len(cards)} 本）")
            return 0
        print("index.md 与卡片不一致，跑 `brain.py index` 重生成", file=sys.stderr)
        return 1
    INDEX.write_text(rendered, encoding="utf-8")
    print(f"已重写 {INDEX}（{len(cards)} 本，≈{est_tokens(rendered)} tokens）")
    return 0


def cmd_check(_args) -> int:
    cards = all_cards()
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
        notes = m.get("notes")
        if notes:
            np = Path(str(notes)).expanduser()
            if not (np if np.is_absolute() else SKILL_DIR / np).exists():
                # 原笔记在 .gitignore 里，换台机器就是没有——这是预期，只提醒。
                warns.append(f"{name}: 找不到原笔记 {notes}（本地笔记未入库，正常）")

    if INDEX.exists():
        if INDEX.read_text(encoding="utf-8") != render_index(cards):
            problems.append("index.md 与卡片不一致——跑 brain.py index")
    else:
        problems.append("index.md 不存在——跑 brain.py index")

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
    # 原笔记收进 skill 自己的 notes/，docs/ 只放 repo 级别的东西。
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
triggers: []
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
    print("接下来要手填：author / source_type / domains / triggers / 六节正文，"
          "然后把「待处理」整段删掉。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="第二大脑：检索、索引、体检")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("recall", help="按问题给候选书打分排序")
    p.add_argument("query")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_recall)

    p = sub.add_parser("index", help="用卡片 frontmatter 重生成 index.md")
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
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
