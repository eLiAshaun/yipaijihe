"""
一拍迹合 - 把抖音精选里的旅行视频，变成更契合你旅行人格的线路图
抖音精选内容重构黑客松参赛作品
"""

import logging
import os

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from backend.config import Config
from backend.database import init_db
from backend.routes import register_blueprints

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT, "frontend")

# 高德地图 / 字体 / CDN 均为前端所需的第三方来源
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://webapi.amap.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com 'unsafe-inline'",
    "style-src 'self' https://fonts.googleapis.com https://webapi.amap.com 'unsafe-inline'",
    "font-src 'self' https://fonts.gstatic.com data:",
    "img-src 'self' data: blob: https:",
    "connect-src 'self' https://*.amap.com https://restapi.amap.com https://cdn.jsdelivr.net",
    "frame-ancestors 'self'",
])


def create_app():
    """应用工厂"""
    app = Flask(__name__, static_folder=None)

    if Config.CORS_ORIGINS:
        CORS(app, resources={r"/api/*": {"origins": Config.CORS_ORIGINS}})

    os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)
    init_db()
    register_blueprints(app)

    # ---------- 前端（SPA，hash 路由） ----------
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html", max_age=0)

    @app.get("/<path:filename>")
    def static_files(filename):
        if filename.startswith("api/"):
            return jsonify({"error": "Not Found"}), 404
        # 资源图片带指纹很少变；代码文件使用协商缓存，开发时改动立即生效
        max_age = 60 * 60 * 24 * 30 if filename.startswith("assets/") else 0
        return send_from_directory(FRONTEND_DIR, filename, max_age=max_age)

    # ---------- 公共 API ----------
    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "llm_configured": Config.HAS_LLM,
            "model": Config.LLM_MODEL if Config.HAS_LLM else "demo_mode",
        }

    @app.get("/api/config")
    def public_config():
        """下发前端所需的公开配置（地图 Key 等），避免写死在 HTML 里"""
        return {
            "amap": {
                "key": Config.AMAP_JS_KEY,
                "securityJsCode": Config.AMAP_SECURITY_CODE,
            },
            "llm": Config.HAS_LLM,
        }

    # ---------- 安全响应头 ----------
    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Content-Security-Policy", CSP)
        return resp

    # ---------- 统一 JSON 错误 ----------
    @app.errorhandler(HTTPException)
    def http_error(e):
        return jsonify({"error": e.description or e.name}), e.code

    @app.errorhandler(Exception)
    def unhandled(e):
        logger.exception("未处理的异常: %s", e)
        return jsonify({"error": "服务器开小差了，请稍后重试"}), 500

    return app


if __name__ == "__main__":
    application = create_app()
    logger.info("🚀 一拍迹合启动在 http://localhost:%s", Config.PORT)
    logger.info("📊 LLM 模式: %s", "API" if Config.HAS_LLM else "Demo（未配置 API Key）")
    application.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)
