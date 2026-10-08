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


class Config:
    """应用配置"""

    # Flask
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    # 默认 8000：macOS 的 AirPlay 接收器占用 5000，会导致启动失败或请求被 403
    PORT = _int_env("FLASK_PORT", 8000)
    # 默认只监听本机；局域网 / 容器部署时显式设为 0.0.0.0
    HOST = os.getenv("FLASK_HOST", "127.0.0.1")

    # LLM
    LLM_API_KEY = _secret("LLM_API_KEY")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_WEB_SEARCH_MODEL = os.getenv("LLM_WEB_SEARCH_MODEL", "gpt-4o-mini-search-preview")
    LLM_WEB_SEARCH_CONTEXT_SIZE = os.getenv("LLM_WEB_SEARCH_CONTEXT_SIZE", "medium")
    # chat = Chat Completions（OpenAI / DeepSeek / 通义 / Kimi / Ollama 都支持）；responses 仅 OpenAI 官方等少数服务支持
    LLM_WIRE_API = os.getenv("LLM_WIRE_API", "chat").strip().lower()
    LLM_WEB_SEARCH = os.getenv("LLM_WEB_SEARCH", "live")
    LLM_TIMEOUT = _float_env("LLM_TIMEOUT", 45)
    LLM_MAX_RETRIES = _int_env("LLM_MAX_RETRIES", 1)

    # MiMo ASR (抖音视频语音转文字)
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

    # Database
    DB_PATH = os.getenv("DB_PATH", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "instance", "luvdazi.db"
    ))

    # 判断是否配置了 LLM
    HAS_LLM = bool(LLM_API_KEY)
    # 联网搜索：豆包，或 OpenAI 官方 Responses API 的 web_search 工具
    HAS_WEB_SEARCH = HAS_DOUBAO or (HAS_LLM and LLM_WIRE_API == "responses" and LLM_WEB_SEARCH == "live")
    HAS_ASR = bool(MIMO_API_KEY)
