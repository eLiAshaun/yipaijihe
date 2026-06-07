#!/bin/bash

# 旅搭子 - 启动脚本

echo "🚀 启动旅搭子..."
echo ""

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python3，请先安装"
    exit 1
fi

# 检查依赖
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 安装依赖..."
    pip3 install -r requirements.txt
fi

# 检查 .env
if [ ! -f .env ]; then
    echo "📝 未找到 .env 文件，使用 Demo 模式（无 LLM）"
    echo "   如需 LLM 支持，请复制 .env.example 为 .env 并配置 API Key"
    echo ""
fi

echo "✅ 启动完成！"
echo "🌐 访问 http://localhost:5000"
echo ""

python3 app.py
