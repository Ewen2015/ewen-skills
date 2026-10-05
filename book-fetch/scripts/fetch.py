#!/usr/bin/env python3
"""book-fetch：把「决定读某本书」变成「手上有一个可用的电子书文件」。

四步，中间必须停下来让用户确认格式与封面：

  search    通过外部适配器找候选（适配器命令由 ~/.config/book-fetch/config.json 指定）
  shortlist 剔除李鬼、逐条打分、解析封面与书目，产出可读的对比页
  download  用户确认后才下载，并校验落盘
  queue     登记到待读队列（reading-queue.md）

本脚本**不含任何书源名称**：它只调用适配器。换书源 = 改配置，不改代码。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CONFIG = HOME / ".config/book-fetch/config.json"
PREFS = HOME / ".config/book-fetch/prefs.json"
CACHE = HOME / ".cache/book-fetch"
STATE = HOME / ".local/share/book-fetch"
QUEUE_JSON = STATE / "queue.json"
QUEUE_MD = HOME / "Documents/reading-queue.md"

UA = "book-fetch/0.1 (personal reading pipeline)"

# ---------- 配置 ----------

def load_json(path: Path, default: dict) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return dict(default)
    return dict(default)


def load_config() -> dict:
    cfg = load_json(CONFIG, {})
    if not cfg.get("search_cmd"):
        die(
            "还没配置书源适配器。\n"
            f"建一个 {CONFIG}，至少给出 search_cmd 与 download_cmd，例如：\n"
            '{\n  "search_cmd": ["python3", "/path/to/runner.py", "search", "{query}", "--source", "all", "--json"],\n'
            '  "download_cmd": ["python3", "/path/to/runner.py", "download", "{result_id}", "--output", "{output}", "--json"]\n}\n'
            "本脚本不关心适配器背后是哪个书源。"
        )
    return cfg


def die(msg: str, code: int = 2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def run_adapter(template: list[str], mapping: dict) -> dict:
    argv = [str(t).format(**mapping) for t in template]
    proc = subprocess.run(argv, capture_output=True, text=True)
    raw = proc.stdout.strip()
    if not raw:
        die(f"适配器没有输出（退出码 {proc.returncode}）。\n{proc.stderr.strip()[:800]}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 适配器可能把警告打在 stdout，取最后一段 JSON
        i = raw.find("{")
        while i != -1:
            try:
                return json.loads(raw[i:])
            except json.JSONDecodeError:
                i = raw.find("{", i + 1)
        die(f"适配器输出不是 JSON：{raw[:500]}")


# ---------- 李鬼过滤 ----------

EXCLUDE = [
    r"study guide", r"\bsummary\b", r"workbook", r"quicklet", r"cliffs?notes",
    r"sparknotes", r"companion to", r"\(study guide\)", r"works by ",
    r"complete works", r"annotated bibliography", r"shmoop",
    r"导读", r"速读", r"精读笔记", r"摘要", r"解读版", r"节选",
]
EXCLUDE_RE = re.compile("|".join(EXCLUDE), re.I)


def is_impostor(r: dict) -> str | None:
    """返回命中原因；None 表示不是李鬼。"""
    blob = " ".join(str(r.get(k) or "") for k in ("title", "author", "publisher", "publisher_name"))
    m = EXCLUDE_RE.search(blob)
    return m.group(0) if m else None


# ---------- 文本归一化 ----------

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", s)


# ---------- 打分 ----------

FORMAT_RANK = {"epub": 3.0, "pdf": 2.0, "azw3": 1.6, "mobi": 1.5, "djvu": 1.0, "fb2": 1.2, "txt": 0.8}


def parse_size_kb(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s) / 1024 if s > 10000 else float(s)
    m = re.match(r"\s*([\d.]+)\s*([KMGT]?)B?\s*$", str(s), re.I)
    if not m:
        return None
    v = float(m.group(1))
    return v * {"": 1, "K": 1, "M": 1024, "G": 1024 ** 2, "T": 1024 ** 3}[m.group(2).upper()]


def author_match(author_field: str, term: str) -> bool:
    """作者匹配用词序无关的包含：`Sagan, Carl; Druyan Ann` 也算命中 `Carl Sagan`。"""
    a = norm(author_field)
    if not a:
        return False
    toks = [norm(x) for x in re.split(r"[\s,]+", term) if x.strip()]
    toks = [t for t in toks if t] or [norm(term)]
    return all(t in a for t in toks)


def score_candidate(r: dict, target: dict, peers: list[dict], prefs: dict) -> dict:
    """返回 {total, parts:[{name, score, max, note}]}。综合、可解释、可反驳。"""
    parts: list[dict] = []
    ext = (r.get("extension") or "").lower()
    title = r.get("title") or ""
    author = r.get("author") or ""
    ident = str(r.get("identifier") or "")
    blob = norm(title + " " + author)

    # 1. 书目匹配度 /25
    s = 0.0
    notes = []
    t_norm = norm(target["title"])
    if t_norm and t_norm in norm(title):
        s += 10
        if norm(title).startswith(t_norm):
            s += 2
            notes.append("书名以目标开头")
    else:
        notes.append("书名不完全吻合")
    if target["author_terms"] and any(author_match(author, t) for t in target["author_terms"]):
        s += 8
    else:
        notes.append("作者未匹配")
    if target.get("isbns") and any(i in ident.replace("-", "") for i in target["isbns"]):
        s += 5
        notes.append("ISBN 命中已知版本")
    parts.append({"name": "书目匹配", "score": min(s, 25), "max": 25, "note": "；".join(notes)})

    # 2. 版本完整性 /20
    s = 0.0
    notes = []
    if (r.get("publisher") or r.get("publisher_name")):
        s += 5
        notes.append(f"有出版社")
    if r.get("year"):
        s += 4
        notes.append(f"{r['year']}")
    lang = (r.get("language") or "").lower()
    want_lang = (prefs.get("language") or "").lower()
    if lang:
        if want_lang and lang.startswith(want_lang):
            s += 6
            notes.append(f"语言 {lang}（符合偏好）")
        elif not want_lang:
            s += 3
            notes.append(f"语言 {lang}")
        else:
            notes.append(f"语言 {lang}（偏好 {want_lang}）")
    else:
        notes.append("语言未知")
    if ext == "epub":
        s += 5
        notes.append("epub 未删节可能性高")
    parts.append({"name": "版本完整", "score": min(s, 20), "max": 20, "note": "；".join(notes)})

    # 3. 文本可提取性 /20 —— 决定能不能自动做笔记，最重要的技术维度
    s = 0.0
    notes = []
    if ext == "epub":
        s = 18
        notes.append("epub 通常带文字层，可直接抽取")
    elif ext == "pdf":
        s = 11
        notes.append("pdf：文字层未知，下载后必须检测（扫描件要 OCR）")
    elif ext in ("mobi", "azw3"):
        s = 8
        notes.append(f"{ext}：需先转换")
    elif ext:
        s = 5
        notes.append(f"{ext}：格式不理想")
    else:
        s = 4
        notes.append("格式未知")
    parts.append({"name": "文本可提取", "score": s, "max": 20, "note": "；".join(notes)})

    # 4. 文件线索 /15 —— 同格式里明显偏小的，多半删了图或就是节本
    s = 0.0
    notes = []
    kb = parse_size_kb(r.get("size") or r.get("filesize"))
    same = [parse_size_kb(p.get("size") or p.get("filesize")) for p in peers
            if (p.get("extension") or "").lower() == ext]
    same = [x for x in same if x]
    if kb:
        if len(same) >= 3:
            med = statistics.median(same)
            ratio = kb / med if med else 1.0
            if ratio >= 3:
                s += 12
                notes.append(f"{kb/1024:.2f} MB，远大于同格式中位 {med/1024:.2f} MB（有图版的书通常如此，优先）")
            elif ratio >= 0.75:
                s += 12
                notes.append(f"{kb/1024:.2f} MB，与同格式中位相当")
            elif ratio >= 0.4:
                s += 7
                notes.append(f"{kb/1024:.2f} MB，明显小于同格式中位 {med/1024:.2f} MB")
            else:
                s += 2
                notes.append(f"{kb/1024:.2f} MB，远小于同格式中位 {med/1024:.2f} MB（疑删图或节本）")
        else:
            s += 8
            notes.append(f"{kb/1024:.2f} MB")
    else:
        s += 3
        notes.append("文件大小未知")
    parts.append({"name": "文件线索", "score": s, "max": 15, "note": "；".join(notes)})

    # 5. 元数据完整度 /10
    fields = ["title", "author", "language", "extension", "year",
              "publisher", "identifier", "size"]
    have = sum(1 for f in fields if r.get(f) or r.get("publisher_name"))
    s = round(10 * have / len(fields), 1)
    parts.append({"name": "元数据", "score": s, "max": 10,
                  "note": f"{have}/{len(fields)} 个字段有值"})

    # 6. 可得性 /10
    s = 0.0
    if r.get("can_download"):
        s = 10
        note = "可直接下载"
    elif r.get("requires_account"):
        s = 5
        note = "需要登录账号才能下载"
    elif r.get("can_attempt_download"):
        s = 7
        note = "可尝试下载"
    else:
        s = 2
        note = "当前不可下载"
    parts.append({"name": "可得性", "score": s, "max": 10, "note": note})

    total = round(sum(p["score"] for p in parts), 1)
    isbn_hit = bool(target.get("isbns") and any(i in ident.replace("-", "") for i in target["isbns"]))
    return {"total": total, "parts": parts, "isbn_hit": isbn_hit, "size_kb": kb or 0.0}


# ---------- 封面与书目（公共书目 API）----------

def http_json(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as f:
            return json.loads(f.read().decode("utf-8", "replace"))
    except Exception:
        return None


def http_bytes(url: str, timeout: int = 25) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as f:
            data = f.read()
            return data if len(data) > 2000 else None   # 占位图只有几十字节
    except Exception:
        return None


def resolve_cover(cand: dict) -> dict:
    """按 ISBN → 书目搜索 的顺序找封面，返回 {cover_path, bibliographic}。"""
    out = {"cover_path": None, "bibliographic": {}}
    isbns = [x.strip() for x in re.split(r"[,\s]+", str(cand.get("identifier") or "")) if x.strip()]
    isbns = [i for i in isbns if re.fullmatch(r"[\dXx-]{10,17}", i)]

    for isbn in isbns:
        d = http_json(f"https://openlibrary.org/isbn/{isbn.replace('-', '')}.json")
        if d:
            out["bibliographic"] = {
                "title": d.get("title"),
                "publishers": d.get("publishers"),
                "publish_date": d.get("publish_date"),
                "number_of_pages": d.get("number_of_pages"),
                "isbn": isbn,
                "source": "openlibrary:isbn",
            }
            covers = d.get("covers") or []
            if covers:
                data = http_bytes(f"https://covers.openlibrary.org/b/id/{covers[0]}-L.jpg")
                if data:
                    out["cover_path"] = data
                    return out
    # 回退：书名 + 作者搜索
    q = urllib.parse.quote(f"{cand.get('title','')} {cand.get('author','')}".strip())
    d = http_json(f"https://openlibrary.org/search.json?q={q}&limit=1"
                  "&fields=title,author_name,first_publish_year,publisher,cover_i,isbn,number_of_pages_median")
    if d and d.get("docs"):
        doc = d["docs"][0]
        out["bibliographic"] = {
            "title": doc.get("title"),
            "authors": doc.get("author_name"),
            "publishers": doc.get("publisher"),
            "publish_date": doc.get("first_publish_year"),
            "number_of_pages": doc.get("number_of_pages_median"),
            "source": "openlibrary:search",
        }
        if doc.get("cover_i"):
            data = http_bytes(f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg")
            if data:
                out["cover_path"] = data
    return out


# ---------- 命令 ----------

def cmd_search(args) -> int:
    cfg = load_config()
    CACHE.mkdir(parents=True, exist_ok=True)
    res = run_adapter(cfg["search_cmd"], {"query": args.query})
    out = CACHE / "last_search.json"
    out.write_text(json.dumps({"query": args.query, "raw": res}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    n = len(res.get("results") or [])
    print(f"找到 {n} 条候选 → {out}")
    for s in res.get("sources") or []:
        print(f"  · {s.get('source')}: {s.get('status')} {s.get('message') or ''}".rstrip())
    print("下一步：python3 scripts/fetch.py shortlist")
    return 0


def cmd_shortlist(args) -> int:
    src = Path(args.file).expanduser() if args.file else CACHE / "last_search.json"
    if not src.exists():
        die(f"没有搜索结果：{src}\n先跑 search。")
    blob = json.loads(src.read_text(encoding="utf-8"))
    raw = blob.get("raw") or blob
    results = raw.get("results") or []
    if not results:
        die("搜索结果为空。")

    prefs = load_json(PREFS, {"format_rank": ["epub", "pdf"], "language": "english"})
    query = blob.get("query") or args.query or ""
    target = build_target(query, args)

    excluded, kept = [], []
    for r in results:
        reason = is_impostor(r)
        if reason:
            excluded.append({"result": r, "reason": reason})
        else:
            kept.append(r)

    # 去重：同 identifier 或同 hash 只留分数高的
    scored = []
    for r in kept:
        sc = score_candidate(r, target, kept, prefs)
        scored.append({**r, "_score": sc})
    dedup: dict = {}
    for r in scored:
        k = key_of(r)
        if k not in dedup or r["_score"]["total"] > dedup[k]["_score"]["total"]:
            dedup[k] = r
    scored = sorted(dedup.values(),
                    key=lambda x: (-x["_score"]["total"],
                                   not x["_score"]["isbn_hit"],
                                   -x["_score"]["size_kb"]))
    dropped_dupes = len(kept) - len(scored)
    if args.max:
        scored = scored[:args.max]

    cover_dir = CACHE / "covers"
    cover_dir.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(scored):
        got = resolve_cover(r)
        r["_bib"] = got["bibliographic"]
        if got["cover_path"]:
            p = cover_dir / f"{i:02d}-{norm(str(r.get('result_id')))[:24]}.jpg"
            p.write_bytes(got["cover_path"])
            r["_cover"] = str(p)

    payload = {
        "query": query, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target": target, "candidates": scored, "excluded": excluded,
        "sources": raw.get("sources") or [],
        "dropped_duplicates": dropped_dupes,
    }
    out = CACHE / "shortlist.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html = render_html(payload)
    (CACHE / "shortlist.html").write_text(html, encoding="utf-8")
    print_text(payload)
    print(f"\n对比页：{CACHE/'shortlist.html'}\n结构化：{out}")
    return 0


def key_of(r: dict) -> str:
    return norm(str(r.get("identifier") or r.get("hash") or r.get("title") or ""))[:40]


def build_target(query: str, args) -> dict:
    title = args.title or query
    authors = [a.strip() for a in (args.author or "").split(",") if a.strip()]
    isbns = [i.replace("-", "") for i in (args.isbn or "").split(",") if i.strip()]
    terms = authors + (["sagan"] if "sagan" in query.lower() and not authors else [])
    return {"title": title, "author_terms": [t.lower() for t in terms] if terms else [],
            "isbns": isbns, "query": query}


def print_text(payload: dict) -> None:
    print(f"# 候选评分（{payload['query']}）\n")
    print("| # | 分数 | 书名 | 作者 | 格式 | 大小 | 年份 | 封面 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(payload["candidates"]):
        flag = " ⭐️" if i == 0 else ""
        print(f"| {i+1}{flag} | **{r['_score']['total']}** | {r.get('title','')} | {r.get('author','')} | "
              f"{r.get('extension','')} | {r.get('size','')} | {r.get('year') or '—'} | "
              f"{'有' if r.get('_cover') else '无'} |")
    print("\n## 逐条理由\n")
    for i, r in enumerate(payload["candidates"]):
        print(f"**[{i+1}] {r.get('title','')}** — {r['_score']['total']} 分")
        for p in r["_score"]["parts"]:
            print(f"  - {p['name']} {p['score']}/{p['max']}：{p['note']}")
        if r.get("_bib"):
            b = r["_bib"]
            print(f"  - 书目核对：{b.get('title')}｜{b.get('publishers')}｜{b.get('publish_date')}"
                  f"｜{b.get('number_of_pages')} 页（{b.get('source')}）")
        print()
    if payload["excluded"]:
        print("## 已剔除（疑似李鬼）\n")
        for e in payload["excluded"]:
            print(f"- {e['result'].get('title','')} — 命中「{e['reason']}」")


def render_html(payload: dict) -> str:
    rows = []
    for i, r in enumerate(payload["candidates"]):
        img = (f'<img src="{Path(r["_cover"]).as_uri()}" alt="cover">'
               if r.get("_cover") else '<div class="nocover">无封面</div>')
        parts = "".join(
            f'<li><b>{p["name"]}</b> <span class="sc">{p["score"]}/{p["max"]}</span><br>{p["note"]}</li>'
            for p in r["_score"]["parts"])
        bib = r.get("_bib") or {}
        bibline = "｜".join(str(x) for x in [bib.get("title"), bib.get("publishers"),
                                            bib.get("publish_date"),
                                            (f'{bib["number_of_pages"]} 页' if bib.get("number_of_pages") else None)]
                            if x)
        rows.append(f"""
    <article class="card">
      <div class="cover">{img}</div>
      <div class="meta">
        <h2><span class="rank">#{i+1}</span> <span class="score">{r['_score']['total']}</span> {r.get('title','')}</h2>
        <p class="sub">{r.get('author','')}｜{r.get('extension','').upper()}｜{r.get('size','')}｜{r.get('year') or '年份未知'}｜{r.get('language','')}</p>
        <p class="bib">书目核对：{bibline or '未找到'}</p>
        <ul>{parts}</ul>
      </div>
    </article>""")
    excl = "".join(f"<li>{e['result'].get('title','')} — <i>{e['reason']}</i></li>"
                   for e in payload["excluded"])
    return f"""<!doctype html><meta charset="utf-8">
<title>候选评分 · {payload['query']}</title>
<style>
 body{{font:15px/1.6 -apple-system,"PingFang SC",sans-serif;background:#F3EEE5;color:#111;margin:0;padding:32px}}
 h1{{font-size:22px;margin:0 0 6px}} .q{{color:#666;margin-bottom:22px;font-size:13px}}
 .card{{display:flex;gap:20px;background:#fff;border:1px solid #e3ded4;border-radius:6px;padding:18px;margin-bottom:16px}}
 .cover img{{width:132px;border-radius:3px;display:block}}
 .nocover{{width:132px;height:196px;display:flex;align-items:center;justify-content:center;background:#eee;color:#999;font-size:12px;border-radius:3px}}
 .meta{{flex:1}} h2{{font-size:17px;margin:0 0 4px;font-weight:600}}
 .rank{{color:#999;font-weight:400}} .score{{background:#111;color:#fff;border-radius:3px;padding:1px 7px;font-size:13px}}
 .sub{{color:#555;font-size:13px;margin:0 0 4px}} .bib{{color:#777;font-size:12px;margin:0 0 10px}}
 ul{{list-style:none;padding:0;margin:0}} li{{font-size:12.5px;color:#444;padding:3px 0;border-top:1px solid #f0ece4}}
 .sc{{color:#111;font-variant-numeric:tabular-nums}}
 .excl{{background:#fff;border:1px solid #e3ded4;border-radius:6px;padding:14px 18px;font-size:13px;color:#666}}
</style>
<h1>候选评分</h1><div class="q">{payload['query']} · {payload['generated_at']}</div>
{''.join(rows)}
<div class="excl"><b>已剔除（疑似李鬼/摘编）</b><ul>{excl or '<li>无</li>'}</ul></div>
"""


def clean_filename(title: str, author: str, ext: str) -> str:
    """生成干净文件名：去掉书名号里的来源后缀、站点名与多余括号。

    下载器给的文件名常带站点后缀（形如 `书名 (site.sk, site2.sk).epub`），
    那属于来源信息，不该留在书库和笔记里。
    """
    t = str(title or "未命名")
    # 通用规则：括号里只要出现域名样式的 token，整块去掉。
    # 不列举具体站点——列举会过时，也会把来源信息写进仓库。
    t = re.sub(r"[（(][^）)]*[a-z0-9-]+\.[a-z]{2,4}[^）)]*[）)]", "", t, flags=re.I)
    t = re.sub(r"[\\/:*?\"<>|]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" .-_")
    a = re.sub(r"[\\/:*?\"<>|]+", " ", str(author or "")).strip()
    a = re.split(r"[;,]", a)[0].strip()
    name = f"{t} - {a}" if a and a.lower() not in t.lower() else t
    ext = str(ext or "").strip().lstrip(".").lower()
    return (name[:150].strip() or "book") + (f".{ext}" if ext else "")


def cmd_download(args) -> int:
    cfg = load_config()
    payload = json.loads((CACHE / "shortlist.json").read_text(encoding="utf-8"))
    cands = payload["candidates"]
    idx = args.pick - 1
    if not (0 <= idx < len(cands)):
        die(f"--pick 超出范围（1–{len(cands)}）")
    r = cands[idx]
    outdir = Path(args.output).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in outdir.iterdir()} if outdir.exists() else set()
    res = run_adapter(cfg["download_cmd"],
                      {"result_id": r["result_id"], "output": str(outdir)})
    if not res.get("ok", True):
        die(f"适配器报告失败：{json.dumps(res.get('error'), ensure_ascii=False)}")
    after = [p for p in outdir.iterdir() if p.name not in before]
    if not after:
        die("适配器说成功，但目录里没有新文件——不要当成下载完成。")
    f = max(after, key=lambda p: p.stat().st_size)
    if not args.keep_raw_name:
        clean = f.with_name(clean_filename(r.get("title"), r.get("author"), f.suffix.lower()))
        if clean != f and not clean.exists():
            f.rename(clean)
            f = clean
    print(f"已下载：{f}（{f.stat().st_size/1024/1024:.2f} MB）")
    if f.suffix.lower() == ".pdf":
        print("提醒：pdf 需要检测文字层；若是扫描件，先确认要不要走 OCR 再决定是否用它做笔记。")
    if args.queue:
        cmd_queue(argparse.Namespace(action="add", title=r.get("title"), author=r.get("author"),
                                     file=str(f), result_id=r.get("result_id"),
                                     note=args.note, status="fetched"))
    return 0


def cmd_queue(args) -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    q = load_json(QUEUE_JSON, {"items": []})
    items = q.get("items") or []
    if args.action == "add":
        items.append({"title": args.title, "author": args.author, "file": args.file,
                      "result_id": args.result_id, "status": args.status or "fetched",
                      "note": args.note or "", "added_at": datetime.now().date().isoformat()})
    elif args.action == "list":
        pass
    elif args.action == "set":
        n = 0
        for it in items:
            if norm(it.get("title")) == norm(args.title):
                it["status"] = args.status
                n += 1
        if not n:
            die(f"队列里没有《{args.title}》")
    q["items"] = items
    QUEUE_JSON.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
    render_queue(items)
    print_queue(items)
    return 0


def render_queue(items: list[dict]) -> None:
    lines = ["# 待读队列", "",
             "由 `book-fetch` 维护，别手改（手改会被下次写入覆盖）。",
             "状态：`want` 想读 · `fetched` 已拿到文件 · `reading` 在读 · `done` 已读完 · `dropped` 放弃", ""]
    lines += ["| 状态 | 书名 | 作者 | 文件 | 备注 |", "| --- | --- | --- | --- | --- |"]
    for it in items:
        f = it.get("file") or "—"
        lines.append(f"| {it.get('status','?')} | {it.get('title','')} | {it.get('author','')} | "
                     f"{Path(f).name if f != '—' else '—'} | {it.get('note','')} |")
    if not items:
        lines.append("| — | （空） | | | |")
    QUEUE_MD.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_queue(items: list[dict]) -> None:
    print(f"# 待读队列（{len(items)} 条）\n")
    for it in items:
        print(f"- [{it.get('status','?')}] {it.get('title','')} — {it.get('author','')}"
              + (f"（{it.get('note')}）" if it.get("note") else ""))
    print(f"\n→ {QUEUE_MD}")


def main() -> int:
    ap = argparse.ArgumentParser(description="book-fetch：找书、评分、确认、下载、登记队列")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="调用外部适配器找候选")
    p.add_argument("query")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("shortlist", help="剔除李鬼、打分、解析封面与书目")
    p.add_argument("--file", help="用指定的搜索结果文件，默认用最近一次")
    p.add_argument("--query")
    p.add_argument("--title")
    p.add_argument("--author")
    p.add_argument("--isbn")
    p.add_argument("--max", type=int, default=8)
    p.set_defaults(fn=cmd_shortlist)

    p = sub.add_parser("download", help="下载用户选中的那条（必须由用户确认后调用）")
    p.add_argument("--pick", type=int, required=True, help="shortlist 里的序号，从 1 开始")
    p.add_argument("--output", required=True)
    p.add_argument("--queue", action="store_true", help="下载成功后登记到待读队列")
    p.add_argument("--note", default="")
    p.add_argument("--keep-raw-name", action="store_true",
                   help="不重命名（默认会去掉文件名里的来源后缀）")
    p.set_defaults(fn=cmd_download)

    p = sub.add_parser("queue", help="待读队列")
    p.add_argument("action", choices=["add", "list", "set"])
    p.add_argument("--title"); p.add_argument("--author"); p.add_argument("--file")
    p.add_argument("--result_id"); p.add_argument("--status"); p.add_argument("--note")
    p.set_defaults(fn=cmd_queue)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
