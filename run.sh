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

if ! .venv/bin/python -c "import flask, flask_cors, dotenv, openai, requests" 2>/dev/null; then
  echo "📦 安装依赖（首次约 1 分钟）..."
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "📝 已生成 .env（全部留空即可运行；需要 AI 能力时再填写 Key）"
fi

export OPEN_BROWSER="${OPEN_BROWSER:-1}"
exec .venv/bin/python app.py
