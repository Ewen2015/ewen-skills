#!/usr/bin/env bash
# One-time setup for the 小红书 browser bridge.
#
#   bash scripts/setup_bridge.sh
#
# Clones autoclaw-cc/xiaohongshu-skills, creates its venv, and installs deps.
# Then prints the two manual steps (load the extension, log in).
set -euo pipefail

REPO_URL="https://github.com/autoclaw-cc/xiaohongshu-skills.git"
TOP="${XHS_SKILLS_DIR:-/tmp/xhs-skills-repo}"

echo "==> 仓库位置：$TOP"
case "$TOP" in
  /tmp/*|/var/folders/*)
    echo "    注意：/tmp 会被系统清理。长期使用请设 XHS_SKILLS_DIR 到持久目录。" ;;
esac

if [ -d "$TOP/.git" ]; then
  echo "==> 已存在，跳过克隆"
else
  git clone --depth 1 "$REPO_URL" "$TOP"
fi

echo "==> 创建 venv"
if command -v uv >/dev/null 2>&1; then
  uv venv "$TOP/.venv" >/dev/null
  PY="$TOP/.venv/bin/python"
  uv pip install --python "$PY" -q websockets==13.1
  # The repo only pins websockets>=12.0, so a plain install grabs 16.x, whose
  # handshake the extension cannot complete (server says "connected", the CLI
  # then dies with InvalidMessage). Pin it explicitly.
  uv pip install --python "$PY" -q python-socks requests
else
  python3 -m venv "$TOP/.venv"
  PY="$TOP/.venv/bin/python"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q "websockets==13.1" python-socks requests
fi

echo "==> 校验"
"$PY" - <<'PY'
import websockets, sys
v = getattr(websockets, "__version__", "?")
print(f"    websockets {v}")
if not v.startswith("13."):
    sys.exit("    ✗ 必须是 13.x——其他版本握手会失败，见 references/publishing.md")
print("    ✓ 依赖就绪")
PY

cat <<EOF

还需要手动做两件事（脚本不能替你做）：

  1. Chrome 打开 chrome://extensions → 开启开发者模式 →
     「加载已解压的扩展程序」→ 选择：
         $TOP/extension

  2. 在 Chrome 里登录小红书创作服务平台：
         https://creator.xiaohongshu.com

完成后验证：
     python3 $(cd "$(dirname "$0")" && pwd)/xhs.py status
EOF
