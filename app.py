"""
一拍迹合 - 把抖音精选里的旅行视频，变成更契合你旅行人格的线路图
抖音精选内容重构黑客松参赛作品
"""

import logging
import os
import socket
import sys
import threading
import webbrowser

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

    # 本地语音模型在后台下载 / 加载，不阻塞启动
    from backend.services import asr

    asr.warm_up()

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
        from backend.services.llm_service import llm_status

        return {
            "status": "ok",
            "llm_configured": Config.HAS_LLM,
            "model": Config.LLM_MODEL if Config.HAS_LLM else "local_engine",
            "capabilities": llm_status(),
        }

    @app.get("/api/config")
    def public_config():
        """下发前端所需的公开配置（地图 Key、可用能力），避免写死在 HTML 里"""
        from backend.services.llm_service import llm_status
        from backend.database import list_cities

        caps = llm_status()
        return {
            "amap": {
                "key": Config.AMAP_JS_KEY,
                "securityJsCode": Config.AMAP_SECURITY_CODE,
            },
            "llm": caps["llm"],
            "model": Config.LLM_MODEL if Config.HAS_LLM else "",
            "web_search": caps["web_search"],
            "vision": caps["vision"],
            "asr": caps["asr"],
            "asr_status": caps["asr_engine"],
            # 能分析的视频平台（抖音分享页解析不需要额外组件，其余平台需要 yt-dlp）与是否能读文章链接
            "video_platforms": ["抖音", "B 站", "YouTube", "小红书", "西瓜视频"] if Config.HAS_YTDLP else ["抖音"],
            "reader": Config.HAS_READER,
            # 有内置景点库的城市；开启联网搜索后可以规划任意城市
            "cities": list_cities(),
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


def _free_port(host: str, preferred: int, attempts: int = 20) -> int:
    """端口被占用（常见：macOS AirPlay 占 5000、本机已有服务占 8000）时顺延到下一个可用端口"""
    for port in range(preferred, preferred + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host if host != "0.0.0.0" else "", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"端口 {preferred}-{preferred + attempts - 1} 都被占用，请在 .env 里设置 FLASK_PORT")


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("需要 Python 3.10 及以上版本")
    application = create_app()
    port = _free_port(Config.HOST, Config.PORT)
    url = f"http://{'127.0.0.1' if Config.HOST in ('0.0.0.0', '') else Config.HOST}:{port}"
    if port != Config.PORT:
        logger.info("端口 %s 已被占用，改用 %s", Config.PORT, port)
    logger.info("🚀 一拍迹合已启动：%s", url)
    from backend.services import asr

    asr_engine = asr.engine()
    logger.info(
        "🧠 大模型：%s ｜ 联网搜索：%s ｜ 看画面：%s ｜ 语音转写：%s",
        f"{Config.LLM_MODEL}" if Config.HAS_LLM else "未配置（使用本地行程引擎与助手）",
        "开启" if Config.HAS_WEB_SEARCH else "未开启",
        "开启" if Config.HAS_VISION else "未开启",
        {"mimo": "MiMo 云端", "local": f"本地 Whisper（{Config.ASR_MODEL}，首次使用会在后台下载模型）", "none": "未开启（读取视频标题 / 画面 / 文案识别地点）"}[asr_engine],
    )
    if os.getenv("OPEN_BROWSER") == "1" and not os.getenv("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    application.run(host=Config.HOST, port=port, debug=Config.DEBUG, threaded=True)


if __name__ == "__main__":
    main()
