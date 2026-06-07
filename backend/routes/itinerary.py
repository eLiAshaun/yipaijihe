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
        "destination": "上海",
        "days": 2,
        "companions": "朋友",
        "budget": "中等",
        "selected_locations": ["loc_001", "loc_002"],
        "preview_locations": [{"name": "外滩", "lat": 31.24, "lng": 121.49, ...}],
        "profile": { "mbti": "SHFS", ... }
    }

    其中 preview_locations 为用户在"地图预览"页勾选保留的地点列表（优先级最高），
    一旦提供，行程将直接基于这些地点生成，不再走 selected_locations / MBTI 推荐 / 视频合并逻辑。
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供旅行配置"}), 400

    days = data.get("days", 2)
    companions = data.get("companions", "")  # 可选字段
    budget = data.get("budget", "中等")
    profile = data.get("profile", {})
    selected_ids = data.get("selected_locations", [])
    city = data.get("destination", "上海")

    # 从数据库读取地点
    db = get_db()
    try:
        all_rows = db.execute(
            "SELECT * FROM attractions WHERE city = ?", (city,)
        ).fetchall()
        all_locations = [_db_row_to_location(r) for r in all_rows]
    finally:
        db.close()

    # 用户在"地图预览"页选中的景点（可能来自视频分析结果，也可能来自 AI 筛选的默认推荐景点）
    # 一旦提供，行程将直接基于这些用户选中的景点生成，不再走 MBTI 推荐 / 数据库 ID 筛选 / 视频合并逻辑，
    # 确保"路径规划和行程安排"严格基于用户在上一步实际选中的地点
    preview_locations = data.get("preview_locations", [])

    if preview_locations:
        locations = _convert_preview_locations(preview_locations)
        logger.info(f"基于地图预览页用户选中的 {len(locations)} 个景点生成行程")
    else:
        # 筛选地点
        if selected_ids:
            locations = [l for l in all_locations if l["id"] in selected_ids]
        else:
            locations = _recommend_locations(all_locations, profile, days)

        # 合并视频分析提取的地点（相似景点采纳视频数据，不相似则新增）
        video_locations = data.get("video_locations", [])
        if video_locations:
            video_locs = _convert_video_locations(video_locations, locations)
            # 分离：merged（替换原有）和 pure_video（新增）
            merged_ids = set()
            pure_video = []
            for vl in video_locs:
                if vl.get("source") == "video_merged":
                    merged_ids.add(vl["id"])
                else:
                    pure_video.append(vl)

            # 用 merged 版本替换原有 locations 中的对应项
            if merged_ids:
                merged_map = {vl["id"]: vl for vl in video_locs if vl.get("source") == "video_merged"}
                locations = [merged_map.get(loc["id"], loc) for loc in locations]

            # 添加纯视频新景点（去重）
            existing_names = {l["name"] for l in locations}
            for vl in pure_video:
                if vl["name"] not in existing_names:
                    locations.append(vl)
                    existing_names.add(vl["name"])

            logger.info(f"合并了 {len(video_locations)} 个视频提取地点，"
                         f"其中 {len(merged_ids)} 个采纳视频数据，"
                         f"{len(pure_video)} 个为新景点，当前共 {len(locations)} 个地点")

    if not locations:
        return jsonify({"error": "没有可用的地点"}), 400

    trip_config = {"days": days, "companions": companions, "budget": budget}

    # 调用 LLM 或规则引擎生成路线
    itinerary = generate_itinerary(locations, profile, trip_config)

    # 补充地点详细信息（包含数据库地点 + 视频提取地点）
    loc_map = {l["id"]: l for l in all_locations}
    # 将视频地点也加入 loc_map（如果还没在其中）
    for l in locations:
        if l["id"] not in loc_map:
            loc_map[l["id"]] = l
    for day in itinerary.get("days", []):
        for item in day.get("items", []):
            loc = loc_map.get(item.get("location_id"))
            if loc:
                item["location"] = {
                    "name": loc["name"],
                    "lat": loc["lat"],
                    "lng": loc["lng"],
                    "type": loc["type"],
                    "category": loc["category"],
                    "duration_min": loc["duration_min"],
                    "cost_level": loc["cost_level"],
                }

    # 补充推荐池的地点详细信息
    for rec in itinerary.get("recommendations", []):
        loc = loc_map.get(rec.get("location_id"))
        if loc:
            rec["location"] = {
                "name": loc["name"],
                "lat": loc["lat"],
                "lng": loc["lng"],
                "type": loc["type"],
                "category": loc["category"],
                "duration_min": loc["duration_min"],
                "cost_level": loc["cost_level"],
                "description": loc.get("description", ""),
                "tags": loc.get("tags", []),
            }

    return jsonify({
        "itinerary": itinerary,
        "locations_used": [loc_map[lid] for lid in
                          set(item.get("location_id")
                              for day in itinerary.get("days", [])
                              for item in day.get("items", [])
                              if item.get("location_id")) if lid in loc_map],
    })


@itinerary_bp.route("/save", methods=["POST"])
def save_itinerary():
    """
    保存路线到用户旅行历史（需登录）

    请求体：{ "token": "xxx", "city": "上海", "days": 2, "itinerary": {...}, ... }
    """
    from backend.routes.auth import _get_current_user

    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供旅行数据"}), 400

    user = _get_current_user()
    if not user:
        return jsonify({"error": "请先登录"}), 401

    from datetime import datetime

    trip = {
        "city": data.get("city", "上海"),
        "days": data.get("days", 2),
        "companions": data.get("companions", ""),
        "budget": data.get("budget", ""),
        "mbti_type": user.get("mbti_type"),
        "itinerary": data.get("itinerary"),
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    db = get_db()
    try:
        row = db.execute(
            "SELECT travel_history FROM users WHERE id = ?", (user["id"],)
        ).fetchone()

        history = json.loads(row["travel_history"]) if row["travel_history"] else []
        history.append(trip)

        db.execute(
            "UPDATE users SET travel_history = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(history, ensure_ascii=False), user["id"])
        )
        db.commit()
        return jsonify({"message": "旅行已保存", "trip": trip}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _normalize_name(name: str) -> str:
    """标准化名称用于相似度比较"""
    import re
    # 去除标点、空格、常见后缀
    name = name.strip()
    for ch in ["·", "—", "-", "（", "）", "(", ")", "：", ":", "，", ",", "、"]:
        name = name.replace(ch, "")
    name = re.sub(r"\s+", "", name)
    return name.lower()


def _is_similar_location(video_name: str, db_name: str) -> bool:
    """判断视频提取的景点名和数据库景点名是否高度相似"""
    vn = _normalize_name(video_name)
    dn = _normalize_name(db_name)
    if not vn or not dn:
        return False
    # 完全匹配
    if vn == dn:
        return True
    # 一方包含另一方（如 "外滩" vs "外滩夜景"）
    if vn in dn or dn in vn:
        return True
    # 计算简单字符重叠率
    common = sum(1 for c in vn if c in dn)
    if common / max(len(vn), len(dn)) > 0.7:
        return True
    return False


def _convert_video_locations(video_locations: list, existing_locations: list = None) -> list:
    """
    将视频分析提取的地点转换为与数据库地点相同格式。
    如果与已有景点高度相似，采纳视频分析数据（更新坐标等）并合并。
    """
    existing_locations = existing_locations or []
    existing_names = {loc["name"]: loc for loc in existing_locations}

    converted = []
    for i, vl in enumerate(video_locations):
        if not isinstance(vl, dict) or not vl.get("name"):
            continue

        # 检查是否与已有景点相似
        matched_existing = None
        for ename, eloc in existing_names.items():
            if _is_similar_location(vl["name"], ename):
                matched_existing = eloc
                break

        if matched_existing:
            # 相似 → 采纳视频分析数据，更新坐标和描述，保留原有元数据
            merged = {**matched_existing}
            # 视频分析如果有更精确的坐标则采用
            if vl.get("lat") and vl.get("lng") and vl["lat"] != 31.2304:
                merged["lat"] = vl["lat"]
                merged["lng"] = vl["lng"]
            # 视频分析的描述/关键词作为补充
            if vl.get("reason"):
                merged["description"] = vl["reason"]
            if vl.get("keywords"):
                existing_tags = set(merged.get("tags", []))
                existing_tags.update(vl["keywords"])
                merged["tags"] = list(existing_tags)
            if vl.get("travel_style_fit"):
                merged["travel_style_fit"] = vl["travel_style_fit"]
            merged["source"] = "video_merged"
            converted.append(merged)
            # 从已有列表中移除，避免重复
            del existing_names[ename]
        else:
            # 不相似 → 作为新景点添加
            converted.append({
                "id": f"video_{i:03d}",
                "name": vl["name"],
                "type": "landmark",
                "category": "视频推荐",
                "lat": vl.get("lat") or 31.2304,
                "lng": vl.get("lng") or 121.4737,
                "address": "",
                "description": vl.get("reason", ""),
                "tags": vl.get("keywords", []),
                "crowd_level": "medium",
                "cost_level": "中等",
                "duration_min": 60,
                "best_time": "全天",
                "suitable_for": [],
                "travel_style_fit": vl.get("travel_style_fit", {}),
                "tips": "",
                "risks": "",
                "source": "video",
            })
    return converted


def _convert_preview_locations(preview_locations: list) -> list:
    """
    将"地图预览"页面中用户勾选保留的景点转换为与数据库地点相同格式。
    这些景点可能来自 AI（豆包）按用户旅行风格主画像筛选出的默认推荐景点，
    也可能来自视频分析结果或本地数据库兜底列表，均带有
    name / lat / lng / type / keywords(或 tags) / reason(或 description) 等字段。
    """
    converted = []
    for i, vl in enumerate(preview_locations):
        if not isinstance(vl, dict) or not vl.get("name"):
            continue
        converted.append({
            "id": f"preview_{i:03d}",
            "name": vl["name"],
            "type": vl.get("type") or "landmark",
            "category": vl.get("category") or "用户精选",
            "lat": vl.get("lat") or 31.2304,
            "lng": vl.get("lng") or 121.4737,
            "address": vl.get("address") or "",
            "description": vl.get("reason") or vl.get("description") or vl.get("video_hint") or "",
            "tags": vl.get("keywords") or vl.get("tags") or [],
            "crowd_level": "medium",
            "cost_level": "中等",
            "duration_min": vl.get("duration_min") or 60,
            "best_time": "全天",
            "suitable_for": [],
            "travel_style_fit": vl.get("travel_style_fit") or vl.get("personality_fit") or {},
            "tips": "",
            "risks": "",
            "source": "preview",  # 标记来源为地图预览页用户精选
        })
    return converted


def _recommend_locations(all_locations: list, profile: dict, days: int) -> list:
    """根据用户画像推荐地点"""
    if not profile:
        return all_locations[:min(days * 4, len(all_locations))]

    mbti = profile.get("mbti", "")

    scored = []
    for loc in all_locations:
        score = 0
        fit = loc.get("travel_style_fit", {})

        if mbti and len(mbti) >= 1:
            pace = mbti[0]
            if pace == "D" and fit.get("pace") in ["any", "rush"]:
                score += 2
            elif pace == "I" and fit.get("pace") in ["any", "slow"]:
                score += 2

        if mbti and len(mbti) >= 2:
            pref = mbti[1]
            if pref == "R" and fit.get("pref") in ["any", "classic"]:
                score += 2
            elif pref == "L" and fit.get("pref") in ["any", "hidden"]:
                score += 2

        if mbti and len(mbti) >= 3:
            exp = mbti[2]
            if exp == "P" and fit.get("exp") in ["any", "scene"]:
                score += 2
            elif exp == "S" and fit.get("exp") in ["any", "food"]:
                score += 2

        if mbti and len(mbti) >= 4:
            social = mbti[3]
            if social == "C" and fit.get("social") in ["any", "social"]:
                score += 2
            elif social == "T" and fit.get("social") in ["any", "solo"]:
                score += 2

        scored.append((score, loc))

    scored.sort(key=lambda x: x[0], reverse=True)
    max_locs = days * 4
    return [loc for _, loc in scored[:max_locs]]
