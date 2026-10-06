# 计划与库存的口径

## workspace 布局

```
<workspace>/
|-- plan.json      发布计划：频率、时段、栏目、目标（唯一必填项）
|-- topics.md      选题池，一行一条
|-- posts/         每个笔记一个 rednote-post 目录
`-- state/         xhs_state.py 的输出（可选）
```

默认 `<workspace>` 是 `~/Documents/rednote`，可用 `$XHS_WORKSPACE` 覆盖。
`posts/` 下的目录直接沿用 `rednote-post` 的 post 目录约定
（`manifest.json` / `title.txt` / `body.txt` / 成图），两个 skill 才能共用同一批文件。

## state/queue.json：先确认它是"全部"，再拿它判断

`xhs_state.py` 扫出来的队列是**唯一**的"平台上到底排了什么"的输入，
所以它只要少读一篇，后面的"有没有空档""要不要补一篇"就全是错的。判断前先看这三个字段：

| 字段 | 含义 |
| --- | --- |
| `scroll_exhausted` | **列表确实到底**才为 `true`。页面还挂着「正在加载」时一律为 `false` |
| `partial` | `true` = 这份扫描不完整，**不能**据此判断排期 |
| `expected_total` | 从 tab 标签读到的总数（如「全部 255」），用来和 `cards_scanned` 对账 |

**`partial: true` 时不要输出任何缺口结论**，先按提示把 Chrome 切到前台重扫。

笔记列表是虚拟滚动的：首屏只挂约 10 张，往下要靠滚动触发下一页。
而**这个请求在 Chrome 窗口不在前台时根本不发**（`document.hasFocus()` 为 `false`），
卡片数会一直不变——很容易被误读成"列表到底了"。
2026-10-06 就是这么漏掉 10-07、10-08 两篇已排期笔记、还报了个 `scroll_exhausted: true` 的。
另一条老坑：真正的滚动容器不是 window（window 的 `scrollHeight == clientHeight`，滚不动），
是 `.note-card` 的可滚动祖先（`.list-container-box` / `.microapp-container`）。

## plan.json

```json
{
  "account": "司马读书",
  "cadence": {
    "posts_per_week": 2,
    "weekdays": [2, 6],
    "slots": ["20:00"]
  },
  "pillars": [
    {"name": "读书笔记", "share": 0.6},
    {"name": "思维模型", "share": 0.4}
  ],
  "targets": {"ready_weeks": 2, "semi_weeks": 4, "topic_weeks": 6},
  "paused": false,
  "publish_policy": "confirm"
}
```

| 字段 | 含义 |
| --- | --- |
| `cadence.posts_per_week` | 每周发几篇。**排期里所有"够不够"的判断都以它为分母。** |
| `cadence.weekdays` | `0`=周一 … `6`=周日。用数字，不用中文，脚本直接读 |
| `cadence.slots` | 当天几点发，`"HH:MM"`。一天多个时段就写多个 |
| `pillars` | 栏目与配比。只在写文案时做参照，排期计算不强制 |
| `targets.*_weeks` | 三档缓冲的目标周数，理由见下 |
| `paused` | 停更期。为 `true` 时报告不该再报"空档" |
| `publish_policy` | `"auto"` 或 `"confirm"`。`auto` 时 `plan.py ready` 全绿即可直接发布，不再问用户；缺失按 `confirm` 处理。见「发布授权」 |

## 频率怎么选

频率是**能力问题，不是目标问题**：写一条读书笔记（读→笔记→卡片→实测）通常要好几个小时，
所以上限由"每周真的能拿出几个这样的时间段"决定，不由"想涨粉多快"决定。

给建议时按这个顺序问用户，然后让他自己定：

1. 每周能稳定拿出几个完整时段做内容？
2. 现有成品的质量，一周最多出几条不会掉水平？
3. 过去四周实际发了几条？（低于计划的频率就是定高了）

参考区间：**每周 1–2 篇**能长期维持；3 篇以上通常需要已有素材流水线或批量生产。
宁可定 1 篇发满，也不要定 3 篇发两周就断。

## 素材积累量的口径

| 层级 | 目标 | 为什么是这个数 |
| --- | --- | --- |
| 可直接发（过实测、能立刻排） | 频率 × **2 周** | 扛一次出差、生病或平台卡审核。低于 1 周就是随时会断更 |
| 半成品（有选题、有素材，没做卡片） | 频率 × **4 周** | 从半成品到成品还要几小时，留出这条流水线的在制品 |
| 选题池（未用） | 频率 × **6 周** | 一条成品通常要废掉一两次选题，池子浅了就会临时凑内容 |

这三档是**缓冲**不是**目标产量**：超过目标不用庆祝，掉到目标以下的动作是"去补"，
不是"把频率降下来"——除非连续两周都发不满，那才是频率定高了。

## topics.md

```markdown
- [ ] 为什么读了很多书还是做不好决定
- [x] 地图不等于疆域（已发 2026-10-05）
```

`- [ ]` 计入未用选题，`- [x]` 计入已用。行内其他文字随意，脚本只数这两个前缀。

## 成品怎么判定

`posts/<name>/` 同时满足三条才算"可直接发"：`title.txt` 非空、`body.txt` 非空、
目录下有至少一张 `.png/.jpg/.jpeg/.webp`。缺哪条就在 `missing` 里列出来。

这是**有意从宽**的判据：`report` 不重跑 `render_cards.py`，所以"过了实测"这件事它不验，
只用来算库存。要动真格发布时走 `plan.py ready`——那一条会真的跑一遍实测。

## 发布授权与就绪检查

`publish_policy` 决定本 skill 能不能自己拍板发布：

| 取值 | 行为 |
| --- | --- |
| `"auto"` | `plan.py ready` 全绿 → 直接发布，不再回头确认。授权只覆盖"发不发、发哪一档" |
| `"confirm"` 或缺失 | 每次都回到 `rednote-post` 的确认闸门，把标题/正文/图片摆给用户看完再发 |

```bash
python3 plan.py ready --workspace W --post <post-dir> [--state F] [--json]
```

退出码 `0` 全绿，`1` 有不过的项。它验八条：计划未停更、已授权、成品唯一、交付物齐全、
标题 ≤ 20 字、正文末行是标签行、`render_cards.py` 全绿、有空闲时段。正文超过 1000 字
只算提醒（平台本身也只警告）。

它**不验平台回读**——那是 `fill` 之后 `verify` 的事。`ready` 全绿 + `verify` 一致，
两条都过才允许自动发布。任一条不过都得停下来问用户。
