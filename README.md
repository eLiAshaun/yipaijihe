# 旅搭子 — AI 旅行搭子

> 抖音 AI 创变者黑客松 2026 参赛作品

一个基于 MBTI 性格测试的 AI 旅行搭子，帮你规划上海旅行行程。

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/eLiAshaun/douyinai2026.git
cd douyinai2026

# 2. 创建虚拟环境 & 安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key

# 4. 安装 Agent Reach（抖音/小红书等工具）
bash agent-reach/setup.sh

# 5. 启动
bash run.sh
# 或直接 python3 app.py
```

访问 http://localhost:5000

## Agent Reach — 互联网接入

项目集成了 [Agent Reach](https://github.com/Panniantong/agent-reach)，提供抖音、小红书等平台的接入能力。

### 已接入渠道

| 渠道 | 工具 | 用途 | 需要配置 |
|------|------|------|----------|
| 🎵 抖音 | douyin-mcp-server | 视频解析、无水印下载、语音转文字 | 语音转文字需要 MIMO_API_KEY |
| 📕 小红书 | xhs-cli | 搜索、阅读、发帖 | 需要 `xhs login` |
| 🔍 全网搜索 | Exa (mcporter) | 语义搜索 | 免费，开箱即用 |

### 使用方式

**抖音**（通过 mcporter 调用）：

```bash
# 解析视频信息（无需 API Key）
mcporter call douyin.parse_douyin_video_info share_link='https://v.douyin.com/xxx/'

# 获取无水印下载链接（无需 API Key）
mcporter call douyin.get_douyin_download_link share_link='https://v.douyin.com/xxx/'

# 语音转文字（需要 MIMO_API_KEY）
mcporter call douyin.extract_douyin_text share_link='https://v.douyin.com/xxx/'
```

**小红书**：

```bash
xhs search '上海旅游攻略'   # 搜索
xhs login                   # 首次使用需登录
```

**全网搜索**：

```bash
mcporter call exa.web_search_exa query='上海外滩附近美食'
```

### 配置说明

在 `.env` 中配置：

```bash
# MiMo ASR（抖音语音转文字）
MIMO_API_KEY=tp-xxxxx                              # 获取: https://token-plan-cn.xiaomimimo.com
MIMO_API_BASE=https://token-plan-cn.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.5-asr

# 可选：ASR 性能参数
MIMO_ASR_REQUEST_TIMEOUT=120
MIMO_ASR_MAX_RETRIES=1
MIMO_ASR_SEGMENT_DURATION=90
MIMO_ASR_MAX_WORKERS=3
MIMO_ASR_GLOBAL_MAX_CONCURRENT=4
MIMO_ASR_AUDIO_BITRATE=64k
MIMO_ASR_SAMPLE_RATE=16000
MIMO_ASR_CHANNELS=1

# 可选：LLM 请求参数
LLM_TIMEOUT=60
LLM_MAX_RETRIES=1
```

`config/mcporter.json` 由 `agent-reach/setup.sh` 根据 `.env` 自动生成，也可以手动编辑。

### 语音转文字技术栈

- **模型**: 小米 MiMo-v2.5-ASR（中文识别效果好）
- **流程**: 视频下载 → ffmpeg 提取轻量音频(16kHz/mono/64kbps) → 分段(90s) → base64 编码 → MiMo ASR
- **优化**: system prompt 引导逐字转录、temperature=0 确定性输出、自动分段处理长视频

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/auth/*` | — | 用户认证 |
| `/api/mbti/*` | — | MBTI 测试 |
| `/api/locations/*` | — | 上海地点数据 |
| `/api/itinerary/*` | — | 行程规划 |
| `/api/chat/*` | — | AI 对话 |

## 项目结构

```
├── app.py                          # Flask 入口
├── run.sh                          # 启动脚本
├── requirements.txt                # Python 依赖
├── .env                            # 环境变量（API Key 等）
├── .env.example                    # 环境变量模板
├── backend/
│   ├── config.py                   # 配置
│   ├── database.py                 # 数据库初始化
│   ├── routes/                     # API 路由
│   ├── services/                   # 业务逻辑
│   ├── models/                     # 数据模型
│   └── data/                       # 静态数据
├── frontend/                       # 前端页面
│   ├── index.html
│   ├── css/
│   ├── js/
│   ├── pages/
│   └── assets/
├── config/
│   ├── mcporter.json               # MCP 工具配置（抖音/小红书/搜索）
│   └── mcporter.json.template      # 配置模板
└── agent-reach/                    # 互联网接入工具
    ├── README.md                   # 详细文档
    ├── setup.sh                    # 一键安装脚本
    ├── tools/
    │   └── douyin-mcp-server/      # 抖音 MCP Server（改造版）
    └── output/                     # 转录输出
```

## 技术栈

- **后端**: Flask + SQLite
- **前端**: 原生 HTML/CSS/JS
- **AI**: OpenAI 兼容接口（支持 DeepSeek / 通义千问 / Ollama 等）
- **互联网接入**: Agent Reach（抖音/小红书/搜索）

## License

[MIT](LICENSE)
