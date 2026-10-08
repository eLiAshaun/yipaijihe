"""
语音转写（听抖音视频里的讲解）。

DeepSeek 等大模型的 API 不接收音频，所以「听」在这里完成，「理解」交给大模型：
  · mimo  ：小米 MiMo 云端转写（配置 MIMO_API_KEY）
  · local ：本地 Whisper（faster-whisper，免费、离线可用）。首次启动在后台下载模型，
            huggingface.co 连不上时自动改用国内镜像 hf-mirror.com；下载完成前视频分析会跳过语音、照常看画面和标题
"""

from __future__ import annotations

import logging
import os
import threading
import time

from backend.config import Config

logger = logging.getLogger(__name__)

# faster-whisper 模型在 Hugging Face 上的仓库与大约体积（MB），用于显示下载进度
_REPOS = {
    "tiny": ("Systran/faster-whisper-tiny", 75),
    "base": ("Systran/faster-whisper-base", 145),
    "small": ("Systran/faster-whisper-small", 484),
    "medium": ("Systran/faster-whisper-medium", 1530),
    "large-v3": ("Systran/faster-whisper-large-v3", 3090),
}
_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]

_state = {"state": "idle", "error": "", "started": 0.0}
_model = None
_load_lock = threading.Lock()
_run_lock = threading.Lock()  # CPU 推理很吃资源，同一时间只转写一条


def engine() -> str:
    if Config.HAS_MIMO_ASR:
        return "mimo"
    if Config.HAS_LOCAL_ASR:
        return "local"
    return "none"


def _model_dir() -> str:
    return Config.ASR_MODEL_DIR or os.path.join(Config._ROOT, "instance", "models")


def _downloaded_mb() -> int:
    total = 0
    for root, _, files in os.walk(_model_dir()):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in files if not os.path.islink(os.path.join(root, f)))
    return total // (1024 * 1024)


def status() -> dict:
    """{engine, ready, state, model, progress, error}；state: ready / downloading / loading / idle / error / unavailable"""
    e = engine()
    if e == "mimo":
        return {"engine": "mimo", "ready": True, "state": "ready"}
    if e == "none":
        return {"engine": "none", "ready": False, "state": "unavailable"}
    info = {"engine": "local", "ready": _model is not None, "state": _state["state"], "model": Config.ASR_MODEL, "error": _state["error"]}
    if _state["state"] == "downloading":
        size = _REPOS.get(Config.ASR_MODEL, ("", 500))[1]
        info["progress"] = min(99, int(_downloaded_mb() * 100 / size))
    return info


def warm_up() -> None:
    """应用启动时调用：后台下载并加载本地模型，不阻塞启动"""
    if engine() == "local" and _state["state"] in ("idle", "error"):
        threading.Thread(target=_load, name="asr-warmup", daemon=True).start()


def _download() -> str:
    from huggingface_hub import snapshot_download

    name = Config.ASR_MODEL
    if os.path.isdir(name):  # 直接给了本地模型目录
        return name
    repo = _REPOS.get(name, (name, 0))[0]
    errors = []
    for endpoint in (None, "https://hf-mirror.com"):
        try:
            return snapshot_download(repo, allow_patterns=_FILES, cache_dir=_model_dir(), endpoint=endpoint)
        except Exception as e:  # noqa: BLE001 — 换下一个源
            errors.append(f"{endpoint or 'huggingface.co'}: {str(e)[:120]}")
            logger.warning("下载语音模型失败（%s），尝试下一个源", errors[-1])
    raise RuntimeError("；".join(errors))


def _load() -> None:
    global _model
    with _load_lock:
        if _model is not None:
            return
        _state.update(state="downloading", error="", started=time.time())
        try:
            from faster_whisper import WhisperModel

            path = _download()
            _state["state"] = "loading"
            _model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=max(2, (os.cpu_count() or 4) - 1))
            _state["state"] = "ready"
            logger.info("本地语音模型已就绪：%s（%.0fs）", Config.ASR_MODEL, time.time() - _state["started"])
        except Exception as e:  # noqa: BLE001
            _state.update(state="error", error=str(e)[:300])
            logger.error("本地语音模型加载失败：%s", e)


def transcribe_local(media_path: str, hints: list[str] | None = None, max_seconds: int | None = None) -> str:
    """
    本地转写音 / 视频文件（PyAV 解码，不需要系统装 ffmpeg）。
    hints：可能出现的地名，作为 Whisper 的提示词能明显减少地名同音错字，也让输出保持简体中文。
    """
    if _model is None:
        raise RuntimeError("本地语音模型还没准备好")
    max_seconds = max_seconds or Config.ASR_MAX_SECONDS
    prompt = "以下是普通话旅行视频的讲解，使用简体中文和标点。"
    if hints:
        prompt += "可能提到：" + "、".join(dict.fromkeys(h for h in hints if h))[:300] + "。"
    with _run_lock:
        segments, _ = _model.transcribe(
            media_path,
            language="zh",
            beam_size=3,
            vad_filter=True,
            initial_prompt=prompt,
            condition_on_previous_text=False,
        )
        text = ""
        for seg in segments:
            if seg.start > max_seconds:
                break
            piece = seg.text.strip()
            if piece:
                text += piece if not text or text[-1] in "，。！？、；：,.!?" else "，" + piece
    return text
