"""
数据库管理模块 - SQLite
"""

import json
import sqlite3
import logging
from backend.config import Config

logger = logging.getLogger(__name__)


def get_db():
    """获取数据库连接（Row 模式）"""
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库：建表 + 插入种子数据"""
    conn = get_db()
    cursor = conn.cursor()

    # ========== 建表 ==========

    # 用户表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE
                          CHECK(length(username) BETWEEN 3 AND 20),
            password_hash TEXT    NOT NULL,
            mbti_type     TEXT    CHECK(mbti_type IS NULL OR length(mbti_type) BETWEEN 4 AND 5),
            mbti_result   TEXT,
            travel_history TEXT,
            session_token TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 景点表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attractions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT    NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
            city           TEXT    NOT NULL CHECK(length(city) BETWEEN 1 AND 50),
            type           TEXT    NOT NULL
                           CHECK(type IN ('landmark','street','food','culture')),
            category       TEXT    NOT NULL CHECK(length(category) BETWEEN 1 AND 50),
            description    TEXT    CHECK(description IS NULL OR length(description) <= 2000),
            address        TEXT    CHECK(address IS NULL OR length(address) <= 200),
            lat            REAL    NOT NULL CHECK(lat BETWEEN -90 AND 90),
            lng            REAL    NOT NULL CHECK(lng BETWEEN -180 AND 180),
            tags           TEXT,
            crowd_level    TEXT    CHECK(crowd_level IN ('low','medium','high')),
            cost_level     TEXT    CHECK(cost_level IN ('免费','低','中等','较高','高')),
            duration_min   INTEGER CHECK(duration_min BETWEEN 10 AND 480),
            best_time      TEXT    CHECK(best_time IS NULL OR length(best_time) <= 50),
            suitable_for   TEXT,
            personality_fit TEXT,
            tips           TEXT    CHECK(tips IS NULL OR length(tips) <= 500),
            risks          TEXT    CHECK(risks IS NULL OR length(risks) <= 500),
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, city)
        )
    """)

    # 城市表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cities (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT    NOT NULL UNIQUE CHECK(length(name) BETWEEN 1 AND 50),
            center_lat     REAL    NOT NULL CHECK(center_lat BETWEEN -90 AND 90),
            center_lng     REAL    NOT NULL CHECK(center_lng BETWEEN -180 AND 180),
            zoom           INTEGER DEFAULT 13 CHECK(zoom BETWEEN 1 AND 18),
            transit_info   TEXT,
            accommodation  TEXT,
            description    TEXT    CHECK(description IS NULL OR length(description) <= 1000)
        )
    """)

    # 行程表（取代 users.travel_history 这个 JSON 大字段：可单条增删改、可分享）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            id          TEXT    PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title       TEXT    NOT NULL DEFAULT '',
            city        TEXT    NOT NULL DEFAULT '上海',
            days        INTEGER NOT NULL DEFAULT 1,
            budget      INTEGER NOT NULL DEFAULT 0,
            companions  TEXT    NOT NULL DEFAULT '',
            start_date  TEXT,
            mbti_type   TEXT,
            itinerary   TEXT    NOT NULL,
            meta        TEXT,
            share_token TEXT    UNIQUE,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trips_user ON trips(user_id, updated_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attractions_city ON attractions(city)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attractions_type ON attractions(type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_session ON users(session_token)")

    conn.commit()

    _ensure_columns(conn)
    _migrate_legacy_history(conn)

    # ========== 种子数据（仅首次） ==========
    cursor.execute("SELECT COUNT(*) FROM attractions")
    if cursor.fetchone()[0] == 0:
        _seed_data(conn)
        logger.info("✅ 种子数据已插入")

    conn.close()
    logger.info(f"📦 数据库初始化完成: {Config.DB_PATH}")


def _seed_data(conn):
    """插入种子数据"""
    cursor = conn.cursor()

    # --- 从 shanghai_locations.py 导入景点 ---
    from backend.data.shanghai_locations import SHANGHAI_LOCATIONS, CITY_CENTER

    # cost_level 映射（处理不在约束范围内的值）
    _cost_map = {
        "免费": "免费", "免费-低": "低", "低": "低",
        "中等": "中等", "较高": "较高", "高": "高",
    }

    for loc in SHANGHAI_LOCATIONS:
        cost_raw = loc.get("cost_level", "中等")
        cost_level = _cost_map.get(cost_raw, "中等")

        cursor.execute("""
            INSERT INTO attractions
                (name, city, type, category, description, address,
                 lat, lng, tags, crowd_level, cost_level, duration_min,
                 best_time, suitable_for, personality_fit, tips, risks)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            loc["name"],
            "上海",
            loc["type"],
            loc["category"],
            loc["description"],
            loc.get("address", ""),
            loc["lat"],
            loc["lng"],
            json.dumps(loc.get("tags", []), ensure_ascii=False),
            loc.get("crowd_level", "medium"),
            cost_level,
            loc.get("duration_min", 60),
            loc.get("best_time", "全天"),
            json.dumps(loc.get("suitable_for", []), ensure_ascii=False),
            json.dumps(loc.get("travel_style_fit", {}), ensure_ascii=False),
            loc.get("tips", ""),
            loc.get("risks", ""),
        ))

    # --- 城市数据 ---
    cursor.execute("""
        INSERT INTO cities (name, center_lat, center_lng, zoom, transit_info, accommodation, description)
        VALUES (?,?,?,?,?,?,?)
    """, (
        CITY_CENTER["name"],
        CITY_CENTER["lat"],
        CITY_CENTER["lng"],
        CITY_CENTER["zoom"],
        json.dumps([
            {"mode": "地铁", "description": "上海地铁覆盖广泛，是最便捷的出行方式", "cost": "3-10元"},
            {"mode": "公交", "description": "公交线路密集，适合短途", "cost": "2元"},
            {"mode": "打车", "description": "高峰期可能堵车，建议地铁优先", "cost": "起步价16元"},
            {"mode": "步行", "description": "梧桐区景点集中，步行体验最佳", "cost": "免费"},
        ], ensure_ascii=False),
        json.dumps([
            {"level": "经济型", "price_range": "150-300元/晚", "description": "青年旅舍、快捷酒店，适合背包客"},
            {"level": "舒适型", "price_range": "300-600元/晚", "description": "商务酒店、精品民宿，性价比高"},
            {"level": "高档型", "price_range": "600-1500元/晚", "description": "四五星酒店、设计酒店，体验优先"},
            {"level": "奢华型", "price_range": "1500元+/晚", "description": "顶级酒店、历史建筑酒店"},
        ], ensure_ascii=False),
        "上海，一座融合了海派文化与现代都市魅力的国际大都市。梧桐区的法式浪漫、外滩的万国建筑、弄堂里的市井烟火，每一步都是故事。",
    ))

    conn.commit()


def _migrate_legacy_history(conn):
    """把旧版 users.travel_history（JSON 数组）搬进 trips 表，只执行一次（搬完清空原字段）。"""
    import uuid

    rows = conn.execute(
        "SELECT id, travel_history FROM users WHERE travel_history IS NOT NULL AND travel_history != '' AND travel_history != '[]'"
    ).fetchall()
    for row in rows:
        try:
            history = json.loads(row["travel_history"])
        except (TypeError, ValueError):
            continue
        for trip in history if isinstance(history, list) else []:
            if not isinstance(trip, dict) or not trip.get("itinerary"):
                continue
            digits = "".join(ch for ch in str(trip.get("budget", "")) if ch.isdigit())
            conn.execute(
                """INSERT INTO trips (id, user_id, title, city, days, budget, companions, mbti_type, itinerary)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex,
                    row["id"],
                    (trip.get("itinerary") or {}).get("summary", "")[:60],
                    trip.get("city", "上海"),
                    int(trip.get("days") or 1),
                    int(digits) if digits else 0,
                    trip.get("companions", ""),
                    trip.get("mbti_type"),
                    json.dumps(trip["itinerary"], ensure_ascii=False),
                ),
            )
        conn.execute("UPDATE users SET travel_history = NULL WHERE id = ?", (row["id"],))
    if rows:
        conn.commit()
        logger.info("已迁移 %d 位用户的旧版旅行历史到 trips 表", len(rows))


def list_cities():
    """返回有内置景点库的城市（含中心坐标），供前端城市选择与天气查询使用"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT c.name, c.center_lat, c.center_lng, COUNT(a.id) AS n "
            "FROM cities c LEFT JOIN attractions a ON a.city = c.name GROUP BY c.name ORDER BY n DESC"
        ).fetchall()
        return [{"name": r["name"], "lat": r["center_lat"], "lng": r["center_lng"], "places": r["n"]} for r in rows]
    finally:
        conn.close()


def _ensure_columns(conn):
    """给旧数据库补上新增的列（SQLite 没有 IF NOT EXISTS 的 ADD COLUMN）"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "is_guest" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_guest INTEGER NOT NULL DEFAULT 0")
        conn.commit()
