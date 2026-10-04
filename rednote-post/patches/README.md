# 上游补丁存档

`rednote-post` 依赖一份 `autoclaw-cc/xiaohongshu-skills` 的 checkout（路径由
`XHS_SKILLS_DIR` 指定），但那份 checkout 不在本仓库里。本地改过的东西一旦重装或
重新 clone 就没了，所以把补丁存一份在这里。

## bridge-command-timeout.patch

**改的什么**：把 bridge 命令超时从硬编码 90s 改成可配置，默认 300s。

```python
# scripts/xhs/bridge.py
raw = ws.recv(timeout=float(os.environ.get("XHS_CMD_TIMEOUT", "300")))
# scripts/bridge_server.py
CMD_TIMEOUT = float(os.environ.get("XHS_CMD_TIMEOUT", "300"))
```

**为什么需要**：正文是逐字输入的，~900 字带 8 个话题标签时 `fill` 会跑过 90s。
旧行为是 CLI 报超时失败、页面上其实已经填好了——重跑一次就把内容填两遍。

**状态**：已提 PR → https://github.com/autoclaw-cc/xiaohongshu-skills/pull/102
（上游合入后这个补丁就可以删了）

**基线**：`autoclaw-cc/xiaohongshu-skills` @ `b043748`

**怎么打**：

```bash
cd "$XHS_SKILLS_DIR"            # 那份 xiaohongshu-skills checkout
git am <path-to>/bridge-command-timeout.patch
```

打不上（上游已经改过这段）就用 `git apply --3way`，或者干脆手改——
改动就上面那两行加一个环境变量读取。

不想打补丁的话，把 `<post-dir>` 的正文压到 900 字以内通常也能绕开，
但那是在给一个本可以修掉的限制让路。
