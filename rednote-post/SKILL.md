---
name: rednote-post
description: >-
  把一份素材（读书笔记、产品观察、教程、观点）做成小红书图文笔记并发到用户自己的账号：
  写标题与正文、生成 1080×1440 卡片图、本地实测排版、经用户确认后用浏览器桥接发布、发布后核验。
  当用户说"发小红书""发一篇笔记""rednote""做图文 post""把这份笔记发出去""配图发小红书"时激活。
  不适用于：只要文案不要发布、只要图片不要发布、无人值守或批量发布、
  发布到用户自己账号以外的位置（品牌号代运营、投流、多账号矩阵）。
metadata:
  short-description: 生成并发布小红书图文笔记（含发布前确认闸门）
---

# 小红书图文笔记

一条流水线：**文案 → 卡片图 → 实测 → 用户确认 → 发布 → 发布后核验**。

下面命令里的 `<skill>` 指本文件所在目录
（通常是 `${CODEX_HOME:-$HOME/.codex}/skills/rednote-post`）。
按字面写 `scripts/xhs.py` 会找不到——当前工作目录通常是用户的项目，不是 skill 目录。

## 三条铁律

1. **发布前必须拿到明确同意。** 把标题、**完整正文**、**每一张图**、合集、可见范围一次性摆给
   用户看，然后**停下等待**。用户没点头不许点发布；用户改了任何一项，重新摆一遍再问。
2. **发布是公开且难以撤回的动作。** 不替用户决定发什么、不自动补发、不批量发。
   账号／合集／可见范围以用户**当次**的指示为准，不沿用上一次。
3. **图片必须实测。** 渲染完看一眼不算数——用 `<skill>/scripts/render_cards.py` 量字号下限、溢出、
   页脚碰撞和孤字换行。曾有一版卡片因为辅助函数把每张卡自己的 CSS 丢掉了，全部以浏览器默认
   16px 渲染，肉眼看只觉得"字有点小"，看不出根因。

## 工作流

### 1. 定角度
能从上下文推断就别问。要确定的是：发什么、给谁看、是否指定合集、有没有现成图片。
选题时挑**对读者直接有用**的点——读者点赞收藏的是"这跟我有关"，不是"这个内容很好"。
文案结构与体量见 [`references/copywriting.md`](references/copywriting.md)。

### 2. 写标题与正文
标题 ≤ 20 字（超限 CLI 直接报错）；正文 ≤ 1000 字。正文末尾的 `#标签` 会被 CLI 自动识别成
话题。**正文最后一行单独放 `#标签`，用空格分隔**（如 `#意会认知 #波兰尼 #读书`），
不要另填 `--tags`。

**正文不能加粗**——平台不支持富文本，重音只能用 emoji／断行／符号，写法见
[`references/copywriting.md`](references/copywriting.md#正文没有加粗重音只能用这三招)，
别去试 `**字**`。

> 标签必须逐个从联想下拉里用**真点击**选中才会变成话题；上游 CLI 用的是合成 JS 点击，
> tiptap 会忽略，结果是只有最后一个标签生效。`fill` 已经绕开这条坏路径自己做，见
> [`references/publishing.md`](references/publishing.md#话题标签必须用真点击这是最容易踩的坑)。

### 3. 做卡片图
用 [`assets/card.css`](assets/card.css) 的令牌与版式起步，从
[`assets/cover.html`](assets/cover.html) 和 [`assets/card.html`](assets/card.html) 改内容。
尺寸固定 1080×1440（3:4，小红书信息流原生比例）。字号下限、卡片类型和素材处理见
[`references/cards.md`](references/cards.md)。

**强调色用 Volvo Safety Orange `#FD6408`（`--accent`），不要用绿色**；它是信号色，
只点短句与关键词，成段正文走 `--ink2`（橙色在暖纸底上只有约 2.6:1 对比度）。

**源素材要转成 RGB PNG 并确认方向**——手机拍的 HEIC 常带 EXIF 旋转，直接 `Image.open()` 会歪。

### 4. 本地实测

```bash
python3 <skill>/scripts/render_cards.py <post-dir>
```

它渲染 `manifest.json` 里列的每张卡，并检查：溢出、压页脚、正文区字号低于下限、孤字换行。
**任何一项不过就改版式，不要靠肉眼放行。** 修完重跑，直到全绿再进入下一步。

### 5. 用户确认（闸门）

把下面这些一次性摆出来，然后停：

- 标题
- **完整正文**（不要摘要，用户要逐字看）
- **每一张图**（用绝对路径的 Markdown 图片，让它在对话里直接显示）
- 合集、可见范围、原创声明状态

问一句明确的"确认发布吗"。**这一步不许跳过，也不许合并进上一步。**

### 6. 填表并回读核验

```bash
python3 <skill>/scripts/xhs.py fill   --dir <post-dir> --collection "<合集名>"
python3 <skill>/scripts/xhs.py verify --dir <post-dir> --collection "<合集名>"
```

`fill` 从 `<post-dir>/manifest.json` 取图片顺序，所以目录里有别的图也不会传错。

`verify` 从页面回读标题、正文长度、图片张数和合集名，并和本地文件比对。
**不要相信 `fill` 的成功输出**——它是"我以为填进去了"，`verify` 才是页面上的事实。
其中**话题标签数**（`[role=textbox] .tiptap-topic`）必须等于正文末尾的标签个数；
数量对不上就说明有标签退化成了普通文字。

标签没上去（改了标签、或想补几个）可以单独重跑，不用重新填整张表：

```bash
python3 <skill>/scripts/xhs.py tags --dir <post-dir>
```

### 7. 发布

```bash
python3 <skill>/scripts/xhs.py publish
```

点完按钮 CLI 可能报"未捕获到发布反馈"，这是**正常的模糊结果**，不代表失败。以页面状态为准：
URL 出现 `published=true` 且表单被清空 = 已提交。

### 8. 发布后核验

```bash
python3 <skill>/scripts/xhs.py check-published "<标题>"
```

到 `creator.xiaohongshu.com/new/note-manager` 确认：出现在**已发布**、不在**审核中**。
把结论告诉用户（已发布／审核中／未找到），不要只报"发布完成"。

## 修订循环

用户几乎一定会改文案或图片。改完的固定动作是：

1. 重新渲染 + 重跑 `render_cards.py`；
2. **重新导航到干净的发布页**（`xhs.py reset`），再 `fill`——否则旧图会残留，
   图片会叠加成 10 张；
3. 重跑 `verify`，重新摆给用户确认。

## post 目录约定

一个笔记一个目录，固定这几个名字，脚本就能直接跑：

```
<post-dir>/
|-- manifest.json      图片清单与渲染参数（render_cards.py 读）
|-- title.txt          标题，≤20 字
|-- body.txt           正文，≤1000 字
|-- build/             卡片 HTML + 复制的 card.css
`-- assets/            原图、处理后的素材
```

`body.txt` 只保留一个当前版本。**不要**留 `body-v2.txt` 这种并存版本——
`fill` 默认读 `body.txt`，改完忘了同步就会发出旧文案。

## 环境

发布依赖浏览器桥接（Chrome 扩展 + 本地 WebSocket 服务）。首次配置、选择器、故障排查见
[`references/publishing.md`](references/publishing.md)。跑之前先确认桥接就绪：

```bash
python3 <skill>/scripts/xhs.py status
```

`status` 不通就先按 `references/publishing.md` 里的 `setup_bridge.sh` 配好，**不要**在桥接
未就绪时硬撞 `fill`。

## 参考文件

- [`references/copywriting.md`](references/copywriting.md)——标题公式、正文骨架、字数与标签规则
- [`references/cards.md`](references/cards.md)——1080×1440 卡片系统、字号下限、素材处理
- [`references/publishing.md`](references/publishing.md)——桥接环境、选择器、故障排查、发布后核验
