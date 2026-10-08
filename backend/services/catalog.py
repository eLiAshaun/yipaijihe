"""
景点库写入：把联网搜索 / 视频识别得到的地点存进 attractions 表。

存进去之后：生成行程时能按名称匹配到完整数据（建议时段、贴士、消费档位），
该城市会出现在城市列表里，下次打开不用再等搜索。
"""

from __future__ import annotations

import json
import logging

from backend.database import get_db

logger = logging.getLogger(__name__)

_DB_TYPES = ("landmark", "street", "food", "culture")
_COSTS = ("免费", "低", "中等", "较高", "高")


def ensure_city(city: str) -> None:
    """城市表里没有这个城市时，用地理编码补一条（地图中心、天气都依赖它）"""
    from backend.services.geo import city_center, wgs84_to_gcj02

    db = get_db()
    try:
        if db.execute("SELECT 1 FROM cities WHERE name = ?", (city,)).fetchone():
            return
        center = city_center(city)
        if not center:
            return
        lat, lng = wgs84_to_gcj02(*center)
        db.execute(
            "INSERT OR IGNORE INTO cities (name, center_lat, center_lng, zoom, transit_info, accommodation, description) VALUES (?,?,?,?,?,?,?)",
            (city, lat, lng, 12, "[]", "[]", ""),
        )
        db.commit()
    finally:
        db.close()


def upsert_places(city: str, places: list[dict], category: str = "联网推荐") -> list[dict]:
    """
    写入有坐标的地点（同名已存在则保留原数据），返回带数据库 id（loc_xxx）的地点列表。
    已在景点库里的地点沿用库里的 id，这样生成行程时会用到库里更完整的数据。
    """
    if not places:
        return places
    from backend.services.inspiration import _aliases

    ensure_city(city)
    db = get_db()
    try:
        # 「外滩」和库里的「外滩夜景」、「武康大楼」和「武康路·武康大楼」是同一个地方：沿用库里那条
        existing = db.execute("SELECT id, name FROM attractions WHERE city = ?", (city,)).fetchall()
        alias_ids = {a: f"loc_{r['id']:03d}" for r in existing for a in _aliases(r["name"])}
        for p in places:
            name = (p.get("name") or "").strip()
            if name in alias_ids:
                p["id"] = alias_ids[name]
                continue
            if not name or p.get("lat") is None or p.get("lng") is None:
                continue
            raw_type = p.get("type")
            try:
                db.execute(
                    """INSERT OR IGNORE INTO attractions
                       (name, city, type, category, description, address, lat, lng, tags, crowd_level, cost_level,
                        duration_min, best_time, suitable_for, personality_fit, tips, risks)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        name[:100],
                        city,
                        raw_type if raw_type in _DB_TYPES else "landmark",
                        (p.get("category") or ("自然风光" if raw_type == "nature" else category))[:50],
                        (p.get("description") or p.get("reason") or "")[:2000],
                        (p.get("address") or "")[:200],
                        float(p["lat"]),
                        float(p["lng"]),
                        json.dumps(p.get("tags") or p.get("keywords") or [], ensure_ascii=False),
                        p.get("crowd_level") if p.get("crowd_level") in ("low", "medium", "high") else "medium",
                        p.get("cost_level") if p.get("cost_level") in _COSTS else "中等",
                        max(10, min(int(p.get("duration_min") or 60), 480)),
                        (p.get("best_time") or "全天")[:50],
                        "[]",
                        json.dumps(p.get("travel_style_fit") or {}, ensure_ascii=False),
                        (p.get("tips") or "")[:500],
                        (p.get("risks") or "")[:500],
                    ),
                )
            except Exception as e:  # noqa: BLE001 — 单条脏数据不影响其他
                logger.warning("保存地点 [%s] 失败: %s", name, e)
        db.commit()
        names = [p["name"] for p in places if p.get("name")]
        rows = db.execute(
            f"SELECT id, name FROM attractions WHERE city = ? AND name IN ({','.join('?' * len(names))})", (city, *names)
        ).fetchall() if names else []
    finally:
        db.close()
    ids = {r["name"]: f"loc_{r['id']:03d}" for r in rows}
    for p in places:
        if p.get("name") in ids and not str(p.get("id") or "").startswith("loc_"):
            p["id"] = ids[p["name"]]
    return places
