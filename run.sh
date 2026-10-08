#!/usr/bin/env bash
# 一拍迹合 · 一键启动（macOS / Linux）
# 创建虚拟环境 → 安装依赖 → 启动服务并打开浏览器
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || { echo "❌ 需要 Python 3.10 及以上版本：https://www.python.org/downloads/"; exit 1; }

if [ ! -x .venv/bin/python ]; then
  echo "📦 创建虚拟环境 .venv ..."
  "$PY" -m venv .venv
fi

# 官方源装不上（国内网络常见）时自动改用清华镜像
pip_install() {
  .venv/bin/python -m pip install --disable-pip-version-check "$@" \
    || .venv/bin/python -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple "$@"
}

if ! .venv/bin/python -c "import flask, flask_cors, dotenv, openai, requests" 2>/dev/null; then
  echo "📦 安装依赖（首次约 1 分钟）..."
  pip_install -q --upgrade pip
  pip_install -q -r requirements.txt
fi

# 视频分析组件（本地语音转写 + 截取画面）：可选，装不上不影响其他功能；设置 SKIP_VIDEO_DEPS=1 可跳过
if [ "${SKIP_VIDEO_DEPS:-0}" != "1" ] && ! .venv/bin/python -c "import faster_whisper, av, PIL" 2>/dev/null; then
  echo "🎧 安装视频分析组件（本地语音转写，约 100MB，只需一次）..."
  pip_install -r requirements-video.txt || echo "⚠️  视频分析组件没装上，将跳过「听语音」，其他功能不受影响"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "📝 已生成 .env（全部留空即可运行；填上 DEEPSEEK_API_KEY 即可开启大模型、联网搜索和看画面）"
fi

export OPEN_BROWSER="${OPEN_BROWSER:-1}"
exec .venv/bin/python app.py
