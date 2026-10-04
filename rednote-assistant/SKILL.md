---
name: rednote-assistant
description: >-
  小红书发布排期助理：定更新频率与发布时段、看平台上有没有未来定时发布的笔记、
  盘草稿箱、算现有成品能撑几周、指出排期缺口、按账号自己的历史数据挑最佳发布时间、
  给出素材积累量目标，并判断该用定期提醒还是随问随答。
  当用户说"更新计划""发布频率""排期""内容日历""草稿够不够""下次发什么"
  "什么时候发最好""有没有定时发布""排期还剩几周""rednote 助理"时激活。
  不适用于：写标题正文、做卡片图、实际发布、修改已发布笔记——那些走 rednote-post。
metadata:
  short-description: 小红书发布排期与库存体检（只排期，不写不发）
---

# 小红书排期助理

只管**什么时候发什么、还够发多久**。文案、卡片图、发布动作都在 `rednote-post`，
这个 skill 不写、不做图、不点发布。

下面命令里的 `<skill>` 指本文件所在目录
（通常是 `${CODEX_HOME:-$HOME/.codex}/skills/rednote-assistant`）。
按字面写 `scripts/plan.py` 会找不到——当前工作目录通常是用户的项目，不是 skill 目录。

## 两个脚本

| 回答什么问题 | 命令 | 触不触网 |
| --- | --- | --- |
| 平台上现在有什么：定时发布队列、审核中、草稿箱、已发布数据 | `python3 <skill>/scripts/xhs_state.py` | 要浏览器桥接 |
| 计划、库存、覆盖率、缺口、时段、提醒（纯本地算） | `python3 <skill>/scripts/plan.py` | 不要 |

## 铁律

1. **计划先行。** 没有 `plan.json` 里的**频率**，就无从回答"草稿够不够"——
   "够"永远是相对频率说的。缺计划时先 `plan.py init`，把频率/时段/栏目拿给用户确认，
   **不要替用户猜一个频率**然后据此下结论。
2. **只读。** 本 skill 只切 tab、开抽屉、滚动、读文本。不改计划外的任何东西，
   不发不删不改笔记。发布永远走 `rednote-post`（它自带确认闸门）。
3. **草稿箱不是库存。** 平台草稿存在**当前浏览器本地**，清浏览器数据就没了，
   也不跟账号走。真正的库存是 workspace 里 `posts/` 下过了实测的成品目录。
4. **列表是懒加载的。** 笔记管理一屏只有 10–20 张，账号总篇数往往上百。
   只看第一屏就断言"没有定时发布"是本 skill 最容易犯的错——脚本已经做了滚动收集，
   但 `--max` 给小了照样看不全，报告里要如实说扫了多少张。

## 工作流

### 1. 定计划（只做一次，之后按需改）

```bash
python3 <skill>/scripts/plan.py init --workspace <workspace>
```

默认 workspace 是 `~/Documents/rednote`，也可以用 `$XHS_WORKSPACE` 指定。
`init` 只建骨架、不覆盖已有文件。字段口径、频率怎么选、栏目怎么配，见
[`references/plan-schema.md`](references/plan-schema.md)。

频率这一步必须问用户，不能自己定：能长期维持的频率取决于他每周真的能拿出多少时间。
给建议而不是给结论——见 `references/plan-schema.md` 的「频率怎么选」。

### 2. 扫平台状态

```bash
python3 <skill>/scripts/xhs_state.py all --out <workspace>/state/state.json
```

四条子命令：`queue`（定时发布 + 审核中）、`drafts`（草稿箱）、`history`（已发布 + 数据）、
`all`。整轮约 1 分钟，慢是因为要真跳页面、真滚动。

要浏览器桥接就绪；没就绪先按 `rednote-post/references/publishing.md` 配好，
不要在桥接没通时硬跑。

页面选择器和字段含义（改版时按这张表修）见 [`references/platform-selectors.md`](references/platform-selectors.md)。

### 3. 出排期报告

```bash
python3 <skill>/scripts/plan.py report --workspace <workspace> \
    --state <workspace>/state/state.json --weeks 4
```

报告包含六块：计划摘要、库存、**未来 N 周排期表**（已定时 / 计划外已定时 / 本地成品 / 缺口）、
**素材积累量建议**、账号自己的时段数据、提醒建议。

没有 `--state` 也能跑，只是少了平台那一段——纯本地计划与库存照样能算。

### 4. 讲给用户听

报告是给机器看的底稿，转述时按这个顺序，别把表格整段粘过去：

1. **未来几周有几个空档** → 这是用户最想知道的一句。
2. 平台上**有没有已定时**的笔记、有没有卡在审核中。
3. 要回到目标缓冲**还缺几篇**，以及**选题池还够不够**。
4. 时段建议（有自有数据就按数据说，样本薄就明说样本薄）。
5. 提醒方式建议（要开就去建，见下一步）。

### 5. 定提醒方式

`report` 会直接给 `cron` 或 `ad-hoc` 的结论和理由，判定规则与配置模板见
[`references/reminders.md`](references/reminders.md)。要开定期提醒时，用 automation 工具建，
**不要手写 RRULE 字符串**。

## 什么时候该改计划

- 连续两周发不满计划 → 频率定高了，下调，不要靠更长的缓冲硬撑。
- 某种内容明显跑得比别的快 → 调 `pillars` 的配比。
- 账号要停更一段时间 → 在 `plan.json` 里加 `paused`，别让报告继续报"空档"。

## 参考文件

- [`references/plan-schema.md`](references/plan-schema.md)——`plan.json`/`topics.md` 字段、
  workspace 布局、频率与素材积累量的口径
- [`references/timing.md`](references/timing.md)——最佳发布时段：什么时候信自有数据、
  什么时候退回基线，以及为什么不能直接比阅读量
- [`references/reminders.md`](references/reminders.md)——定期提醒还是随问随答，
  以及 reminders 的创建模板
- [`references/platform-selectors.md`](references/platform-selectors.md)——创作者中心的
  真实选择器与字段（2026-10 实测）
