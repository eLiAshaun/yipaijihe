"""
看画面：把视频关键帧 / 图文笔记的图片交给多模态大模型（默认 DeepSeek deepseek-flash），
读出字幕、标题字、招牌和能认出的地标。很多旅行视频只配音乐不说话，地名全在画面上。
"""

from __future__ import annotations

import base64
import io
import logging

from backend.config import Config

logger = logging.getLogger(__name__)


def to_jpeg(data: bytes, max_side: int = 960) -> bytes | None:
    """任意图片 → 缩小后的 JPEG（减小请求体积）；没装 Pillow 时原样返回"""
    try:
        from PIL import Image
    except ImportError:
        return data
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((max_side, max_side))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=72)
        return out.getvalue()
    except Exception:  # noqa: BLE001 — 损坏 / 不支持的格式
        return None


def _image_part(data: bytes) -> dict:
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}


def read_images(images: list[bytes], title: str = "", city: str = "") -> dict:
    """
    返回 {"text": 画面上的文字（逐条）, "places": [{"name", "evidence"}], "summary": 一句话}；
    不支持看图或调用失败时返回空结构。
    """
    empty = {"text": [], "places": [], "summary": ""}
    images = [i for i in images if i][:10]
    if not (Config.HAS_VISION and images):
        return empty
    from backend.services.llm_service import chat_completion, parse_json

    prompt = f"""这是一条{city or ''}旅行视频按时间顺序截取的画面{f"，视频标题：{title}" if title else ""}。
请仔细看每一张图：
1. 逐条抄下画面上的中文 / 英文文字：字幕、大标题、店铺招牌、路牌、地铁站名、门票等（原样抄写，不要改写）
2. 列出视频在推荐或经过、游客值得去的具体地点（景点、街道、餐厅、咖啡馆、店铺、展馆、公园等）：要么画面上写着名字，要么是一眼能认出的著名地标；
   不确定的不要写；路过的小区、物业、家政、银行、诊所、中介这类与游玩无关的招牌不要写；同一个地方的中英文名只写中文名
3. 用一句话概括视频内容

只输出 JSON：{{"text": ["画面文字1", "画面文字2"], "places": [{{"name": "地点名", "evidence": "字幕/招牌/地标外观"}}], "summary": "一句话"}}"""
    content = [{"type": "text", "text": prompt}] + [_image_part(i) for i in images]
    raw = chat_completion([{"role": "user", "content": content}], temperature=0.1, max_tokens=2000, json_mode=True)
    data = parse_json(raw) if raw else None
    if not isinstance(data, dict):
        return empty
    text = [str(t).strip()[:80] for t in (data.get("text") or []) if str(t).strip()][:60]
    places = [
        {"name": str(p.get("name")).strip()[:40], "evidence": str(p.get("evidence") or "")[:20]}
        for p in (data.get("places") or [])
        if isinstance(p, dict) and str(p.get("name") or "").strip()
    ][:20]
    return {"text": text, "places": places, "summary": str(data.get("summary") or "")[:120]}


def as_text(seen: dict) -> str:
    """把看画面的结果拼成一段文字，供地点识别使用（地点名出现在这段文字里才会被采纳）"""
    parts = []
    if seen.get("text"):
        parts.append("画面文字：" + "；".join(seen["text"]))
    if seen.get("places"):
        parts.append("画面中的地点：" + "、".join(p["name"] for p in seen["places"]))
    return "\n".join(parts)
