#!/usr/bin/env python3
"""只读地读取小红书创作者中心状态，供排期与库存体检使用。

扫描四类事实（都通过 rednote-post 用的同一个浏览器桥接）：
  queue    未来定时发布队列（note-manager 全部 tab 的 .note-card__schedule），
           并标注哪些还卡在审核中
  drafts   草稿箱（发布页 .draft-title 抽屉，按 视频/图文/长文/播客 分类）
  history  已发布笔记的发布时间 + 五项数据（note-manager 已发布 tab）
  all      以上三项

这里不点任何会改变的按钮：只切 tab、开抽屉、滚动。发布动作仍然归 rednote-post。

用法：
  python3 xhs_state.py queue   [--max 40] [--out state/queue.json]
  python3 xhs_state.py drafts  [--out state/drafts.json]
  python3 xhs_state.py history [--max 60] [--out state/history.json]
  python3 xhs_state.py all     [--out state/state.json]

输出为 JSON（stdout 或 --out）。字段见 references/plan-schema.md。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SKILLS_DIR = Path(os.environ.get("XHS_SKILLS_DIR", "/tmp/xhs-skills-repo"))
BRIDGE_URL = os.environ.get("XHS_BRIDGE_URL", "ws://localhost:9333")
NOTE_MANAGER_URL = "https://creator.xiaohongshu.com/new/note-manager"
PUBLISH_URL = ("https://creator.xiaohongshu.com/publish/publish"
               "?source=official&target=image")

# 平台在卡片上的固定顺序；用错顺序会把点赞当阅读量。
STAT_ORDER = ["reads", "comments", "likes", "collects", "shares"]

# 卡片解析：noteId 藏在 data-impression 的 JSON 里（HTML 转义过）。
CARD_JS = r"""(() => {
  const decode = (s) => (s || '').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
  const num = (s) => {
    const t = String(s == null ? '' : s).replace(/[,\s]/g, '');
    const m = t.match(/(-?\d+(?:\.\d+)?)\s*(万|w)?/i);
    if (!m) return null;
    return Math.round(Number(m[1]) * (m[2] ? 10000 : 1));
  };
  const txt = (el) => (el ? (el.innerText || '').trim() : null);
  return JSON.stringify([...document.querySelectorAll('.note-card')].map(c => {
    let noteId = null;
    try {
      noteId = JSON.parse(decode(c.getAttribute('data-impression')))
                 .noteTarget.value.noteId;
    } catch (e) {}
    const raw = [...c.querySelectorAll('.note-card__row--stats .note-card__stat span')]
                  .map(e => (e.innerText || '').trim());
    return {
      noteId,
      title: txt(c.querySelector('.note-card__title')),
      time: txt(c.querySelector('.note-card__time')),
      scheduled: !!c.querySelector('.note-card__schedule'),
      statsRaw: raw,
      stats: raw.map(num),
    };
  }));
})()"""

TABS_JS = r"""(() => JSON.stringify(
  [...document.querySelectorAll('.tab-item')].map(e => (e.innerText || '').trim())
))()"""

CLICK_TAB_JS = r"""(() => {
  const want = %s;
  const t = [...document.querySelectorAll('.tab-item')]
    .find(e => (e.innerText || '').trim().startsWith(want));
  if (!t) return 'not-found';
  t.click();
  return 'ok';
})()"""

OPEN_DRAFTS_JS = r"""(() => {
  const e = document.querySelector('.draft-title');
  if (!e) return null;
  e.click();
  return (e.innerText || '').trim();
})()"""

DRAFT_TABS_JS = r"""(() => JSON.stringify(
  [...document.querySelectorAll('.draft-tabs .tab-item')]
    .map(e => (e.innerText || '').trim())
))()"""

DRAFT_ITEMS_JS = r"""(() => JSON.stringify(
  [...document.querySelectorAll('.draft-item')].map(e => ({
    title: (e.querySelector('.draft-title-text') || {}).innerText || null,
    saved_at: (e.querySelector('.draft-time') || {}).innerText || null,
  }))
))()"""

CLICK_DRAFT_TAB_JS = r"""(() => {
  const want = %s;
  const t = [...document.querySelectorAll('.draft-tabs .tab-item')]
    .find(e => (e.innerText || '').trim().startsWith(want));
  if (!t) return 'not-found';
  t.click();
  return 'ok';
})()"""

CLOSE_DRAWER_JS = r"""(() => {
  const m = document.querySelector('.d-drawer-mask');
  if (m) { m.click(); return 'closed'; }
  return 'no-mask';
})()"""


def reexec_in_venv() -> None:
    """桥接依赖 websockets，它装在 skills 仓库的 venv 里，这里换解释器再跑。"""
    if os.environ.get("_XHS_REEXEC"):
        return
    try:
        import websockets  # noqa: F401
        return
    except ImportError:
        pass
    for candidate in (SKILLS_DIR / ".venv" / "bin" / "python",
                      SKILLS_DIR / ".venv" / "Scripts" / "python.exe"):
        if candidate.exists():
            os.environ["_XHS_REEXEC"] = "1"
            os.execv(str(candidate), [str(candidate), os.path.abspath(__file__), *sys.argv[1:]])


reexec_in_venv()


def die(msg: str, code: int = 2):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def bridge():
    sys.path.insert(0, str(SKILLS_DIR / "scripts"))
    try:
        from xhs.bridge import BridgePage
        from xhs.errors import CDPError
    except ImportError as e:
        die(f"无法从 {SKILLS_DIR} 导入 xhs 模块：{e}\n"
            "先按 rednote-post/references/publishing.md 跑它的 scripts/setup_bridge.sh，"
            "或用 XHS_SKILLS_DIR 指向仓库。")
    page = BridgePage(BRIDGE_URL)
    if not page.is_server_running():
        die("bridge server 没在跑。先在 rednote-post 里跑 `python3 scripts/xhs.py status`。")
    if not page.is_extension_connected():
        die("浏览器扩展没连上。打开装了 XHS Bridge 扩展的 Chrome 再试。")
    return page, CDPError


def jload(raw):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def cards_on_page(page) -> list[dict]:
    return jload(page.evaluate(CARD_JS)) or []


def card_key(c: dict) -> str:
    return c.get("noteId") or f"{c.get('title')}|{c.get('time')}"


def scroll_and_collect(page, limit: int, settle: int = 3) -> tuple[list[dict], bool]:
    """滚动收集卡片，直到拿到 limit 张或连续 settle 次不再增长。

    列表是分页/懒加载的：一次只有 20 张左右，账号总篇数远大于此，
    所以"只看到第一屏就下结论"是本脚本最容易犯的错。
    """
    seen: dict[str, dict] = {}
    stale = 0
    exhausted = False
    while True:
        for c in cards_on_page(page):
            seen[card_key(c)] = c
        if len(seen) >= limit:
            break
        before = len(seen)
        page.scroll_to_bottom()
        time.sleep(1.5)
        for c in cards_on_page(page):
            seen[card_key(c)] = c
        if len(seen) == before:
            stale += 1
            if stale >= settle:
                exhausted = True
                break
        else:
            stale = 0
    items = list(seen.values())
    return items[:limit], exhausted


def goto_note_manager(page) -> None:
    """每次扫 tab 前都重新导航。

    草稿箱在发布页，历史在笔记管理页——不重新导航就会在错误的页面上
    找 .tab-item，结果是把"页面上没有 tab"误读成"这个 tab 是空的"。
    """
    page.navigate(NOTE_MANAGER_URL)
    time.sleep(7)


def scan_tab(page, tab: str, limit: int) -> tuple[list[dict], bool, list[str]]:
    tabs = jload(page.evaluate(TABS_JS)) or []
    res = page.evaluate(CLICK_TAB_JS % json.dumps(tab))
    if res == "not-found":
        return [], True, tabs
    time.sleep(5)
    items, exhausted = scroll_and_collect(page, limit)
    return items, exhausted, tabs


def scan_queue(page, limit: int) -> dict:
    """未来定时发布 + 审核中积压。

    定时笔记既在"全部"里，也在"审核中"里（还没到发布时间就一直是审核中），
    两个 tab 各扫一次才能同时拿到"有没有定时"和"是否卡审核"。
    """
    all_cards, all_done, tabs = scan_tab(page, "全部", limit)
    review_cards, _, _ = scan_tab(page, "审核中", limit)
    review_ids = {c["noteId"] for c in review_cards if c.get("noteId")}

    scheduled = []
    for c in all_cards:
        if not c.get("scheduled"):
            continue
        scheduled.append({
            "noteId": c.get("noteId"),
            "title": c.get("title"),
            "time": c.get("time"),
            "in_review": c.get("noteId") in review_ids,
        })
    scheduled.sort(key=lambda x: x.get("time") or "")

    published_seen = [c for c in all_cards if not c.get("scheduled") and c.get("time")]
    return {
        "tabs": tabs,
        "scheduled": scheduled,
        "in_review_count": len(review_cards),
        "in_review": [{"noteId": c.get("noteId"), "title": c.get("title"),
                       "time": c.get("time")} for c in review_cards],
        "cards_scanned": len(all_cards),
        "scroll_exhausted": all_done,
        "recent_unpublished": published_seen[0]["time"] if published_seen else None,
    }


def scan_drafts(page) -> dict:
    """草稿箱。注意：草稿存在浏览器本地，清浏览器数据就没了。"""
    page.navigate(PUBLISH_URL)
    time.sleep(7)
    opened = page.evaluate(OPEN_DRAFTS_JS)
    if not opened:
        return {"available": False,
                "reason": "找不到 .draft-title（未登录、页面改版，或不在发布页）",
                "items": [], "counts": {}}
    time.sleep(2.5)
    tabs = jload(page.evaluate(DRAFT_TABS_JS)) or []
    items = []
    for tab in tabs:
        if page.evaluate(CLICK_DRAFT_TAB_JS % json.dumps(tab)) != "ok":
            continue
        time.sleep(1.5)
        for it in (jload(page.evaluate(DRAFT_ITEMS_JS)) or []):
            it["type"] = tab.split("(")[0]
            items.append(it)
    counts = {}
    for tab in tabs:
        name = tab.split("(")[0]
        try:
            counts[name] = int(tab.split("(")[1].rstrip(")"))
        except (IndexError, ValueError):
            counts[name] = None
    page.evaluate(CLOSE_DRAWER_JS)
    return {"available": True, "entry": opened, "counts": counts, "items": items}


def scan_history(page, limit: int) -> dict:
    """已发布笔记的发布时间与五项数据，用来算账号自己的最佳时段。"""
    cards, exhausted, _tabs = scan_tab(page, "已发布", limit)
    rows = []
    for c in cards:
        stats = c.get("stats") or []
        row = {"noteId": c.get("noteId"), "title": c.get("title"),
               "time": c.get("time")}
        for i, name in enumerate(STAT_ORDER):
            row[name] = stats[i] if i < len(stats) else None
        row["statsRaw"] = c.get("statsRaw")
        rows.append(row)
    rows = [r for r in rows if r.get("time")]
    rows.sort(key=lambda r: r["time"], reverse=True)
    return {"published": rows, "cards_scanned": len(cards),
            "scroll_exhausted": exhausted}


def stamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def emit(payload: dict, out: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"已写出 {p}")
        for k, v in payload.items():
            if isinstance(v, list):
                print(f"  {k}: {len(v)} 条")
            elif isinstance(v, dict) and k != "scanned_at":
                print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:120]}")
    else:
        print(text)


def main() -> int:
    ap = argparse.ArgumentParser(description="只读读取小红书创作者中心状态")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("queue", "history", "all"):
        p = sub.add_parser(name)
        p.add_argument("--max", type=int, default=40, help="每个列表最多读多少张卡片")
        p.add_argument("--out", default=None, help="把 JSON 写到文件")
    p = sub.add_parser("drafts")
    p.add_argument("--out", default=None)
    args = ap.parse_args()

    page, _ = bridge()
    payload = {"scanned_at": stamp()}

    if args.cmd in ("queue", "all"):
        goto_note_manager(page)
        payload["queue"] = scan_queue(page, args.max)
    if args.cmd in ("drafts", "all"):
        payload["drafts"] = scan_drafts(page)
    if args.cmd in ("history", "all"):
        goto_note_manager(page)
        payload["history"] = scan_history(page, args.max)

    if args.cmd == "all":
        payload["source_url"] = NOTE_MANAGER_URL
    emit(payload, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
