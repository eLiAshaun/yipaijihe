# Agent Reach — 本地互联网接入

给 AI Agent 接入抖音、小红书等平台的能力。

## 快速开始（新用户）

```bash
# 1. 克隆项目
git clone <repo-url> && cd 黑客松

# 2. 一键安装（自动装 ffmpeg、uv、mcporter、xhs-cli、douyin 依赖）
bash agent-reach/setup.sh
```

`.env` 和 `config/mcporter.json` 已包含在仓库中，clone 后直接可用。

如果需要更换 API Key，编辑 `.env` 中的 `MIMO_API_KEY`，然后重新运行 `bash agent-reach/setup.sh` 更新 mcporter 配置。

## 已安装渠道

| 渠道 | 工具 | 用途 | 需要 API Key |
|------|------|------|:---:|
| 抖音 | douyin-mcp-server | 视频解析、无水印下载、语音转文字 | 语音转文字需要 |
| 小红书 | xhs-cli | 搜索、阅读、发帖 | 需要登录 |
| 全网搜索 | Exa (mcporter) | 语义搜索 | 免费 |

## 使用方式

### 抖音

```bash
# 解析视频信息（无需 API Key）
mcporter call douyin.parse_douyin_video_info share_link='https://v.douyin.com/xxx/'

# 获取无水印下载链接（无需 API Key）
mcporter call douyin.get_douyin_download_link share_link='https://v.douyin.com/xxx/'

# 语音转文字（需要 MIMO_API_KEY）
mcporter call douyin.extract_douyin_text share_link='https://v.douyin.com/xxx/'
```

### 小红书

```bash
# 搜索
xhs search '上海旅游攻略'

# 登录（首次使用，需先在浏览器登录 xiaohongshu.com）
xhs login
```

## 语音转文字技术栈

- **模型**: 小米 MiMo-v2.5-ASR
- **API**: `https://token-plan-cn.xiaomimimo.com/v1`（OpenAI 兼容）
- **流程**: 视频下载 → ffmpeg 提取音频(192kbps) → 分段(90s) → base64 编码 → MiMo ASR
- **限制**: 单段 base64 < 10MB，超过自动分段

## 配置说明

| 文件 | 用途 |
|------|------|
| `.env` | 环境变量（API Key 等），已提交 |
| `.env.example` | 环境变量模板 |
| `config/mcporter.json` | mcporter 配置，已提交 |
| `config/mcporter.json.template` | mcporter 配置模板（setup.sh 用） |

## 目录结构

```
agent-reach/
├── README.md
├── setup.sh                          # 一键安装
├── tools/
│   └── douyin-mcp-server/            # 抖音 MCP（改造版）
│       ├── .venv/                    # Python 虚拟环境（gitignore）
│       ├── douyin_mcp_server/
│       │   └── server.py             # 核心代码
│       └── pyproject.toml
└── output/                           # 转录输出
```
