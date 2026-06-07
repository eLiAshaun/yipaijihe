#!/bin/bash
# Agent Reach 本地安装脚本
# 用法: bash agent-reach/setup.sh
#
# 新用户 clone 后执行此脚本即可，会自动：
#   1. 安装系统依赖（ffmpeg, uv, mcporter）
#   2. 创建 douyin-mcp-server 虚拟环境
#   3. 从 .env 读取 API Key，生成 config/mcporter.json
#   4. 安装 xhs-cli（小红书）

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Agent Reach 安装 ==="
echo "项目目录: $PROJECT_DIR"

# ──────────────────────────────────────
# 1. 安装系统依赖
# ──────────────────────────────────────
echo ""
echo "--- 系统依赖 ---"

# ffmpeg
if command -v ffmpeg >/dev/null 2>&1; then
    echo "✅ ffmpeg ($(ffmpeg -version 2>&1 | head -1 | awk '{print $3}'))"
else
    echo "📦 安装 ffmpeg..."
    if command -v brew >/dev/null 2>&1; then
        brew install ffmpeg
    elif command -v apt >/dev/null 2>&1; then
        sudo apt install -y ffmpeg
    else
        echo "❌ 请手动安装 ffmpeg: https://ffmpeg.org/download.html"
        exit 1
    fi
    echo "✅ ffmpeg 已安装"
fi

# uv (Python 包管理)
if command -v uv >/dev/null 2>&1; then
    echo "✅ uv ($(uv --version 2>&1 | awk '{print $2}'))"
else
    echo "📦 安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo "✅ uv 已安装"
fi

# mcporter
if command -v mcporter >/dev/null 2>&1; then
    echo "✅ mcporter"
else
    echo "📦 安装 mcporter..."
    if command -v brew >/dev/null 2>&1; then
        brew install mcporter
    else
        npm install -g mcporter
    fi
    echo "✅ mcporter 已安装"
fi

# ──────────────────────────────────────
# 2. 安装 douyin-mcp-server
# ──────────────────────────────────────
echo ""
echo "--- 抖音 MCP Server ---"
cd "$SCRIPT_DIR/tools/douyin-mcp-server"
uv sync 2>&1 | tail -1
echo "✅ douyin-mcp-server 依赖安装完成"

# ──────────────────────────────────────
# 3. 安装 xhs-cli（小红书）
# ──────────────────────────────────────
echo ""
echo "--- 小红书 CLI ---"
if command -v xhs >/dev/null 2>&1; then
    echo "✅ xhs-cli 已安装 ($(xhs --version 2>&1))"
else
    echo "📦 安装 xhs-cli..."
    if command -v pipx >/dev/null 2>&1; then
        pipx install xiaohongshu-cli
    else
        uv tool install xiaohongshu-cli
    fi
    echo "✅ xhs-cli 已安装"
fi

# ──────────────────────────────────────
# 4. 生成 mcporter.json
# ──────────────────────────────────────
echo ""
echo "--- 生成 mcporter 配置 ---"

# 从 .env 读取 MIMO_API_KEY
MIMO_KEY=""
if [ -f "$PROJECT_DIR/.env" ]; then
    MIMO_KEY=$(grep "^MIMO_API_KEY=" "$PROJECT_DIR/.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
fi

if [ -z "$MIMO_KEY" ] || [ "$MIMO_KEY" = "your-mimo-api-key-here" ]; then
    echo "⚠️  未找到有效的 MIMO_API_KEY"
    echo "   请编辑 $PROJECT_DIR/.env 填入 Key，然后重新运行此脚本"
    echo "   获取地址: https://token-plan-cn.xiaomimimo.com"
    MIMO_KEY="YOUR_MIMO_API_KEY_HERE"
else
    echo "✅ MIMO_API_KEY 已读取"
fi

# 从模板生成 mcporter.json
TEMPLATE="$PROJECT_DIR/config/mcporter.json.template"
TARGET="$PROJECT_DIR/config/mcporter.json"

if [ -f "$TEMPLATE" ]; then
    sed \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "s|__MIMO_API_KEY__|$MIMO_KEY|g" \
        "$TEMPLATE" > "$TARGET"
    echo "✅ mcporter.json 已生成"
else
    echo "❌ 模板文件不存在: $TEMPLATE"
    exit 1
fi

# ──────────────────────────────────────
# 5. 验证
# ──────────────────────────────────────
echo ""
echo "--- 验证 ---"
cd "$PROJECT_DIR"

if mcporter config list 2>/dev/null | grep -q "douyin"; then
    echo "✅ douyin MCP 已注册"
else
    echo "❌ douyin MCP 注册失败，请检查 config/mcporter.json"
fi

if mcporter config list 2>/dev/null | grep -q "exa"; then
    echo "✅ exa 搜索已注册"
fi

# ──────────────────────────────────────
# 完成
# ──────────────────────────────────────
echo ""
echo "========================================="
echo "  ✅ 安装完成！"
echo "========================================="
echo ""
echo "使用方式:"
echo "  # 抖音视频解析（无需 API Key）"
echo "  mcporter call douyin.parse_douyin_video_info share_link='https://v.douyin.com/xxx/'"
echo ""
echo "  # 抖音语音转文字（需要 MIMO_API_KEY）"
echo "  mcporter call douyin.extract_douyin_text share_link='https://v.douyin.com/xxx/'"
echo ""
echo "  # 小红书"
echo "  xhs search '关键词'"
echo ""
echo "  # 全网搜索"
echo "  mcporter call exa.web_search_exa query='关键词'"
