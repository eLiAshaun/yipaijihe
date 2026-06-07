"""
旅搭子 - AI 旅行搭子
抖音精选内容重构黑客松参赛作品
"""

import os
import logging
from flask import Flask, send_from_directory
from flask_cors import CORS
from backend.config import Config
from backend.database import init_db

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app():
    """创建 Flask 应用"""
    app = Flask(
        __name__,
        static_folder="frontend",
        static_url_path="",
    )

    # CORS
    CORS(app)

    # 初始化数据库
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance"), exist_ok=True)
    init_db()

    # 注册蓝图
    from backend.routes.mbti import mbti_bp
    from backend.routes.locations import locations_bp
    from backend.routes.itinerary import itinerary_bp
    from backend.routes.chat import chat_bp
    from backend.routes.auth import auth_bp
    from backend.routes.video import video_bp
    from backend.routes.buddy import buddy_bp

    app.register_blueprint(mbti_bp, url_prefix="/api/mbti")
    app.register_blueprint(locations_bp, url_prefix="/api/locations")
    app.register_blueprint(itinerary_bp, url_prefix="/api/itinerary")
    app.register_blueprint(chat_bp, url_prefix="/api/chat")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(video_bp, url_prefix="/api/video")
    app.register_blueprint(buddy_bp, url_prefix="/api/buddy")

    # 前端路由 - SPA 入口
    @app.route("/")
    def index():
        return send_from_directory("frontend", "index.html")

    # 健康检查
    @app.route("/api/health")
    def health():
        return {
            "status": "ok",
            "llm_configured": Config.HAS_LLM,
            "model": Config.LLM_MODEL if Config.HAS_LLM else "demo_mode",
        }

    # 错误处理
    @app.errorhandler(404)
    def not_found(e):
        return {"error": "Not Found"}, 404

    @app.errorhandler(500)
    def server_error(e):
        return {"error": "Internal Server Error"}, 500

    return app


if __name__ == "__main__":
    app = create_app()

    port = Config.PORT
    logger.info(f"🚀 旅搭子启动在 http://localhost:{port}")
    logger.info(f"📊 LLM 模式: {'API' if Config.HAS_LLM else 'Demo（未配置 API Key）'}")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=Config.DEBUG,
    )
