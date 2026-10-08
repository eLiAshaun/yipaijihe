"""
灵感素材：粘贴任意文字（小红书 / 抖音文案、攻略、地名清单），提取可以去的地点
"""

from flask import Blueprint, jsonify, request

from backend.database import get_db
from backend.routes.auth import login_required
from backend.services.inspiration import extract_places

inspiration_bp = Blueprint("inspiration", __name__)


@inspiration_bp.post("/extract")
@login_required
def extract():
    from backend.routes.itinerary import _db_row_to_location

    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "请粘贴一些文字"}), 400
    if len(text) > 20000:
        return jsonify({"error": "文字太长了，请分几次粘贴（每次 2 万字以内）"}), 400
    city = str(data.get("city") or "上海")[:20]
    db = get_db()
    try:
        catalog = [_db_row_to_location(r) for r in db.execute("SELECT * FROM attractions WHERE city = ?", (city,)).fetchall()]
    finally:
        db.close()
    from backend.services.geo import fill_missing

    places = fill_missing(extract_places(text, city, catalog), city)
    return jsonify({"places": places, "count": len(places)})
