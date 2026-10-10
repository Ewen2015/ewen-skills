#!/usr/bin/env python3
"""rsi-reading 的观测仪：把「读书」这条流水线扫成一份可回查的体检报告。

只读，不写任何东西。每个数字都能追到具体文件。

用法：
  python3 rsi.py report                    # 完整体检（默认）
  python3 rsi.py coverage [--json]         # 每本书在闭环上走到哪一步
  python3 rsi.py posts [--json]            # 发布产物与平台数据的对账
  python3 rsi.py backlog                   # 改进项队列的年龄与状态

路径默认值：
  书库  ~/Documents/GitHub/reading-pkm/library
  发布  ~/Documents/rednote            （或 $XHS_WORKSPACE）
  另加  ~/Documents/*/xhs-post 这些散落的历史产物目录
用 --brain / --workspace / --post-root 覆盖。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

HOME = Path.home()
SKILL_DIR = Path(__file__).resolve().parents[1]


def _default_brain() -> Path:
    """书库在哪：$SECOND_BRAIN_HOME → 仓库布局的 library/ → ~/.local/share/second-brain。
    与 second-brain/scripts/brain.py 的 resolve_library() 同一套口径——那边是唯一权威实现。"""
    env = os.environ.get("SECOND_BRAIN_HOME")
    if env:
        return Path(env).expanduser()
    sibling = SKILL_DIR.parent.parent / "library"
    if sibling.is_dir():
        return sibling
    return HOME / ".local" / "share" / "second-brain"


DEFAULT_BRAIN = _default_brain()
DEFAULT_WORKSPACE = Path(os.environ.get("XHS_WORKSPACE") or (HOME / "Documents/rednote"))
EXTRA_POST_GLOB = "Documents/*/xhs-post"

STAGES = ("read", "note", "card", "post", "published")


# ---------- 解析小工具 ----------

def parse_frontmatter(path: Path) -> dict:
    """只认一个很小的 YAML 子集：key: 值、key: [a, b]、key:\\n  - a。"""
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    key = None
    for raw in text[3:end].splitlines():
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
        key, val = key.strip(), val.strip()
        if not val:
            meta[key] = []
        elif val.startswith("[") and val.endswith("]"):
            meta[key] = [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
        else:
            meta[key] = val.strip("'\"")
    return meta


def read_text(path: Path, limit: int | None = None) -> str:
    try:
        t = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    return t[:limit] if limit else t


def parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def as_list(v) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v).strip()]


# ---------- 采集 ----------

def load_books(brain: Path) -> list[dict]:
    books = []
    notes_dir = brain / "notes"
    for card in sorted((brain / "books").glob("*.md")):
        meta = parse_frontmatter(card)
        slug = meta.get("slug") or card.stem
        note_rel = meta.get("notes") or f"notes/{slug}.md"
        note_path = brain / str(note_rel)
        if not note_path.exists():
            alt = notes_dir / f"{slug}.md"
            note_path = alt if alt.exists() else note_path
        books.append({
            "slug": slug,
            "title": meta.get("title") or slug,
            "aliases": as_list(meta.get("aliases")),
            "author": meta.get("author") or "",
            "read_at": parse_dt(meta.get("read_at") or ""),
            "card": card,
            "note": note_path,
            "has_note": note_path.exists(),
            "triggers": len(as_list(meta.get("triggers"))),
            "source_type": meta.get("source_type") or "",
            "thesis": (meta.get("thesis") or "").strip(),
        })
    # 有笔记但没卡片的书
    known = {b["slug"] for b in books}
    for note in sorted(notes_dir.glob("*.md")):
        if note.stem not in known:
            books.append({
                "slug": note.stem, "title": note.stem, "aliases": [], "author": "",
                "read_at": None, "card": None, "note": note, "has_note": True,
                "triggers": 0, "source_type": "", "thesis": "",
            })
    return books


def discover_posts(roots: list[Path]) -> list[dict]:
    posts = []
    for root in roots:
        if not root.is_dir():
            continue
        # 既支持 <root>/<post-dir>/，也支持 root 自身就是一个 post-dir
        candidates = [root] if (root / "manifest.json").exists() else []
        candidates += [d for d in sorted(root.iterdir()) if d.is_dir()]
        for d in candidates:
            title_f = d / "title.txt"
            body_f = d / "body.txt"
            if not (title_f.exists() or body_f.exists()):
                continue
            manifest = d / "manifest.json"
            man = {}
            if manifest.exists():
                try:
                    man = json.loads(manifest.read_text(encoding="utf-8"))
                except Exception:
                    man = {}
            posts.append({
                "dir": d,
                "title": read_text(title_f).strip(),
                "body_len": len(read_text(body_f).strip()),
                "cards": len(man.get("cards") or []),
                "has_manifest": manifest.exists(),
                "blob": (read_text(title_f) + read_text(body_f, 4000) + str(d)),
                "mtime": datetime.fromtimestamp(d.stat().st_mtime),
            })
    return posts


def load_platform(workspace: Path) -> dict:
    state_f = workspace / "state/state.json"
    queue_f = workspace / "state/queue.json"
    plan_f = workspace / "plan.json"
    state, queue, plan = {}, {}, {}
    for path, dest in ((state_f, "state"), (queue_f, "queue"), (plan_f, "plan")):
        if path.exists():
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                obj = {}
            if dest == "state":
                state = obj
            elif dest == "queue":
                queue = obj
            else:
                plan = obj
    scheduled = (state.get("queue") or {}).get("scheduled") or (queue.get("queue") or {}).get("scheduled") or queue.get("scheduled") or []
    published = ((state.get("history") or {}).get("published")) or []
    topics_f = workspace / "topics.md"
    topics = read_text(topics_f)
    open_topics = [l for l in topics.splitlines() if l.strip().startswith("- [ ]")]
    used_topics = [l for l in topics.splitlines() if l.strip().startswith("- [x]")]
    return {
        "workspace": workspace,
        "plan": plan,
        "scheduled": scheduled,
        "published": published,
        "drafts": ((state.get("drafts") or {}).get("items")) or [],
        "open_topics": open_topics,
        "used_topics": used_topics,
        "scanned_at": state.get("scanned_at") or queue.get("scanned_at") or "",
    }


# ---------- 匹配 ----------

def match_posts_to_books(books: list[dict], posts: list[dict]) -> None:
    """给每本书找它对应的发布产物。启发式：长词优先，命中即记，报告里标明是启发式。"""
    for b in books:
        b["post"] = None
        b["match_term"] = None
    for p in posts:
        best = None
        for b in books:
            terms = [b["title"]] + [a for a in b["aliases"] if len(a) >= 2] + [b["slug"]]
            for t in terms:
                t = t.strip()
                if len(t) < 2:
                    continue
                if t in p["blob"]:
                    if best is None or len(t) > len(best[1]):
                        best = (b, t)
        p["book_slug"] = best[0]["slug"] if best else None
        p["book_term"] = best[1] if best else None
        if best and best[0]["post"] is None:
            best[0]["post"] = p


def match_platform(books: list[dict], posts: list[dict], platform: dict) -> None:
    sched_titles = {s.get("title", ""): s.get("time", "") for s in platform["scheduled"]}
    pub_titles = {p.get("title", ""): p for p in platform["published"]}
    for p in posts:
        t = p["title"]
        p["scheduled_at"] = parse_dt(sched_titles.get(t, "") or "")
        rec = pub_titles.get(t)
        p["published_at"] = parse_dt(rec.get("time", "")) if rec else None
        p["stats"] = rec or None
    for b in books:
        p = b.get("post")
        b["published_at"] = (p or {}).get("published_at")
        b["scheduled_at"] = (p or {}).get("scheduled_at")


# ---------- 报告 ----------

def fmt_dt(d) -> str:
    return d.strftime("%Y-%m-%d") if d else "—"


def engagement(rec: dict) -> float:
    reads = rec.get("reads") or 0
    if not reads:
        return 0.0
    return (rec.get("likes", 0) + rec.get("collects", 0) + rec.get("shares", 0)) / reads


def cmd_coverage(args) -> int:
    books = load_books(Path(args.brain).expanduser())
    posts = discover_posts(post_roots(args))
    match_posts_to_books(books, posts)
    platform = load_platform(Path(args.workspace).expanduser())
    match_platform(books, posts, platform)

    rows = []
    for b in books:
        stages = {
            "read": b["read_at"] is not None,
            "note": b["has_note"],
            "card": b["card"] is not None,
            "post": b.get("post") is not None,
            "published": bool(b.get("published_at") or b.get("scheduled_at")),
        }
        rows.append({"book": b, "stages": stages})

    if args.json:
        print(json.dumps([{
            "slug": r["book"]["slug"], "title": r["book"]["title"],
            **r["stages"],
            "read_at": fmt_dt(r["book"]["read_at"]),
            "post_dir": str(r["book"]["post"]["dir"]) if r["book"].get("post") else None,
        } for r in rows], ensure_ascii=False, indent=2))
        return 0

    print("# 闭环覆盖\n")
    head = "| 书 | 读 | 笔记 | 卡片 | 成品 | 发布 |"
    print(head)
    print("| --- | --- | --- | --- | --- | --- |")
    for r in rows:
        b, s = r["book"], r["stages"]
        mark = lambda k: "✅" if s[k] else "·"
        print(f"| {b['title']} | {mark('read')} | {mark('note')} | {mark('card')} | {mark('post')} | {mark('published')} |")

    print("\n## 断点\n")
    broken = False
    for r in rows:
        b, s = r["book"], r["stages"]
        gaps = []
        if s["read"] and not s["note"]:
            gaps.append("读了但没笔记")
        if s["note"] and not s["card"]:
            gaps.append("有笔记但没卡片（检索不到）")
        if s["card"] and not s["post"]:
            gaps.append("有卡片但没做过成品")
        if s["post"] and not s["published"]:
            gaps.append("有成品但没排期/发布")
        if gaps:
            broken = True
            print(f"- **{b['title']}**：" + "；".join(gaps))
    if not broken:
        print("- 无")

    print("\n## 孤儿产物（有成品，但认不出是哪本书）\n")
    orphans = [p for p in posts if not p.get("book_slug")]
    if orphans:
        for p in orphans:
            print(f"- `{p['dir']}`：{p['title'] or '(无标题)'}")
    else:
        print("- 无")
    return 0


def cmd_posts(args) -> int:
    posts = discover_posts(post_roots(args))
    platform = load_platform(Path(args.workspace).expanduser())
    match_posts_to_books(load_books(Path(args.brain).expanduser()), posts)
    match_platform([], posts, platform)

    if args.json:
        print(json.dumps([{
            "dir": str(p["dir"]), "title": p["title"], "book": p.get("book_slug"),
            "cards": p["cards"], "body_len": p["body_len"],
            "scheduled_at": p.get("scheduled_at").isoformat() if p.get("scheduled_at") else None,
            "published_at": p.get("published_at").isoformat() if p.get("published_at") else None,
            "stats": p.get("stats"),
        } for p in posts], ensure_ascii=False, indent=2))
        return 0

    print("# 成品与平台对账\n")
    if not posts:
        print("没有找到成品目录。")
        return 0
    print("| 成品 | 书 | 卡片数 | 正文 | 排期 | 已发 | 阅读 | 赞 | 藏 | 互动率 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for p in posts:
        s = p.get("stats") or {}
        print(f"| {p['title'] or p['dir'].name} | {p.get('book_slug') or '?'} | {p['cards']} | "
              f"{p['body_len']} | {fmt_dt(p.get('scheduled_at'))} | {fmt_dt(p.get('published_at'))} | "
              f"{s.get('reads','—')} | {s.get('likes','—')} | {s.get('collects','—')} | "
              f"{engagement(s)*100:.1f}% |" if s else
              f"| {p['title'] or p['dir'].name} | {p.get('book_slug') or '?'} | {p['cards']} | "
              f"{p['body_len']} | {fmt_dt(p.get('scheduled_at'))} | {fmt_dt(p.get('published_at'))} | — | — | — | — |")

    hist = platform["published"]
    if hist:
        print("\n## 历史发布表现（近 %d 条）\n" % min(len(hist), 10))
        for rec in hist[:10]:
            print(f"- {rec.get('time','?')}｜{rec.get('title','?')}｜阅读 {rec.get('reads',0)}"
                  f"｜赞 {rec.get('likes',0)}｜藏 {rec.get('collects',0)}｜转 {rec.get('shares',0)}"
                  f"｜互动率 {engagement(rec)*100:.1f}%")
    return 0


def cmd_backlog(args) -> int:
    path = Path(args.backlog).expanduser()
    if not path.exists():
        print(f"找不到 backlog：{path}")
        return 2
    text = path.read_text(encoding="utf-8")
    items = re.findall(r"^##\s+(R\d+)\s*[·|]\s*(.+?)\s*$", text, re.M)
    if not items:
        print("backlog 里没解析到条目（约定形如 `## R1 · 标题`）。")
        return 0
    today = date.today()
    print(f"# 改进项队列（{today}）\n")
    print("| ID | 改进项 | 状态 | 记录日期 |")
    print("| --- | --- | --- | --- |")
    missing = []
    for rid, title in items:
        block = text.split(f"## {rid}", 1)[1].split("\n## ", 1)[0]
        m_status = re.search(r"状态[：:]\s*(.+?)\s*$", block, re.M)
        # 日期只认 `记录：` 那一行。退而求其次用块里第一个日期是危险的：
        # 证据正文里的日期（如 `posts/wuqiong-2026-10-21`）会被当成记录日期，
        # 报出一个负数年龄——R63 的条目就撞过这个坑。
        m_date = re.search(r"记录[：:]\s*(\d{4}-\d{2}-\d{2})", block)
        status = m_status.group(1) if m_status else "?"
        d = m_date.group(1) if m_date else "—"
        if not m_status or not m_date:
            missing.append(f"{rid}（缺{'、'.join([x for x, ok in (('状态', m_status), ('记录', m_date)) if not ok])}）")
        age = ""
        if m_date:
            try:
                age = f"（{(today - date.fromisoformat(d)).days} 天）"
            except ValueError:
                age = ""
        print(f"| {rid} | {title} | {status} | {d}{age} |")
    if missing:
        print(f"\n> ⚠️ 有 {len(missing)} 条读不出状态或记录日期，上面的表**不完整**，"
              f"先按 backlog 的约定补 `状态：` / `记录：` 两行：{'、'.join(missing)}")
    return 0


def post_roots(args) -> list[Path]:
    ws = Path(args.workspace).expanduser()
    roots = [ws]
    # `posts/` 是 plan-schema.md 写的成品目录（R63）；`published/` 是更早的落点，保留兼容。
    # 两个都扫，别再让报表少算成品。
    roots += [ws / "posts", ws / "published"]
    if args.post_root:
        roots += [Path(p).expanduser() for p in args.post_root]
    else:
        roots += sorted(HOME.glob(EXTRA_POST_GLOB))
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _sub(args, **over):
    d = {k: v for k, v in vars(args).items() if k != "fn"}
    d.update(over)
    return argparse.Namespace(**d)


def cmd_report(args) -> int:
    print("=" * 62)
    print("读书流水线体检")
    print("=" * 62)
    cmd_coverage(_sub(args, json=False))
    print()
    print("-" * 62)
    cmd_posts(_sub(args, json=False))
    print()
    print("-" * 62)
    cmd_backlog(_sub(args))
    print()
    print("=" * 62)
    print("没埋点的环节（报告里查不到，别假装有数）：")
    print("- 检索命中：second-brain 没记 recall 日志，卡片是否被用到无从得知")
    print("- 阅读耗时：笔记里只有日期，没有从开始读到出笔记的时长")
    print("- 找书耗时：选书到拿到电子书这一步没有任何记录")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="rsi-reading 观测仪（只读）")
    ap.add_argument("--brain", default=str(DEFAULT_BRAIN))
    ap.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    ap.add_argument("--post-root", action="append", help="额外的成品根目录，可重复")
    ap.add_argument("--backlog", default=str(Path(__file__).resolve().parents[1] / "references/backlog.md"))
    sub = ap.add_subparsers(dest="cmd")
    for name, fn in (("report", cmd_report), ("coverage", cmd_coverage),
                     ("posts", cmd_posts), ("backlog", cmd_backlog)):
        p = sub.add_parser(name, help=fn.__doc__ or name)
        p.add_argument("--json", action="store_true")
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    if not getattr(args, "fn", None):
        args.fn = cmd_report
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
