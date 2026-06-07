"""
地点与视频内容路由（从数据库读取）
"""

import json
from flask import Blueprint, jsonify, request
from backend.database import get_db
from backend.services.llm_service import discover_trip_attractions, filter_default_attractions

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


@locations_bp.route("/videos", methods=["GET"])
def get_videos():
    """获取模拟的抖音精选视频列表（从数据库读取地点后构造视频信息）"""
    from backend.data.shanghai_locations import SHANGHAI_LOCATIONS

    db = get_db()
    try:
        rows = db.execute("SELECT * FROM attractions ORDER BY id").fetchall()
        videos = []
        for row in rows:
            # 用原始数据中的 video_source（数据库未存此字段，从 Python 数据补充）
            loc_id = f"loc_{row['id']:03d}"
            orig = next((l for l in SHANGHAI_LOCATIONS if l["id"] == loc_id), {})
            vs = orig.get("video_source", {})

            videos.append({
                "id": f"video_{loc_id}",
                "title": vs.get("title", f"探索{row['name']}"),
                "author": vs.get("author", "@旅行达人"),
                "likes": vs.get("likes", 10000),
                "cover_color": vs.get("cover_color", "#333"),
                "location_id": loc_id,
                "location_name": row["name"],
                "tags": json.loads(row["tags"]) if row["tags"] else [],
                "description": row["description"] or "",
                "category": row["category"],
            })

        videos.sort(key=lambda v: v["likes"], reverse=True)
        return jsonify({"videos": videos})
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


# 静态默认推荐景点（降级方案）
DEFAULT_RECOMMEND_ATTRACTIONS = [
    {"name": "南京路", "type": "street", "lat": 31.2350, "lng": 121.4740, "keywords": ["购物", "步行街"], "video_hint": "上海最繁华的商业街"},
    {"name": "豫园", "type": "culture", "lat": 31.2270, "lng": 121.4920, "keywords": ["古典园林", "小吃"], "video_hint": "江南园林与城隍庙小吃"},
    {"name": "外滩", "type": "landmark", "lat": 31.2400, "lng": 121.4900, "keywords": ["夜景", "万国建筑"], "video_hint": "上海地标，必打卡"},
    {"name": "东方明珠", "type": "landmark", "lat": 31.2397, "lng": 121.4998, "keywords": ["电视塔", "俯瞰"], "video_hint": "上海天际线标志"},
    {"name": "陆家嘴", "type": "landmark", "lat": 31.2355, "lng": 121.5010, "keywords": ["金融中心", "摩天大楼"], "video_hint": "现代上海的代表"},
    {"name": "四行仓库", "type": "culture", "lat": 31.2470, "lng": 121.4730, "keywords": ["历史", "抗战"], "video_hint": "铭记历史的红色景点"},
    {"name": "武康路", "type": "street", "lat": 31.2100, "lng": 121.4380, "keywords": ["梧桐", "老洋房"], "video_hint": "网红打卡梧桐街道"},
    {"name": "田子坊", "type": "street", "lat": 31.2130, "lng": 121.4660, "keywords": ["文创", "弄堂"], "video_hint": "文艺小店聚集地"},
]


@locations_bp.route("/default-recommend", methods=["POST"])
def default_recommend():
    """
    获取默认推荐景点
    优先用豆包联网搜索发现热门地点，失败则降级到静态列表
    请求体：{ "profile": {...}, "city": "上海", "days": 3 }
    """
    data = request.get_json() or {}
    profile = data.get("profile", {})
    city = data.get("city", "上海")
    days = data.get("days", 3)

    # 优先联网搜索
    attractions = discover_trip_attractions(city, days, profile)

    # 降级到静态列表（用显式标志位记录是否发生了降级，
    # 不要靠"内容是否相同"去反推——filter_default_attractions 会原地修改/拷贝字典，
    # 导致降级后的列表内容也可能与 DEFAULT_RECOMMEND_ATTRACTIONS 不完全相等，从而误判来源）
    used_fallback = False
    if not attractions:
        used_fallback = True
        attractions = [loc.copy() for loc in DEFAULT_RECOMMEND_ATTRACTIONS]
        if profile:
            attractions = filter_default_attractions(profile, attractions)

    return jsonify({
        "attractions": attractions,
        "source": "default" if used_fallback else "web_search",
        # 显式告知前端是否发生了降级，前端可据此弹出提示，
        # 避免用户在不知情的情况下一直看到"本地静态库"的内容、误以为是豆包搜索结果
        "fallback": used_fallback,
        "fallback_message": (
            "豆包 AI 联网搜索调用失败或暂不可用，已自动切换为本地静态推荐景点库"
            if used_fallback else ""
        ),
        "query_phrase": f"{city}{days}日游攻略",
    })
