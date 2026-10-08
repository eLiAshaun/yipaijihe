"""
路线规划路由（从数据库读取 + 支持保存旅行历史）
"""

import json
import logging
from flask import Blueprint, jsonify, request
from backend.database import get_db
from backend.services.llm_service import generate_itinerary

logger = logging.getLogger(__name__)

itinerary_bp = Blueprint("itinerary", __name__)


def _db_row_to_location(row):
    """将数据库行转为地点字典"""
    return {
        "id": f"loc_{row['id']:03d}",
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


@itinerary_bp.route("/generate", methods=["POST"])
def generate():
    """
    生成个性化旅行路线

    请求体：
    {
        "destination": "上海", "days": 2, "pace": "balanced", "start_date": "2026-10-12",
        "budget_amount": 800, "companions": "和搭子一起",
        "preview_locations": [{"name": "外滩", "lat": 31.24, "lng": 121.49, ...}],  # 地点筛选页勾选的地点（优先）
        "selected_locations": ["loc_001"],                                            # 或者直接给景点库 id
        "profile": {"mbti": "DRPT", "di_label": "记录表达型", ...}
    }
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请提供旅行配置"}), 400

    try:
        days = max(1, min(int(data.get("days") or 2), 14))
    except (TypeError, ValueError):
        return jsonify({"error": "天数需要是 1-14 的整数"}), 400
    profile = data.get("profile") or {}
    city = (data.get("destination") or "上海").strip()[:20]

    db = get_db()
    try:
        catalog = [_db_row_to_location(r) for r in db.execute("SELECT * FROM attractions WHERE city = ?", (city,)).fetchall()]
    finally:
        db.close()

    preview = data.get("preview_locations") or []
    if preview:
        locations = _convert_preview_locations(preview, catalog)
    else:
        ids = set(data.get("selected_locations") or [])
        locations = [l for l in catalog if l["id"] in ids] if ids else _recommend_locations(catalog, profile, days)
        video_locations = data.get("video_locations") or []
        if video_locations:
            existing = {l["name"] for l in locations}
            locations += [v for v in _convert_preview_locations(video_locations, catalog) if v["name"] not in existing]

    if not locations:
        return jsonify({"error": "没有可用的地点：请先在「地点筛选」里至少选一个"}), 400

    trip_config = {
        "days": days,
        "pace": data.get("pace"),
        "start_date": data.get("start_date") or "",
        "city": city,
        "companions": data.get("companions", ""),
        "budget": data.get("budget") or (f"人均 ¥{data['budget_amount']}" if data.get("budget_amount") else ""),
    }
    itinerary = generate_itinerary(locations, profile, trip_config, catalog)

    by_id = {l["id"]: l for l in catalog + locations}
    used_ids = {i.get("location_id") for d in itinerary.get("days", []) for i in d.get("items", []) if i.get("location_id")}
    return jsonify({
        "itinerary": itinerary,
        "locations_used": [by_id[i] for i in used_ids if i in by_id],
        "engine": "llm" if itinerary.pop("_engine", "") == "llm" else "local",
    })


@itinerary_bp.route("/save", methods=["POST"])
def save_itinerary():
    """兼容旧接口：保存行程到当前用户（新代码请用 POST /api/trips）"""
    from backend.routes.auth import _get_current_user
    from backend.services import trips as repo

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请提供旅行数据"}), 400
    user = _get_current_user()
    if not user:
        return jsonify({"error": "请先登录"}), 401
    try:
        trip = repo.create_trip(user, data)
    except repo.TripError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"message": "旅行已保存", "trip": trip}), 201


def _convert_preview_locations(preview_locations: list, catalog: list | None = None) -> list:
    """
    把前端传来的地点（AI 推荐 / 视频提取 / 景点库 / 用户手动添加）统一成景点库格式。
    能在景点库里找到的（按 id 或名称）直接用库里的完整数据（建议时段、贴士、消费档位等）；
    缺坐标的地点保持缺失，交给行程引擎放到当天末尾并提示，而不是编造一个市中心坐标。
    """
    catalog = catalog or []
    by_id = {l["id"]: l for l in catalog}
    by_name = {l["name"]: l for l in catalog}
    converted = []
    for i, vl in enumerate(preview_locations):
        if not isinstance(vl, dict) or not (vl.get("name") or "").strip():
            continue
        name = vl["name"].strip()
        base = by_id.get(vl.get("id")) or by_name.get(name) or next((c for c in catalog if name in c["name"].split("·") or c["name"].split("·")[0] == name), None)
        if base:
            loc = dict(base)
            if vl.get("reason"):
                loc["reason"] = vl["reason"]
            converted.append(loc)
            continue
        lat, lng = vl.get("lat"), vl.get("lng")
        try:
            lat, lng = (float(lat), float(lng)) if lat not in (None, "") and lng not in (None, "") else (None, None)
        except (TypeError, ValueError):
            lat, lng = None, None
        converted.append({
            "id": str(vl.get("id") or f"preview_{i:03d}")[:40],
            "name": name[:60],
            "type": vl.get("type") if vl.get("type") in ("food", "nature", "culture", "landmark", "street") else "landmark",
            "category": vl.get("category") or "用户精选",
            "lat": lat,
            "lng": lng,
            "address": vl.get("address") or "",
            "description": vl.get("description") or vl.get("video_hint") or "",
            "reason": vl.get("reason") or "",
            "tags": vl.get("keywords") or vl.get("tags") or [],
            "crowd_level": "medium",
            "cost_level": vl.get("cost_level") or "中等",
            "duration_min": vl.get("duration_min") or None,
            "best_time": vl.get("best_time") or "",
            "suitable_for": [],
            "travel_style_fit": vl.get("travel_style_fit") or vl.get("personality_fit") or {},
            "tips": vl.get("tips") or "",
            "risks": vl.get("risks") or "",
            "source": vl.get("source") or "preview",
        })
    return converted


def _recommend_locations(all_locations: list, profile: dict, days: int) -> list:
    """根据用户画像推荐地点"""
    if not profile:
        return all_locations[:min(days * 4, len(all_locations))]
    ranked = sorted(all_locations, key=lambda loc: persona_score(loc, profile.get("mbti", "")), reverse=True)
    return ranked[: days * 4]


_FIT_RULES = [  # (维度位, 字母, travel_style_fit 字段, 匹配值)
    (0, "D", "pace", ("any", "rush")), (0, "I", "pace", ("any", "slow")),
    (1, "R", "pref", ("any", "classic")), (1, "L", "pref", ("any", "hidden")),
    (2, "P", "exp", ("any", "scene")), (2, "S", "exp", ("any", "food")),
    (3, "C", "social", ("any", "social")), (3, "T", "social", ("any", "solo")),
]


def persona_score(loc: dict, mbti: str) -> int:
    """地点与旅行人格四个维度的契合分（0-8，每个维度 2 分）"""
    fit = loc.get("travel_style_fit") or {}
    mbti = mbti or ""
    return sum(2 for pos, letter, key, ok in _FIT_RULES if len(mbti) > pos and mbti[pos] == letter and fit.get(key) in ok)
