"""
旅行搭子对话路由：
  · 本地助手先基于行程、景点库、天气算出事实（距离、时间、预算…）
  · 有大模型时把这些事实交给它组织回答；开启联网搜索时它还可以自己查营业时间、门票等实时信息
  · 大模型不可用时直接返回本地助手的回答
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
    # 只有问到具体问题（吃什么、怎么走、预算…）时，本地算出的结果才是有用的事实；概览类的客套话不传给大模型
    hint = local_text if assistant.intent_of(message) != "summary" else ""
    text, sources = chat_with_companion(message, context, local_hint=hint)
    return jsonify({
        "reply": text or local_text,
        "suggestions": suggestions,
        "sources": sources if text else [],
        "engine": "llm" if text else "local",
    })
