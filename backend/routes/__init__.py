"""蓝图注册表：新增路由只需在这里加一行。"""

from backend.routes.auth import auth_bp
from backend.routes.buddy import buddy_bp
from backend.routes.chat import chat_bp
from backend.routes.itinerary import itinerary_bp
from backend.routes.locations import locations_bp
from backend.routes.inspiration import inspiration_bp
from backend.routes.mbti import mbti_bp
from backend.routes.trips import trips_bp, weather_bp
from backend.routes.video import video_bp

BLUEPRINTS = (
    (mbti_bp, "/api/mbti"),
    (locations_bp, "/api/locations"),
    (itinerary_bp, "/api/itinerary"),
    (chat_bp, "/api/chat"),
    (auth_bp, "/api/auth"),
    (video_bp, "/api/video"),
    (buddy_bp, "/api/buddy"),
    (trips_bp, "/api/trips"),
    (weather_bp, "/api/weather"),
    (inspiration_bp, "/api/inspiration"),
)


def register_blueprints(app):
    for bp, prefix in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=prefix)
