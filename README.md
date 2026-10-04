# ewen-skills

The most important skills Ewen found for his personal AI agent.

## Skills

| Skill | 用途 | 图片示例 |
| --- | --- | --- |
| [`read-a-book`](./read-a-book) | 用《如何阅读一本书》的方法读一本书：检视阅读 → 分析阅读 → 主题阅读，梳理背景脉络与影响，产出结构化读书笔记；可按需压成**一页纸（one-pager）**。 | <img src="docs/skills/read-a-book.png" width="260" alt="《思考的框架》三册一页纸读书笔记：三栏分别放这本书在回答什么、三册结构与 48 个模型、上游与下游的隐身人"> |
| [`scandinavian-style`](./scandinavian-style) | 斯堪的纳维亚风格的设计系统：16:9 版式网格、字号层级、页脚规范、配色与图表规则，附可直接改的单页 HTML 模板，以及**密集单页（one-pager）**三栏模式与实测校验脚本。不带任何品牌资产。 | <img src="docs/skills/scandinavian-style.png" width="260" alt="16:9 单页模板渲染结果：章节标签、32pt 标题、正文与 5 节点时间线，右侧边栏列表，底部四元素页脚"> |
| [`rednote-post`](./rednote-post) | 把一份素材做成小红书图文笔记并发到自己的账号：写标题与正文、生成 1080×1440 卡片图、**实测**排版（字号下限/溢出/压页脚/孤字换行）、经用户确认后用浏览器桥接发布并回读核验。含卡片模板、渲染校验脚本与发布 CLI。 | <img src="docs/skills/rednote-post.png" width="260" alt="小红书图文的封面与两张内页卡片：你不是不够聪明，是手里的模型太少"> |

## 安装

把 skill 目录复制到 Codex 的 skills 目录：

```bash
cp -R read-a-book scandinavian-style rednote-post "${CODEX_HOME:-$HOME/.codex}/skills/"
```

开发时也可以直接软链，改仓库即生效：

```bash
ln -sfn "$PWD/scandinavian-style" "${CODEX_HOME:-$HOME/.codex}/skills/scandinavian-style"
```
