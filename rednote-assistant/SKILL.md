---
name: rednote-assistant
description: >-
  小红书发布排期助理：定更新频率与发布时段、看平台上有没有未来定时发布的笔记、
  盘草稿箱、算现有成品能撑几周、指出排期缺口、按账号自己的历史数据挑最佳发布时间、
  给出素材积累量目标，并判断该用定期提醒还是随问随答。还负责发布前的最后一道检查：
  检查全绿且计划已授权时，直接发布，不再回头找用户确认。
  当用户说"更新计划""发布频率""排期""内容日历""草稿够不够""下次发什么"
  "什么时候发最好""有没有定时发布""排期还剩几周""检查一下能发就发""rednote 助理"时激活。
  不适用于：写标题正文、做卡片图、修改已发布笔记——那些走 rednote-post。
metadata:
  short-description: 小红书排期体检 + 发布就绪检查（检查全绿可代为发布）
---

# 小红书排期助理

只管**什么时候发什么、还够发多久、这一条能不能发**。文案、卡片图和发布动作本身都在
`rednote-post`——本 skill 不写文案、不做图，但**检查全绿时有权直接调用 `rednote-post`
把笔记发出去，不必再问一次**。

下面命令里的 `<skill>` 指本文件所在目录
（通常是 `${CODEX_HOME:-$HOME/.codex}/skills/rednote-assistant`）。
按字面写 `scripts/plan.py` 会找不到——当前工作目录通常是用户的项目，不是 skill 目录。

## 三个命令

| 回答什么问题 | 命令 | 触不触网 |
| --- | --- | --- |
| 平台上现在有什么：定时发布队列、审核中、草稿箱、已发布数据 | `python3 <skill>/scripts/xhs_state.py` | 要浏览器桥接 |
| 计划、库存、覆盖率、缺口、时段、提醒（纯本地算） | `python3 <skill>/scripts/plan.py report` | 不要 |
| 发布就绪检查：这一条够不够格直接发 | `python3 <skill>/scripts/plan.py ready` | 不要（版式实测要 Chrome） |

## 铁律

1. **计划先行。** 没有 `plan.json` 里的**频率**，就无从回答"草稿够不够"——
   "够"永远是相对频率说的。缺计划时先 `plan.py init`，把频率/时段/栏目拿给用户确认，
   **不要替用户猜一个频率**然后据此下结论。
2. **默认只读，授权后才动手。** 平时只切 tab、开抽屉、滚动、读文本，不改计划外的任何东西，
   不发不删不改笔记。唯一的例外是「发布授权」——`plan.json` 里写了 `publish_policy: "auto"`
   且发布就绪检查全绿时，本 skill 直接发布，不再回头确认；其余一切情况照旧停下来问。
3. **草稿箱不是库存。** 平台草稿存在**当前浏览器本地**，清浏览器数据就没了，
   也不跟账号走。真正的库存是 workspace 里 `posts/` 下过了实测的成品目录。
4. **列表是懒加载的，而且"没读全"和"读完了"长得一模一样。** 笔记管理是虚拟滚动，
   一屏只挂约 10 张，账号总篇数往往上百；往下要靠滚动触发下一页，而这个请求
   **在 Chrome 窗口不在前台时不发**。
5. **`partial: true` 时禁止下缺口结论。** 扫描输出里 `scroll_exhausted` 只表示列表真的到底，
   页面还挂着「正在加载」时一律为 `false`；`partial: true` 说明这份扫描不完整。
   这时**任何"排期有空档""这里该补一篇"都是不成立的**——先按提示把 Chrome 切到前台重扫。
   少报比报错危险得多：2026-10-06 就是因为把"卡片数不再增长"误当"列表到底"，
   漏读两篇已排期笔记还报了个全绿的 `scroll_exhausted: true`，据此得出的空档结论整套作废。

## 发布授权

用户已经把"检查过关就发"的权限交给本 skill。开关在 `plan.json`：

```json
{"publish_policy": "auto"}
```

- `auto` —— 就绪检查全绿时直接发，不再问用户。
- `confirm`（或字段缺失）—— 每次都回到确认闸门，把内容摆给用户看再发。

**这条权限只覆盖"发不发、发在哪一档"两个问题**，不覆盖内容本身：标题、正文、图片、
合集仍然来自已经做完的 `rednote-post` 成品目录，本 skill 不替用户改一个字。

### 发布就绪检查

```bash
python3 <skill>/scripts/plan.py ready --workspace <workspace> \
    --post <post-dir> --state <workspace>/state/state.json
```

退出码 `0` 表示全绿。逐条验：

| 检查 | 不过会怎样 |
| --- | --- |
| 计划未停更（`paused` 不为 true） | 停更期不自动发 |
| `publish_policy` 是 `auto` | 没授权就回到确认闸门 |
| 成品唯一（给了 `--post`，或 `posts/` 下只有一篇可直接发） | 多篇候选时让用户挑 |
| 交付物齐全（`manifest.json` / `title.txt` / `body.txt` / 至少一张图） | 缺件不发 |
| 标题 ≤ 20 字 | CLI 会硬失败，先去改 |
| 正文末行是标签行 | 否则标签会退化成普通文字 |
| `render_cards.py` 全绿 | 版式没过实测，不许发 |
| **队列扫描完整**（`state.json` 的 `queue.partial` 不为真） | 空档是从**没读全**的队列算出来的，**宁可不发** |
| 有空闲时段 | 未来几周排满了就没得发 |

正文超过 1000 字只提醒不拦（平台本身也只警告）。

**「队列扫描完整」这一条为什么必须拦**：空档是"已定时的档位"的补集，
少读一条 = 凭空多出一个空档。2026-10-06 就撞到过——扫描因虚拟列表停发下一页只读到 10 张
（`partial: true`），而 `ready` 当时不看这个字段，报出的"空档"正是**《纳瓦尔宝典》占着的 10-07**；
差一步，自动发布就会把新笔记压在旧笔记上面。

扫描读不全时，正确的出路不是"硬发"，而是**换一份可信的占用清单**：

```bash
python3 <skill>/scripts/plan.py ready ... --scheduled-verified <workspace>/state/scheduled-verified.json
```

这个文件要有 `source`（凭什么信它：用户确认、人工核对）和 `scheduled`（`[{"time": "…"}]`）。
给了它就不再因 `partial` 判不过，但会多一条「占用清单有人工来源」检查——
**不许有来路不明的空档**。

**这一步不验平台回读**——那是 `fill` 之后 `verify` 的事。两步都过才算数：

1. `plan.py ready` 全绿；
2. `xhs.py fill` + `xhs.py verify` 回读一致（标题、正文长度、图片张数、话题标签数）。

只要有一条不过，就把没过的项摆给用户看，等指示，不要硬发。

### 授权范围内的动作

全绿之后一口气做完，中途不再找用户确认：

```bash
python3 <rednote-post>/scripts/xhs.py status          # 桥接就绪
python3 <rednote-post>/scripts/xhs.py reset           # 回到干净发布页
python3 <rednote-post>/scripts/xhs.py fill --dir <post-dir> --collection "<合集名>"
python3 <rednote-post>/scripts/xhs.py verify --dir <post-dir> --collection "<合集名>"
python3 <rednote-post>/scripts/xhs.py original        # 计划要求原创声明时
python3 <rednote-post>/scripts/xhs.py schedule "<YYYY-MM-DD HH:MM>"   # 用就绪检查给的空档
python3 <rednote-post>/scripts/xhs.py publish
python3 <rednote-post>/scripts/xhs.py check-published "<标题>"
```

发完回读一次平台状态（`xhs_state.py queue`）确认队列里真有这条，再刷新
`state/state.json` 与 `topics.md`。定时发布的笔记不在「已发布」页签，别看错地方。

### 什么情况下必须停下来问

- 检查有任一条不过。
- `posts/` 下有多篇候选，或这轮没说清要发哪一篇。
- 要改标题、正文、图片本身——那是内容决策，不是排期决策。
- 合集、可见范围、原创声明在计划和历史里都找不到依据。
- 平台回读对不上（话题标签数不符、图片张数不符）。
- 桥接不通、登错账号、页面要求二次验证。

宁可不发，也不要发一条说不清来路的笔记。

## 工作流

### 1. 定计划（只做一次，之后按需改）

```bash
python3 <skill>/scripts/plan.py init --workspace <workspace>
```

默认 workspace 是 `~/Documents/rednote`，也可以用 `$XHS_WORKSPACE` 指定。
`init` 只建骨架、不覆盖已有文件。字段口径、频率怎么选、栏目怎么配，见
[`references/plan-schema.md`](references/plan-schema.md)。

频率这一步必须问用户，不能自己定：能长期维持的频率取决于他每周真的能拿出多少时间。
给建议而不是给结论——见 [`references/plan-schema.md`](references/plan-schema.md) 的「频率怎么选」。
`publish_policy` 也要在这一步跟用户讲清楚，别默默替他打开自动发布。

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

### 6. 检查并发布

用户说"检查一下能发就发""把这条发掉"时，入口就是这一步——不必再走一遍全套报告。
跑 `plan.py ready`；全绿就按「发布授权」那一节做完，然后一句话汇报结果
（标题、几张图、合集、公开范围、原创声明、立即发还是定时到哪一档、noteId）。
没过就把不过的项列出来等指示。

## 什么时候该改计划

- 连续两周发不满计划 → 频率定高了，下调，不要靠更长的缓冲硬撑。
- 某种内容明显跑得比别的快 → 调 `pillars` 的配比。
- 账号要停更一段时间 → 在 `plan.json` 里加 `paused`，别让报告继续报"空档"。
- 不想让它自动发了 → 把 `publish_policy` 改回 `confirm`，立刻回到每次都问。

## 参考文件

- [`references/plan-schema.md`](references/plan-schema.md)——`plan.json`/`topics.md` 字段、
  workspace 布局、频率与素材积累量的口径、`publish_policy` 与就绪检查
- [`references/timing.md`](references/timing.md)——最佳发布时段：什么时候信自有数据、
  什么时候退回基线，以及为什么不能直接比阅读量
- [`references/reminders.md`](references/reminders.md)——定期提醒还是随问随答，
  以及 reminders 的创建模板
- [`references/platform-selectors.md`](references/platform-selectors.md)——创作者中心的
  真实选择器与字段（2026-10 实测）
