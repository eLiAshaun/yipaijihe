"""
行程管理：增删改查 · 分享链接 · 天气
"""

import logging
import time

import requests
from flask import Blueprint, g, jsonify, request

from backend.database import get_db
from backend.routes.auth import login_required
from backend.services import trips as repo

logger = logging.getLogger(__name__)

trips_bp = Blueprint("trips", __name__)


def _json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _bad_request(exc):
    return jsonify({"error": str(exc)}), 400


@trips_bp.get("")
@login_required
def list_my_trips():
    return jsonify({"trips": repo.list_trips(g.user["id"])})


@trips_bp.post("")
@login_required
def create():
    try:
        trip = repo.create_trip(g.user, _json())
    except repo.TripError as e:
        return _bad_request(e)
    return jsonify({"trip": trip}), 201


@trips_bp.get("/<trip_id>")
@login_required
def read(trip_id):
    trip = repo.get_trip(g.user["id"], trip_id)
    return (jsonify({"trip": trip}), 200) if trip else (jsonify({"error": "行程不存在"}), 404)


@trips_bp.put("/<trip_id>")
@login_required
def update(trip_id):
    try:
        trip = repo.update_trip(g.user["id"], trip_id, _json())
    except repo.TripError as e:
        return _bad_request(e)
    return (jsonify({"trip": trip}), 200) if trip else (jsonify({"error": "行程不存在"}), 404)


@trips_bp.delete("/<trip_id>")
@login_required
def remove(trip_id):
    if not repo.delete_trip(g.user["id"], trip_id):
        return jsonify({"error": "行程不存在"}), 404
    return jsonify({"message": "已删除"})


@trips_bp.post("/<trip_id>/share")
@login_required
def share(trip_id):
    token = repo.set_share(g.user["id"], trip_id, True)
    if not token:
        return jsonify({"error": "行程不存在"}), 404
    return jsonify({"token": token, "path": f"/#/s/{token}"})


@trips_bp.delete("/<trip_id>/share")
@login_required
def unshare(trip_id):
    if repo.set_share(g.user["id"], trip_id, False) is None and not repo.get_trip(g.user["id"], trip_id):
        return jsonify({"error": "行程不存在"}), 404
    return jsonify({"message": "已取消分享"})


@trips_bp.get("/shared/<token>")
def shared(token):
    """公开只读：任何拿到链接的人都能查看，无需登录"""
    trip = repo.get_shared(token)
    return (jsonify({"trip": trip}), 200) if trip else (jsonify({"error": "分享链接不存在或已失效"}), 404)


# ------------------------------------------------------------------ 天气 ----
weather_bp = Blueprint("weather", __name__)
_WEATHER_CACHE = {}
_WEATHER_TTL = 30 * 60


def _geocode(city: str):
    """城市名 → 坐标（Open-Meteo 地理编码，免 Key）。用于没有内置景点库的城市查天气。"""
    from backend.services.geo import city_center

    return city_center(city)


@weather_bp.get("")
def weather():
    """
    逐日天气预报（Open-Meteo，免 Key）。
    ?city=上海&start=2026-10-01&days=3
    仅覆盖未来 16 天；失败或超出范围时返回 available=false，前端静默隐藏。
    """
    from datetime import date, datetime, timedelta

    city = request.args.get("city", "上海")
    start = request.args.get("start", "")
    try:
        days = max(1, min(int(request.args.get("days", 3)), 16))
        start_d = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "start 需要 YYYY-MM-DD，days 需要整数"}), 400

    today = date.today()
    end_d = start_d + timedelta(days=days - 1)
    if end_d < today or start_d > today + timedelta(days=15):
        return jsonify({"available": False, "reason": "out_of_range", "days": []})

    db = get_db()
    try:
        row = db.execute("SELECT center_lat, center_lng FROM cities WHERE name = ?", (city,)).fetchone()
    finally:
        db.close()
    coords = (row["center_lat"], row["center_lng"]) if row else _geocode(city)
    if not coords:
        return jsonify({"available": False, "reason": "unknown_city", "days": []})

    key = (city, start_d.isoformat(), days)
    hit = _WEATHER_CACHE.get(key)
    if hit and time.time() - hit[0] < _WEATHER_TTL:
        return jsonify(hit[1])

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": coords[0],
                "longitude": coords[1],
                "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Asia/Shanghai",
                "start_date": max(start_d, today).isoformat(),
                "end_date": end_d.isoformat(),
            },
            timeout=6,
        )
        resp.raise_for_status()
        daily = resp.json()["daily"]
    except Exception as e:  # noqa: BLE001 — 天气是锦上添花，任何失败都降级
        logger.warning("天气获取失败: %s", e)
        return jsonify({"available": False, "reason": "upstream", "days": []})

    by_date = {
        d: {
            "date": d,
            "code": daily["weathercode"][i],
            "tmax": daily["temperature_2m_max"][i],
            "tmin": daily["temperature_2m_min"][i],
            "rain_prob": daily["precipitation_probability_max"][i],
        }
        for i, d in enumerate(daily["time"])
    }
    out = []
    for i in range(days):
        d = (start_d + timedelta(days=i)).isoformat()
        out.append(by_date.get(d, {"date": d, "code": None}))
    payload = {"available": True, "city": city, "days": out}
    _WEATHER_CACHE[key] = (time.time(), payload)
    return jsonify(payload)
