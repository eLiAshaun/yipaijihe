"""
用户认证路由
"""

import re
import json
import uuid
import hashlib
from functools import wraps
from flask import Blueprint, jsonify, request, g
from backend.database import get_db

auth_bp = Blueprint("auth", __name__)

# ========== 工具函数 ==========

def _hash_password(password, salt=None):
    """密码哈希（sha256 + salt）"""
    if salt is None:
        salt = uuid.uuid4().hex[:16]
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${hashed}"


def _verify_password(password, stored_hash):
    """验证密码"""
    salt = stored_hash.split("$")[0]
    return _hash_password(password, salt) == stored_hash


def _generate_token():
    """生成 session token"""
    return uuid.uuid4().hex


def _get_current_user():
    """从请求中获取当前用户"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE session_token = ?", (token,)
    ).fetchone()
    db.close()
    return dict(user) if user else None


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if not user:
            return jsonify({"error": "请先登录"}), 401
        g.user = user
        return f(*args, **kwargs)
    return decorated


# ========== 路由 ==========

@auth_bp.route("/register", methods=["POST"])
def register():
    """
    用户注册
    请求体：{ "username": "xxx", "password": "xxx" }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供注册信息"}), 400

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    # 验证用户名
    if not username or len(username) < 3 or len(username) > 20:
        return jsonify({"error": "用户名长度需为 3-20 个字符"}), 400

    if not re.match(r'^[a-zA-Z0-9_一-鿿]+$', username):
        return jsonify({"error": "用户名只能包含字母、数字、下划线或中文"}), 400

    # 验证密码
    if len(password) < 6 or len(password) > 20:
        return jsonify({"error": "密码长度需为 6-20 个字符"}), 400

    db = get_db()
    try:
        # 检查用户名是否已存在
        existing = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return jsonify({"error": "用户名已存在"}), 409

        # 创建用户
        password_hash = _hash_password(password)
        token = _generate_token()

        cursor = db.execute(
            "INSERT INTO users (username, password_hash, session_token) VALUES (?, ?, ?)",
            (username, password_hash, token)
        )
        db.commit()

        user_id = cursor.lastrowid
        return jsonify({
            "message": "注册成功",
            "user": {"id": user_id, "username": username},
            "token": token,
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    用户登录
    请求体：{ "username": "xxx", "password": "xxx" }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供登录信息"}), 400

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400

    db = get_db()
    try:
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if not user or not _verify_password(password, user["password_hash"]):
            return jsonify({"error": "用户名或密码错误"}), 401

        # 更新 session token
        token = _generate_token()
        db.execute(
            "UPDATE users SET session_token = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (token, user["id"])
        )
        db.commit()

        return jsonify({
            "message": "登录成功",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "mbti_type": user["mbti_type"],
            },
            "token": token,
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@auth_bp.route("/profile", methods=["GET"])
@login_required
def get_profile():
    """获取当前用户完整画像"""
    user = g.user
    profile = {
        "id": user["id"],
        "username": user["username"],
        "mbti_type": user["mbti_type"],
        "mbti_result": json.loads(user["mbti_result"]) if user["mbti_result"] else None,
        "travel_history": json.loads(user["travel_history"]) if user["travel_history"] else [],
        "created_at": user["created_at"],
    }
    return jsonify({"profile": profile})


@auth_bp.route("/mbti", methods=["PUT"])
@login_required
def save_mbti():
    """
    保存 MBTI 测试结果
    请求体：{ "mbti_type": "SHFS", "mbti_result": { ... } }
    """
    data = request.get_json()
    if not data or not data.get("mbti_type"):
        return jsonify({"error": "请提供 MBTI 结果"}), 400

    mbti_type = data["mbti_type"]
    mbti_result = json.dumps(data.get("mbti_result", {}), ensure_ascii=False)

    db = get_db()
    try:
        db.execute(
            "UPDATE users SET mbti_type = ?, mbti_result = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (mbti_type, mbti_result, g.user["id"])
        )
        db.commit()
        return jsonify({"message": "MBTI 结果已保存", "mbti_type": mbti_type})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@auth_bp.route("/travel-history", methods=["POST"])
@login_required
def add_travel_history():
    """
    添加旅行历史
    请求体：{ "city": "上海", "days": 2, "itinerary": { ... } }
    """
    data = request.get_json()
    if not data or not data.get("city"):
        return jsonify({"error": "请提供旅行信息"}), 400

    from datetime import datetime

    trip = {
        "city": data["city"],
        "days": data.get("days", 1),
        "companions": data.get("companions", ""),
        "budget": data.get("budget", ""),
        "mbti_type": g.user["mbti_type"],
        "itinerary": data.get("itinerary"),
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    db = get_db()
    try:
        # 读取现有历史
        user = db.execute(
            "SELECT travel_history FROM users WHERE id = ?", (g.user["id"],)
        ).fetchone()

        history = json.loads(user["travel_history"]) if user["travel_history"] else []
        history.append(trip)

        db.execute(
            "UPDATE users SET travel_history = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(history, ensure_ascii=False), g.user["id"])
        )
        db.commit()
        return jsonify({"message": "旅行已记录", "trip": trip}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """退出登录"""
    db = get_db()
    try:
        db.execute(
            "UPDATE users SET session_token = NULL WHERE id = ?",
            (g.user["id"],)
        )
        db.commit()
        return jsonify({"message": "已退出登录"})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()
