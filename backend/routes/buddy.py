"""
旅行搭子同步路由
"""

import json
import logging
from flask import Blueprint, jsonify, request
from backend.database import get_db

logger = logging.getLogger(__name__)

buddy_bp = Blueprint("buddy", __name__)


@buddy_bp.route("/sync", methods=["POST"])
def sync_buddy():
    """
    旅行搭子同步

    请求体：
    {
        "buddy_identifier": "用户名或UID"
    }

    返回：
    {
        "buddy": {
            "id": 2,
            "username": "xxx",
            "mbti_type": "SHFS"
        },
        "shared_plans": [...]
    }
    """
    data = request.get_json()
    if not data or not data.get("buddy_identifier"):
        return jsonify({"error": "请输入搭子的用户名或UID"}), 400

    identifier = data["buddy_identifier"].strip()

    db = get_db()
    try:
        # 尝试按用户名查找
        buddy = db.execute(
            "SELECT id, username, mbti_type, travel_history FROM users WHERE username = ?",
            (identifier,),
        ).fetchone()

        # 如果没找到，尝试按ID查找
        if not buddy:
            try:
                uid = int(identifier)
                buddy = db.execute(
                    "SELECT id, username, mbti_type, travel_history FROM users WHERE id = ?",
                    (uid,),
                ).fetchone()
            except ValueError:
                pass

        if not buddy:
            return jsonify({"error": "未找到该用户，请检查用户名或UID"}), 404

        # 获取搭子的旅行历史
        shared_plans = []
        if buddy["travel_history"]:
            try:
                shared_plans = json.loads(buddy["travel_history"])
            except json.JSONDecodeError:
                pass

        return jsonify({
            "buddy": {
                "id": buddy["id"],
                "username": buddy["username"],
                "mbti_type": buddy["mbti_type"],
            },
            "shared_plans": shared_plans,
        })

    except Exception as e:
        logger.error(f"搭子同步失败: {e}")
        return jsonify({"error": "同步失败，请稍后重试"}), 500
    finally:
        db.close()


@buddy_bp.route("/search", methods=["GET"])
def search_buddy():
    """
    搜索搭子（模糊匹配用户名）

    查询参数：q=关键词
    """
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify({"error": "请输入至少2个字符"}), 400

    db = get_db()
    try:
        users = db.execute(
            "SELECT id, username, mbti_type FROM users WHERE username LIKE ? LIMIT 10",
            (f"%{query}%",),
        ).fetchall()

        return jsonify({
            "users": [
                {"id": u["id"], "username": u["username"], "mbti_type": u["mbti_type"]}
                for u in users
            ]
        })
    finally:
        db.close()
