import os
from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Config:
    """应用配置"""

    # Flask
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    PORT = int(os.getenv("FLASK_PORT", "5000"))

    # LLM
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_WEB_SEARCH_MODEL = os.getenv("LLM_WEB_SEARCH_MODEL", "gpt-4o-mini-search-preview")
    LLM_WEB_SEARCH_CONTEXT_SIZE = os.getenv("LLM_WEB_SEARCH_CONTEXT_SIZE", "medium")
    LLM_WIRE_API = os.getenv("LLM_WIRE_API", "responses")
    LLM_WEB_SEARCH = os.getenv("LLM_WEB_SEARCH", "live")
    LLM_TIMEOUT = _float_env("LLM_TIMEOUT", 60)
    LLM_MAX_RETRIES = _int_env("LLM_MAX_RETRIES", 1)

    # MiMo ASR (抖音视频语音转文字)
    MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
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
    DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")
    DOUBAO_BASE_URL = os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    DOUBAO_MODEL = os.getenv("DOUBAO_MODEL", "doubao-seed-2-0-pro-260215")  # pro版联网搜索更稳定
    HAS_DOUBAO = bool(DOUBAO_API_KEY)

    # AMap
    AMAP_KEY = os.getenv("AMAP_KEY", "")

    # Database
    DB_PATH = os.getenv("DB_PATH", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "instance", "luvdazi.db"
    ))

    # 判断是否配置了 LLM
    HAS_LLM = bool(LLM_API_KEY)
