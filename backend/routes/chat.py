"""
旅行搭子对话路由：有大模型时用大模型，否则用本地助手（基于行程、景点库、天气计算回答）
"""

from flask import Blueprint, jsonify, request

from backend.database import get_db
from backend.services import assistant
from backend.services.llm_service import chat_with_companion

chat_bp = Blueprint("chat", __name__)


def _catalog(city: str) -> list:
    from backend.routes.itinerary import _db_row_to_location

    db = get_db()
    try:
        return [_db_row_to_location(r) for r in db.execute("SELECT * FROM attractions WHERE city = ?", (city,)).fetchall()]
    finally:
        db.close()


@chat_bp.route("/message", methods=["POST"])
def send_message():
    """
    请求体：{"message": "...", "context": {"itinerary": {...}, "profile": {...}, "trip": {...}, "weather": [...], "chat_history": [...]}}
    """
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()[:500]
    if not message:
        return jsonify({"error": "请输入消息"}), 400
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    city = ((context.get("trip") or {}).get("city") or "上海")[:20]

    local_text, suggestions = assistant.reply(message, context, _catalog(city))
    text = chat_with_companion(message, context)
    return jsonify({"reply": text or local_text, "suggestions": suggestions, "engine": "llm" if text else "local"})
