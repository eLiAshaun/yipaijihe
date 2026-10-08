"""
地点与视频内容路由（从数据库读取）
"""

import json
from flask import Blueprint, jsonify, request
from backend.database import get_db
from backend.services.llm_service import discover_trip_attractions

locations_bp = Blueprint("locations", __name__)


def _row_to_location(row):
    """将数据库行转为地点字典"""
    return {
        "id": f"loc_{row['id']:03d}",
        "db_id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "category": row["category"],
        "lat": row["lat"],
        "lng": row["lng"],
        "address": row["address"] or "",
        "description": row["description"] or "",
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "crowd_level": row["crowd_level"] or "medium",
        "cost_level": row["cost_level"] or "中等",
        "duration_min": row["duration_min"] or 60,
        "best_time": row["best_time"] or "全天",
        "suitable_for": json.loads(row["suitable_for"]) if row["suitable_for"] else [],
        "travel_style_fit": json.loads(row["personality_fit"]) if row["personality_fit"] else {},
        "tips": row["tips"] or "",
        "risks": row["risks"] or "",
    }


@locations_bp.route("/list", methods=["GET"])
def list_locations():
    """获取所有地点列表"""
    loc_type = request.args.get("type")
    tag = request.args.get("tag")
    city = request.args.get("city", "上海")

    db = get_db()
    try:
        query = "SELECT * FROM attractions WHERE city = ?"
        params = [city]

        if loc_type:
            query += " AND type = ?"
            params.append(loc_type)

        rows = db.execute(query, params).fetchall()
        locations = [_row_to_location(r) for r in rows]

        if tag:
            locations = [l for l in locations if tag in l["tags"]]

        # 获取城市信息
        city_row = db.execute(
            "SELECT * FROM cities WHERE name = ?", (city,)
        ).fetchone()

        city_center = {
            "name": city,
            "lat": city_row["center_lat"],
            "lng": city_row["center_lng"],
            "zoom": city_row["zoom"],
        } if city_row else {"name": city, "lat": 31.2304, "lng": 121.4737, "zoom": 13}

        from backend.data.shanghai_locations import LOCATION_TYPES
        return jsonify({
            "locations": locations,
            "total": len(locations),
            "city_center": city_center,
            "types": LOCATION_TYPES,
        })
    finally:
        db.close()


@locations_bp.route("/<location_id>", methods=["GET"])
def get_location(location_id):
    """获取单个地点详情"""
    # 支持 loc_001 格式和纯数字格式
    try:
        db_id = int(location_id.replace("loc_", ""))
    except ValueError:
        return jsonify({"error": "无效的地点 ID"}), 400

    db = get_db()
    try:
        row = db.execute("SELECT * FROM attractions WHERE id = ?", (db_id,)).fetchone()
        if not row:
            return jsonify({"error": "地点不存在"}), 404
        return jsonify({"location": _row_to_location(row)})
    finally:
        db.close()


@locations_bp.route("/city", methods=["GET"])
def get_city_info():
    """获取城市信息"""
    city = request.args.get("city", "上海")
    db = get_db()
    try:
        row = db.execute("SELECT * FROM cities WHERE name = ?", (city,)).fetchone()
        if not row:
            return jsonify({"error": "城市不存在"}), 404

        return jsonify({
            "city": {
                "name": row["name"],
                "center": {"lat": row["center_lat"], "lng": row["center_lng"], "zoom": row["zoom"]},
                "transit_info": json.loads(row["transit_info"]) if row["transit_info"] else [],
                "accommodation": json.loads(row["accommodation"]) if row["accommodation"] else [],
                "description": row["description"] or "",
            }
        })
    finally:
        db.close()


@locations_bp.route("/default-recommend", methods=["POST"])
def default_recommend():
    """
    地点筛选页的候选地点：
      · 开启联网搜索时：搜索「{城市}{天数}日游攻略」归纳高频地点，并按人格筛选
      · 否则：使用该城市的完整内置景点库，按旅行人格契合度排序并给出契合理由
    请求体：{ "profile": {...}, "city": "上海", "days": 3 }
    """
    from backend.routes.itinerary import persona_score

    data = request.get_json(silent=True) or {}
    profile = data.get("profile") or {}
    city = (data.get("city") or "上海").strip()[:20]
    try:
        days = max(1, min(int(data.get("days") or 3), 14))
    except (TypeError, ValueError):
        days = 3

    attractions = discover_trip_attractions(city, days, profile)
    if attractions:
        return jsonify({"attractions": attractions, "source": "web_search", "message": "", "query_phrase": f"{city}{days}日游攻略"})

    db = get_db()
    try:
        rows = db.execute("SELECT * FROM attractions WHERE city = ?", (city,)).fetchall()
        catalog = [_row_to_location(r) for r in rows]
    finally:
        db.close()
    if not catalog:
        return jsonify({
            "attractions": [],
            "source": "none",
            "message": f"「{city}」还没有内置景点库。在 .env 里配置 DOUBAO_API_KEY 开启联网搜索后即可规划，或者在下方手动添加地点。",
        })

    mbti = profile.get("mbti") or ""
    labels = {"pace": profile.get("di_label"), "pref": profile.get("rl_label"), "exp": profile.get("ps_label"), "social": profile.get("cd_label")}
    for loc in catalog:
        score = persona_score(loc, mbti)
        loc["fit_score"] = score
        loc["reason"] = loc.get("tips") or loc.get("description") or ""
        matched = [v for k, v in labels.items() if v and (loc.get("travel_style_fit") or {}).get(k) not in (None, "")]
        if mbti and score >= 6 and matched:
            loc["reason"] = f"契合你的{'、'.join(matched[:2])}偏好 · " + loc["reason"]
    catalog.sort(key=lambda l: l.get("fit_score", 0), reverse=True)
    if mbti:
        # 预选：契合度高的全部选上；不够时按契合度补足到「每天 3 个」，避免行程太空
        enough = max(sum(1 for l in catalog if l["fit_score"] >= 6), days * 3)
        for i, loc in enumerate(catalog):
            loc["selected"] = i < enough
    return jsonify({
        "attractions": catalog,
        "source": "local",
        "message": "" if mbti else "完成旅行人格测试后，会按你的风格自动预选",
        "query_phrase": f"{city}{days}日游攻略",
    })
