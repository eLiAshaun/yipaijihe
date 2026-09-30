"""
用户认证路由
"""

import re
import json
import hmac
import logging
import secrets
import hashlib
from functools import wraps
from flask import Blueprint, jsonify, request, g
from werkzeug.security import generate_password_hash, check_password_hash
from backend.database import get_db
from backend.services import trips as trips_repo

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# ========== 工具函数 ==========

def _hash_password(password):
    """密码哈希（werkzeug：scrypt + 随机盐）"""
    return generate_password_hash(password)


def _is_legacy_hash(stored_hash):
    """旧版格式：`salt$sha256hex`（无 `method$` 前缀）"""
    return bool(re.fullmatch(r"[0-9a-f]{16}\$[0-9a-f]{64}", stored_hash or ""))


def _verify_password(password, stored_hash):
    """验证密码，同时兼容旧版 sha256+salt 记录（登录成功后会自动升级）"""
    if not stored_hash:
        return False
    if _is_legacy_hash(stored_hash):
        salt = stored_hash.split("$")[0]
        legacy = salt + "$" + hashlib.sha256((salt + password).encode()).hexdigest()
        return hmac.compare_digest(legacy, stored_hash)
    return check_password_hash(stored_hash, password)


def _generate_token():
    """生成 session token"""
    return secrets.token_urlsafe(32)


def _server_error(db, exc, action):
    """统一的 500 处理：回滚 + 记日志，不把异常细节泄露给客户端"""
    db.rollback()
    logger.exception("%s失败: %s", action, exc)
    return jsonify({"error": f"{action}失败，请稍后重试"}), 500


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
        return _server_error(db, e, "注册")
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

        # 更新 session token（旧版哈希顺带升级为 scrypt）
        token = _generate_token()
        new_hash = _hash_password(password) if _is_legacy_hash(user["password_hash"]) else user["password_hash"]
        db.execute(
            "UPDATE users SET session_token = ?, password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (token, new_hash, user["id"])
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
        return _server_error(db, e, "登录")
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
        "travel_history": trips_repo.list_trips(user["id"], full=True),
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
        return _server_error(db, e, "保存人格")
    finally:
        db.close()


@auth_bp.route("/travel-history", methods=["POST"])
@login_required
def add_travel_history():
    """兼容旧接口：添加旅行历史（新代码请用 POST /api/trips）"""
    data = request.get_json(silent=True)
    if not data or not data.get("city"):
        return jsonify({"error": "请提供旅行信息"}), 400
    try:
        trip = trips_repo.create_trip(g.user, data)
    except trips_repo.TripError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"message": "旅行已记录", "trip": trip}), 201


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
        return _server_error(db, e, "退出登录")
    finally:
        db.close()
