#!/usr/bin/env python3
"""human-writing 的机械闸门：查一段文字里"能机判"的 AI 味。

用法：
    python3 human_check.py <稿子> [--persona <人设文件>] [--json] [--quiet]

分三层判（口径见 references/ai-tells.md）：

    硬  HARD_PHRASES    几乎总是 AI 味的词／短语——命中即失败（退出码 1）
    硬  HARD_PATTERNS   套装句式（"随着……的发展""在这个……的时代"）——命中即失败
    硬  --persona       人设文件声明的禁忌词——命中即失败
    软  SOFT_PHRASES    可能合法、攒多了才像 AI 的连接词——只提醒
    软  STRUCT_PATTERNS 排比三连、段落长度过于均匀——只提醒

**"像不像一个人在说话"脚本查不出**——那要出声念，见 SKILL.md 第 3 步。
这里只兜住能数的那一半。

词表是单一来源：rednote-post 的 `check_content.py` 直接 import 本模块，
不另抄一份（见 references/persona-intake.md「人设文件合约」）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 硬：一出现就不像人。词都验证过——15 篇已发成品里零命中（不误伤）。
HARD_PHRASES = [
    # 论述套路／AI 连接词
    "综上所述", "总而言之", "总的来说", "综上",
    "值得注意的是", "值得注意", "值得一提", "不容忽视", "不容小觑", "不可忽视",
    "不难发现", "不难看出", "由此可见", "如上所述",
    "众所周知", "毋庸置疑", "毫无疑问", "显而易见", "不言而喻",
    "让我们一起", "不得不说的是", "不得不说",
    "在当今社会", "信息爆炸", "快节奏的时代", "随着时代的",
    "一举两得", "锦上添花", "无论如何",
    # 行话
    "赋能", "底层逻辑", "抓手", "闭环", "颗粒度", "对齐", "打法",
    "组合拳", "双刃剑", "降本增效", "深度赋能",
    # 模板腔／空词
    "极大地", "旨在", "致力于", "本文将", "接下来我们", "下面让我们",
    "再次强调", "需要强调",
]

# 硬：套装句式。用正则，因为中间会插词。
HARD_PATTERNS = [
    (re.compile(r"在这个.{0,12}的时代"), "在这个……的时代"),
    (re.compile(r"随着.{0,10}(的)?(发展|进步|普及|到来|深入)"), "随着……发展／到来"),
    (re.compile(r"让我们(一起|来)?(看看|看|聊聊|走进|探讨|思考)"), "让我们……（教程腔）"),
]

# 软：可能合法。攒多了才像 AI；单独出现不判失败，只提醒。
SOFT_PHRASES = [
    "首先", "其次", "再次", "一方面", "另一方面", "与此同时",
    "换句话说", "换言之", "需要注意的是", "需要指出的是", "需要说明的是",
    "某种程度上", "从某种意义上", "应该说", "可以说",
]

# 软：结构信号。排比三连 + 段落长度过于均匀。
STRUCT_PATTERNS = [
    (re.compile(r"既.{0,24}又.{0,24}还"), "排比三连（既要…又要…还要）"),
    (re.compile(r"不仅.{0,24}而且.{0,24}(还|更)"), "递进三连（不仅…而且…还）"),
]

UNIFORM_SPREAD = 0.25   # 段落长度极差 / 均值 低于这个值，就是"每段一样长"
UNIFORM_MIN_PARAS = 5

# 软：结构模板信号。阈值是**照着已发成品量出来的**（20 篇，见 references/ai-tells.md 第 4 节）：
# 真品里「→」领起的行动行最多 3 条、同一个 emoji 领起最多 2 段、破折号密度最高 0.7/100 字。
# 超了就是"把条目做成了模板"——内容没错，但没起伏。
ARROW_LEAD_RE = re.compile(r"^\s*(?:→|➜|->|=>)\s*\S")
EMOJI_LEAD_RE = re.compile(r"^\s*([\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]+)")
ARROW_MAX = 3            # 「→ 怎么用」超过这个数，就是在给每条观点配零件
EMOJI_LEAD_MAX = 2       # 同一个 emoji 领起超过这么多段，重音符号就变成了编号
DASH_PER_100 = 1.2       # 破折号密度上限（处 / 100 字）


def find_phrase_hits(text: str, phrases) -> list[dict]:
    lines = text.splitlines()
    hits = []
    for ph in phrases:
        n = text.count(ph)
        if n:
            ln = next((i for i, l in enumerate(lines, 1) if ph in l), 1)
            hits.append({"hit": ph, "count": n, "line": ln})
    return hits


def drop_subsumed(hits: list[dict]) -> list[dict]:
    """去掉被更长命中包含的短命中（"综上所述"命中后不再单报"综上"）。"""
    phrases = [h["hit"] for h in hits]
    return [h for h in hits
            if not any(h["hit"] != o and h["hit"] in o for o in phrases)]


def find_pattern_hits(text: str, patterns) -> list[dict]:
    lines = text.splitlines()
    hits = []
    for rx, label in patterns:
        for i, l in enumerate(lines, 1):
            m = rx.search(l)
            if m:
                hits.append({"hit": label, "sample": m.group(0), "line": i})
                break
    return hits


def uniform_paragraphs(text: str) -> dict | None:
    """模型爱写长度几乎一致的段落——人的段落是长短交错的。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) < UNIFORM_MIN_PARAS:
        return None
    lens = [len(p) for p in paras]
    if min(lens) < 12:
        return None
    mean = sum(lens) / len(lens)
    if mean <= 0:
        return None
    spread = (max(lens) - min(lens)) / mean
    if spread < UNIFORM_SPREAD:
        return {"hit": "段落长度过于均匀",
                "detail": f"{len(paras)} 段，最短 {min(lens)} 字、最长 {max(lens)} 字"}
    return None


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def arrow_items(text: str) -> dict | None:
    """「→」领起的'所以怎么用'行太多 = 每条观点都配了一个零件，读起来像模板。"""
    n = sum(1 for p in paragraphs(text) if ARROW_LEAD_RE.match(p))
    if n > ARROW_MAX:
        return {"hit": "「→」领起的行动行太多",
                "detail": f"{n} 条（已发成品最多 {ARROW_MAX}）——每条观点后面都接一句'所以怎么用'，就成了模板"}
    return None


def emoji_leads(text: str) -> dict | None:
    """同一个 emoji 领起好几段 = 把重音符号当成了编号。"""
    cnt: dict[str, int] = {}
    for p in paragraphs(text):
        m = EMOJI_LEAD_RE.match(p)
        if m:
            cnt[m.group(1)] = cnt.get(m.group(1), 0) + 1
    if cnt:
        sym, n = max(cnt.items(), key=lambda kv: kv[1])
        if n > EMOJI_LEAD_MAX:
            return {"hit": "同一个 emoji 领起多段",
                    "detail": f"「{sym}」领起 {n} 段（已发成品最多 {EMOJI_LEAD_MAX}）——重音符号被用成了编号"}
    return None


def dash_density(text: str) -> dict | None:
    """破折号连着来，是替想不出的话找台阶。"""
    n = text.count("——")
    per = n / max(len(text), 1) * 100
    if per > DASH_PER_100:
        return {"hit": "破折号过密",
                "detail": f"{n} 处／{len(text)} 字＝{per:.1f} 处每 100 字（已发成品最高 0.7）"}
    return None


# ---------- 人设文件里声明的禁忌词 ----------

BANNED_LINE_RE = re.compile(r"(禁忌词|禁用词|banned)\s*[:：]\s*(.+)", re.I)
FENCE_OPEN_RE = re.compile(r"```\s*(banned|禁忌词|禁用词)\s*$", re.I)
SPLIT_RE = re.compile(r"[｜|、,，;；/／\s]+")
TRIM = "`「」『』\"'（）()【】*"


def parse_banned(persona_text: str) -> list[str]:
    """从人设文件里读禁忌词。

    认两种写法（口径见 references/persona-intake.md）：
        - 一行声明：`禁忌词：首先｜其次｜综上所述`
        - 围栏块：```banned  ...  ```
    人设没声明就返回空——那种情况下只跑通用词表。
    """
    words: list[str] = []
    for raw in persona_text.splitlines():
        line = raw.strip()
        if FENCE_OPEN_RE.search(line):
            continue
        m = BANNED_LINE_RE.search(line)
        if not m:
            continue
        for tok in SPLIT_RE.split(m.group(2)):
            tok = tok.strip(TRIM)
            if 1 < len(tok) <= 12 and not tok.startswith(("http", "www")):
                words.append(tok)
    # 围栏块
    in_fence = False
    for raw in persona_text.splitlines():
        line = raw.rstrip()
        if not in_fence and FENCE_OPEN_RE.search(line.strip()):
            in_fence = True
            continue
        if in_fence:
            if line.strip().startswith("```"):
                in_fence = False
                continue
            tok = line.strip(TRIM)
            if 1 < len(tok) <= 12:
                words.append(tok)
    return list(dict.fromkeys(words))


def scan(text: str, extra_words=()) -> dict:
    extra = [w for w in dict.fromkeys(extra_words)]
    hard = drop_subsumed(find_phrase_hits(text, [w for w in HARD_PHRASES + extra]))
    hard += find_pattern_hits(text, HARD_PATTERNS)
    soft = drop_subsumed(find_phrase_hits(text, SOFT_PHRASES))
    soft += find_pattern_hits(text, STRUCT_PATTERNS)
    for extra_signal in (uniform_paragraphs(text), arrow_items(text),
                         emoji_leads(text), dash_density(text)):
        if extra_signal:
            soft.append(extra_signal)
    hard_keys = {h["hit"] for h in hard}
    soft = [h for h in soft if h["hit"] not in hard_keys]
    return {
        "pass": not hard,
        "hard": hard,
        "soft": soft,
        "persona_words": extra,
        "chars": len(text.strip()),
        "paragraphs": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
    }


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def fmt_hits(hits: list[dict]) -> list[str]:
    out = []
    for h in hits:
        extra = h.get("sample") or h.get("detail") or ""
        loc = f"第 {h['line']} 行" if h.get("line") else ""
        if h.get("count", 0) > 1:
            loc += f"，×{h['count']}"
        parts = [f"「{h['hit']}」"]
        if extra:
            parts.append(f"：{extra}")
        if loc:
            parts.append(f"（{loc}）")
        out.append("".join(parts))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="查一段文字里能机判的 AI 味")
    ap.add_argument("text", help="要查的稿子（纯文本，如 body.txt）")
    ap.add_argument("--persona", help="人设文件；从中读禁忌词（可选）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="只在失败时输出")
    ap.add_argument("--strict", action="store_true",
                    help="软信号也判失败（发布流水线用这个；已发成品全部 0 软信号，不会误伤）")
    args = ap.parse_args()

    p = Path(args.text).expanduser()
    if not p.is_file():
        print(f"没有这个文件：{p}", file=sys.stderr)
        return 2
    text = read(p)

    extra = []
    if args.persona:
        pp = Path(args.persona).expanduser()
        if not pp.is_file():
            print(f"没有这个人设文件：{pp}", file=sys.stderr)
            return 2
        extra = parse_banned(read(pp))

    rep = scan(text, extra)
    rep["file"] = str(p)
    rep["strict"] = args.strict
    if args.strict and rep["soft"]:
        rep["pass"] = False

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    elif rep["pass"]:
        if not args.quiet:
            tail = "（--strict）" if args.strict else ""
            print(f"✓ 没有 AI 味硬伤{tail}：{p.name}（{rep['chars']} 字，{rep['paragraphs']} 段）")
            for s in fmt_hits(rep["soft"]):
                print(f"⚠ 提醒（不判失败）：{s}")
            if not rep["soft"]:
                print("（连软信号也没有）")
            print("—— 脚本只管能数的那一半，出声念一遍再定稿。")
    else:
        print(f"✗ 有 AI 味硬伤：{p.name}" + ("（--strict：软信号也判失败）" if args.strict else ""))
        for h in fmt_hits(rep["hard"]):
            print(f"   ✗ {h}")
        verdict = "✗ 判失败" if args.strict else "⚠ 提醒（不判失败）"
        for s in fmt_hits(rep["soft"]):
            print(f"   {verdict}：{s}")
        print("回去删套话与行话，把抽象名词换成具体的物，再出声念一遍。")

    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
