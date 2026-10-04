# ewen-skills

The most important skills Ewen found for his personal AI agent.

## Skills

| Skill | 用途 | 图片示例 |
| --- | --- | --- |
| [`read-a-book`](./read-a-book) | 用《如何阅读一本书》的方法读一本书：检视阅读 → 分析阅读 → 主题阅读，梳理背景脉络与影响，产出结构化读书笔记；可按需压成**一页纸（one-pager）**。 | <img src="docs/skills/read-a-book.png" width="260" alt="《思考的框架》三册一页纸读书笔记：三栏分别放这本书在回答什么、三册结构与 48 个模型、上游与下游的隐身人"> |
| [`scandinavian-style`](./scandinavian-style) | 斯堪的纳维亚风格的设计系统：16:9 版式网格、字号层级、页脚规范、配色与图表规则，附可直接改的单页 HTML 模板，以及**密集单页（one-pager）**三栏模式与实测校验脚本。不带任何品牌资产。 | <img src="docs/skills/scandinavian-style.png" width="260" alt="16:9 单页模板渲染结果：章节标签、32pt 标题、正文与 5 节点时间线，右侧边栏列表，底部四元素页脚"> |
| [`rednote-post`](./rednote-post) | 把一份素材做成小红书图文笔记并发到自己的账号：写标题与正文、生成 1080×1440 卡片图、**实测**排版（字号下限/溢出/压页脚/孤字换行）、经用户确认后用浏览器桥接发布并回读核验。含卡片模板、渲染校验脚本与发布 CLI。 | <img src="docs/skills/rednote-post.png" width="260" alt="小红书图文的封面与两张内页卡片：你不是不够聪明，是手里的模型太少"> |
| [`rednote-assistant`](./rednote-assistant) | 小红书发布排期助理：定更新频率与发布时段、看平台上有没有未来定时发布的笔记、盘草稿箱、算现有成品能撑几周、指出排期缺口、按账号自己的历史数据挑最佳发布时间、给素材积累量目标，并判断该用定期提醒还是随问随答。**只排期，不写不发**——文案与发布走 `rednote-post`。 | <img src="docs/skills/rednote-assistant.png" width="260" alt="排期体检报告：每周 2 篇的计划下，未来 3 周排期表标出 5 个空档与已定时的笔记，并给出素材积累量目标与提醒建议"> |
| [`second-brain`](./second-brain) | 用读过的书回答一个具体问题：从书库里挑出真正相关的 1–2 本，用它们的思想视角参与思考，每个观点都带出处与作者。书库按「index 当注册表、卡片按需加载」组织——一次问答约 3–5K tokens，而不是把整个书库塞进上下文。含检索（`recall`）、索引生成与体检脚本。 | — |
| [`rsi-reading`](./rsi-reading) | 把「读书」这条链当成闭环做递归自我改进：度量 read-a-book → 小红书发布 → second-brain 收录 → 下次取用 的流水线，找断点、给改进项排优先级、跑一次只改一个变量的最小试验并记账。附只读观测仪（`rsi.py`：闭环覆盖、断点、成品与平台数据对账、改进项队列）与三份活文档（当前地图、指标口径、改进项队列）。**它不读书、不写笔记、不发帖**——改的是流程本身。 | — |

## 安装

把 skill 目录复制到 Codex 的 skills 目录：

```bash
cp -R read-a-book scandinavian-style rednote-post rednote-assistant second-brain rsi-reading \
  "${CODEX_HOME:-$HOME/.codex}/skills/"
```

开发时也可以直接软链，改仓库即生效：

```bash
ln -sfn "$PWD/scandinavian-style" "${CODEX_HOME:-$HOME/.codex}/skills/scandinavian-style"
```
