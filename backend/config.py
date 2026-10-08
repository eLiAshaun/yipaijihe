import importlib.util
import os
from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _secret(name: str, default: str = "") -> str:
    """读取密钥类配置：把 .env.example 里的占位值（your-xxx / xxx-here）当作未配置，
    避免「复制示例配置 → 每次 AI 调用都带着假 Key 卡到超时」。"""
    value = (os.getenv(name) or default).strip()
    low = value.lower()
    if not value or low.startswith("your") or low.endswith("-here") or low in {"xxx", "changeme", "sk-xxx"}:
        return ""
    return value


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _is_vision_model(model: str) -> bool:
    """按模型名判断是否能看图（DeepSeek V4.1-Flash、GPT-4o 系列、通义 / 智谱的视觉模型等）"""
    m = model.lower()
    return any(k in m for k in ("deepseek-flash", "gpt-4o", "gpt-4.1", "gpt-5", "-vl", "vision", "glm-4v"))


class Config:
    """应用配置"""

    # Flask
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    # 默认 8000：macOS 的 AirPlay 接收器占用 5000，会导致启动失败或请求被 403
    PORT = _int_env("FLASK_PORT", 8000)
    # 默认只监听本机；局域网 / 容器部署时显式设为 0.0.0.0
    HOST = os.getenv("FLASK_HOST", "127.0.0.1")

    # LLM（OpenAI 兼容接口）。默认 DeepSeek：deepseek-flash（V4.1-Flash，支持看图、1M 上下文）
    # 也可以换成 OpenAI / 通义 / Kimi / 本地 Ollama：改 LLM_BASE_URL 与 LLM_MODEL 即可
    LLM_API_KEY = _secret("LLM_API_KEY") or _secret("DEEPSEEK_API_KEY")
    LLM_BASE_URL = (os.getenv("LLM_BASE_URL") or "https://api.deepseek.com").strip().rstrip("/")
    LLM_MODEL = (os.getenv("LLM_MODEL") or "deepseek-flash").strip()
    LLM_PROVIDER = "deepseek" if "deepseek.com" in LLM_BASE_URL else "openai" if "api.openai.com" in LLM_BASE_URL else "other"
    # 思考模式：off（默认）—— 抽取、归纳、排行程这类任务关掉思考快 4-5 倍，质量足够；on 更细致但慢
    LLM_THINKING = os.getenv("LLM_THINKING", "off").strip().lower()
    # 看图（读视频画面里的字幕 / 招牌）：auto = 按模型名判断是否多模态；1 / 0 强制开关
    LLM_VISION = os.getenv("LLM_VISION", "auto").strip().lower()
    # chat = Chat Completions（推荐）；responses = OpenAI Responses API（可用 OpenAI 自带的 web_search 工具）
    LLM_WIRE_API = os.getenv("LLM_WIRE_API", "chat").strip().lower()
    LLM_WEB_SEARCH_MODEL = os.getenv("LLM_WEB_SEARCH_MODEL", "gpt-4o-mini-search-preview")
    LLM_TIMEOUT = _float_env("LLM_TIMEOUT", 60)
    LLM_MAX_RETRIES = _int_env("LLM_MAX_RETRIES", 1)

    # 语音转写（听抖音视频里的讲解）
    #   auto  = 配了 MIMO_API_KEY 用 MiMo 云端转写，否则用本地 Whisper（免费，需安装 requirements-video.txt）
    #   local / mimo / off
    ASR_ENGINE = os.getenv("ASR_ENGINE", "auto").strip().lower()
    # 本地 Whisper 模型：tiny / base / small（默认，约 460MB，中文地名识别明显好于 base）/ medium / large-v3
    ASR_MODEL = os.getenv("ASR_MODEL", "small").strip()
    ASR_MODEL_DIR = os.getenv("ASR_MODEL_DIR", "").strip()
    # 单条视频最多转写多少秒（旅行视频的地点基本都在前几分钟）
    ASR_MAX_SECONDS = _int_env("ASR_MAX_SECONDS", 600)

    # MiMo ASR（可选的云端语音转写）
    MIMO_API_KEY = _secret("MIMO_API_KEY")
    MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1")
    MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5-asr")
    MIMO_ASR_REQUEST_TIMEOUT = _float_env("MIMO_ASR_REQUEST_TIMEOUT", 120)
    MIMO_ASR_MAX_RETRIES = _int_env("MIMO_ASR_MAX_RETRIES", 1)
    MIMO_ASR_SEGMENT_DURATION = _int_env("MIMO_ASR_SEGMENT_DURATION", 90)
    MIMO_ASR_MAX_WORKERS = _int_env("MIMO_ASR_MAX_WORKERS", 3)
    MIMO_ASR_GLOBAL_MAX_CONCURRENT = _int_env("MIMO_ASR_GLOBAL_MAX_CONCURRENT", 4)
    MIMO_ASR_AUDIO_BITRATE = os.getenv("MIMO_ASR_AUDIO_BITRATE", "64k")
    MIMO_ASR_SAMPLE_RATE = _int_env("MIMO_ASR_SAMPLE_RATE", 16000)
    MIMO_ASR_CHANNELS = _int_env("MIMO_ASR_CHANNELS", 1)

    # 豆包 (Doubao / 火山方舟 Ark) - 用于联网搜索发现景点
    DOUBAO_API_KEY = _secret("DOUBAO_API_KEY")
    DOUBAO_BASE_URL = os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    DOUBAO_MODEL = os.getenv("DOUBAO_MODEL", "doubao-seed-2-0-pro-260215")  # pro版联网搜索更稳定
    HAS_DOUBAO = bool(DOUBAO_API_KEY)

    # AMap（高德）—— JS API Key / 安全密钥属于「前端公开配置」，由 /api/config 下发，
    # 不再写死在 index.html 里；建议在高德控制台为其绑定域名白名单。
    AMAP_KEY = _secret("AMAP_KEY")
    AMAP_JS_KEY = _secret("AMAP_JS_KEY", "f82fd3115909f6cda7b1378ff7b2e3cb") or "f82fd3115909f6cda7b1378ff7b2e3cb"
    AMAP_SECURITY_CODE = _secret("AMAP_SECURITY_CODE", "b01d7d9e9a0316af03bd430f49d8def7") or "b01d7d9e9a0316af03bd430f49d8def7"

    # CORS：默认仅同源（前后端同域部署）。需要跨域时用逗号分隔填写来源。
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

    # Database（相对路径按项目根目录解析，从任何目录启动都用同一个数据库）
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(_ROOT, os.getenv("DB_PATH") or os.path.join("instance", "luvdazi.db"))

    # 判断是否配置了 LLM
    HAS_LLM = bool(LLM_API_KEY)
    HAS_VISION = HAS_LLM and (LLM_VISION in ("1", "true", "on") or (LLM_VISION == "auto" and _is_vision_model(LLM_MODEL)))
    # 联网搜索：auto = 有大模型就开启（搜索引擎找资料 + 大模型归纳；配置了豆包时优先用豆包内置搜索）；off = 关闭
    WEB_SEARCH = os.getenv("WEB_SEARCH", "auto").strip().lower()
    HAS_WEB_SEARCH = WEB_SEARCH != "off" and (HAS_DOUBAO or HAS_LLM)
    HAS_MIMO_ASR = bool(MIMO_API_KEY) and ASR_ENGINE in ("auto", "mimo")
    HAS_LOCAL_ASR = ASR_ENGINE in ("auto", "local") and importlib.util.find_spec("faster_whisper") is not None
    HAS_ASR = HAS_MIMO_ASR or HAS_LOCAL_ASR
