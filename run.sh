#!/usr/bin/env bash
# 一拍迹合 · 一键启动：创建虚拟环境 → 安装依赖 → 启动服务
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "❌ 未找到 python3，请先安装 Python 3.10+"; exit 1; }

if [ ! -d .venv ]; then
  echo "📦 创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import flask" 2>/dev/null; then
  echo "📦 安装依赖 ..."
  pip install -q -r requirements.txt
fi

if [ ! -f .env ]; then
  echo "📝 未找到 .env，将以 Demo 模式运行（无 LLM / 语音转写，景点与路线使用内置数据）"
  echo "   需要 AI 能力请：cp .env.example .env 并填写 Key"
fi

echo "🌐 http://localhost:${FLASK_PORT:-5000}"
exec python app.py
