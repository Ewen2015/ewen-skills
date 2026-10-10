# 待读队列

机器维护：`~/.local/share/book-fetch/queue.json`（唯一事实源）
人读的渲染：`~/Documents/reading-queue.md`（**别手改，会被下次写入覆盖**）

这道队列对应 `rsi-reading` 的 **R10：找书这一步进队列（S1）**。
它让"下一本读什么"从即兴变成排期，也让 S1 的输入和后续环节对得上。

## 状态

| 状态 | 含义 |
| --- | --- |
| `want` | 想读，还没拿到文件 |
| `fetched` | 已拿到文件 |
| `reading` | 在读（`read-a-book` 开始时改过来） |
| `done` | 已读完（笔记已进 `second-brain`） |
| `dropped` | 放弃，附一句原因 |

## 条目字段

```json
{
  "title": "Pale Blue Dot",
  "author": "Carl Sagan",
  "file": "/Users/ewen/Documents/books/Pale Blue Dot - Carl Sagan.epub",
  "result_id": "…",
  "status": "fetched",
  "note": "为什么读这本",
  "added_at": "2026-10-05"
}
```

## 用法

```bash
python3 <skill>/scripts/fetch.py queue add --title "…" --author "…" --file "…" --note "…"
python3 <skill>/scripts/fetch.py queue list
python3 <skill>/scripts/fetch.py queue set --title "…" --status reading
python3 <skill>/scripts/fetch.py queue --title "…" --status done --note "成品出处" set
```

`download --queue` 会自动把选中的那份登记为 `fetched`；
用户直接交来的文件走 `adopt`（验可达 → 只复制不移动 → 洗名字 → 登记），别手动 `cp`。

`add` 是**按书名就地更新**，不是无脑追加：同一本书只会有一行，重复登记只会刷新它的
状态与备注（空字段不覆盖已有值）。所以「同一本被登记两次」不会让队列长出两条。

`set` 同理**只改显式传入的字段**：`--status reading` 不会顺手把备注抹掉；
一个字段都不给会直接报错退出，不做事。

## 队列的健康线

- **待读永远 ≥ 3 本**：队列空了，下一次"读什么"就只能即兴。
- `want` 条目要写一句**为什么读**——没有理由的条目到期就该 `dropped`，
  否则队列会变成收藏夹。

这两条和 `rsi-reading` 的 R1（选题池见底）是同一个毛病在上下游的两端：
**没有缓冲，就会在最忙的时候断掉。**
