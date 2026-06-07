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

    # 索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attractions_city ON attractions(city)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attractions_type ON attractions(type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_session ON users(session_token)")

    conn.commit()

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
