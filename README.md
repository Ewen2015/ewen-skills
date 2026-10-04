# ewen-skills

The most important skills Ewen found for his personal AI agent.

## Skills

| Skill | 用途 |
| --- | --- |
| [`read-a-book`](./read-a-book) | 用《如何阅读一本书》的方法读一本书：检视阅读 → 分析阅读 → 主题阅读，梳理背景脉络与影响，产出结构化读书笔记；可按需压成**一页纸（one-pager）**。 |
| [`scandinavian-style`](./scandinavian-style) | 斯堪的纳维亚风格的设计系统：16:9 版式网格、字号层级、页脚规范、配色与图表规则，附可直接改的单页 HTML 模板，以及**密集单页（one-pager）**三栏模式与实测校验脚本。不带任何品牌资产。 |
| [`rednote-post`](./rednote-post) | 把一份素材做成小红书图文笔记并发到自己的账号：写标题与正文、生成 1080×1440 卡片图、**实测**排版（字号下限/溢出/压页脚/孤字换行）、经用户确认后用浏览器桥接发布并回读核验。含卡片模板、渲染校验脚本与发布 CLI。 |

## 安装

把 skill 目录复制到 Codex 的 skills 目录：

```bash
cp -R read-a-book scandinavian-style rednote-post "${CODEX_HOME:-$HOME/.codex}/skills/"
```

开发时也可以直接软链，改仓库即生效：

```bash
ln -sfn "$PWD/scandinavian-style" "${CODEX_HOME:-$HOME/.codex}/skills/scandinavian-style"
```
