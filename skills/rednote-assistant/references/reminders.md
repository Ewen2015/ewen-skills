# 定期提醒还是随问随答

`plan.py report` 会直接给结论，判定规则是：

| 成品缓冲 | 频率 | 结论 |
| --- | --- | --- |
| < 1 周 | 任意 | **cron**：随时会断更 |
| 1 周 ~ 目标（默认 2 周） | 任意 | **cron**：低于缓冲目标 |
| ≥ 4 周且 ≤ 1 篇/周 | — | **ad-hoc**：定期提醒只会变成噪音 |
| 其他 | — | **ad-hoc**：等掉到目标线以下再开 |

判定逻辑在 `scripts/plan.py: reminder_advice()`，要改口径就改那里，不要在报告里手算。

## 定期提醒（cron / heartbeat）

用 automation 工具创建，**不要手写 RRULE 字符串**，也不要把调度细节写进 prompt。
挂在当前会话上的周期任务用 heartbeat；需要独立跑、或用户希望它出现在项目里的用 cron
（cron 需要 project id，先用 list_projects 找到目标项目）。

prompt 模板（把 `<workspace>` 换掉）：

```
每周做一次小红书排期体检，工作目录 <workspace>。

先看 <workspace>/state/state.json 的时间戳，超过 3 天就先重跑
`python3 <skill>/scripts/xhs_state.py all --out <workspace>/state/state.json`，
然后跑 `python3 <skill>/scripts/plan.py report --workspace <workspace> --state <workspace>/state/state.json --weeks 2`。

只在下面任一情况出现时才提醒我，其余情况保持安静、不要发消息：
1. 未来 7 天出现空档；
2. 可直接发的成品少于 2 篇；
3. 有定时发布的笔记卡在审核中，或定时时间已经过了还没发出去。

提醒时只说：空档日期、还缺几篇、需要我做什么决定。
不要自动改 plan.json，不要写文案，不要发布任何内容。
```

「其余情况保持安静」这句不能删：每周都推一条"一切正常"的提醒，用户很快就不看了，
真出问题时也照样忽略。

## 随问随答（ad-hoc）

缓冲充足时就别建定期任务。用户问的时候跑一次 `report` 即可——
但**平台状态会过期**，`state/state.json` 超过 3 天就重扫一遍再答，
不然会把上周的定时队列当成现在的。

## 该顺带提醒的两件事

跑完报告如果看到下面情况，主动说一句，但都不用动手：

- 草稿箱里躺着草稿 → 提醒它存在**浏览器本地**，清浏览器数据就没；要留就落成 `posts/` 里的成品。
- 定时发布时间在计划时段之外（报告里的「已定时·计划外」）→ 问用户是有意为之还是排错了。
