"""
旅行搭子对话路由
"""

from flask import Blueprint, jsonify, request
from backend.services.llm_service import chat_with_companion

chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/message", methods=["POST"])
def send_message():
    """
    发送消息给旅行搭子

    请求体：
    {
        "message": "我走累了，附近有什么咖啡店？",
        "context": {
            "itinerary": {...},
            "profile": {...},
            "current_location": "武康路"
        }
    }
    """
    data = request.get_json()

    if not data or not data.get("message"):
        return jsonify({"error": "请输入消息"}), 400

    message = data["message"]
    context = data.get("context", {})

    reply = chat_with_companion(message, context)

    return jsonify({
        "reply": reply,
        "suggestions": _get_quick_suggestions(message),
    })


@chat_bp.route("/suggestions", methods=["GET"])
def get_suggestions():
    """获取快捷回复建议"""
    return jsonify({
        "suggestions": [
            "附近有什么好吃的？",
            "我走累了，休息一下",
            "帮我调整路线",
            "这个地方值得去吗？",
            "下雨了怎么办？",
            "帮我找个拍照点",
        ]
    })


def _get_quick_suggestions(message: str) -> list:
    """根据上下文生成快捷建议"""
    msg = message.lower()

    if any(w in msg for w in ["下雨", "雨"]):
        return ["室内景点推荐", "最近的地铁站", "附近有商场吗"]

    if any(w in msg for w in ["累", "休息"]):
        return ["最近的咖啡店", "找个地方坐下", "今天的行程调整"]

    if any(w in msg for w in ["吃", "饿"]):
        return ["附近美食推荐", "人均50以内", "本地特色小吃"]

    return ["下一站去哪", "帮我拍张照", "还有什么推荐"]
