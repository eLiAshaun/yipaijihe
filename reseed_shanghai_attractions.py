"""
重新导入"上海"景点种子数据。

背景：backend/database.py 里的 _seed_data() 只在 attractions 表为空时执行一次，
所以单纯替换 backend/data/shanghai_locations.py（比如把景点数量从旧版扩充到新的 24 条）
并不会让数据库里的数据自动更新——数据库里仍然是上一次首次启动时写入的旧数据。

这个脚本会：
  1. 删除 attractions 表中 city = '上海' 的所有现有记录
  2. 按当前 backend/data/shanghai_locations.py 中的 SHANGHAI_LOCATIONS 重新插入

不会影响 users / 旅行历史 / cities 表 / 其他城市的数据
（CITY_CENTER 的中心坐标等信息没有变化，因此不需要重新写入 cities 表）。

用法（在项目根目录下执行）：
    python reseed_shanghai_attractions.py
"""

import json
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reseed")


def main():
    from backend.config import Config
    from backend.database import get_db
    from backend.data.shanghai_locations import SHANGHAI_LOCATIONS

    logger.info(f"数据库路径: {Config.DB_PATH}")
    logger.info(f"新版 shanghai_locations.py 中共有 {len(SHANGHAI_LOCATIONS)} 条上海景点")

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM attractions WHERE city = ?", ("上海",))
        old_count = cursor.fetchone()[0]
        logger.info(f"数据库中现有「上海」景点 {old_count} 条，准备清空并重新导入...")

        cursor.execute("DELETE FROM attractions WHERE city = ?", ("上海",))

        # cost_level 映射（处理不在数据库约束范围内的取值），与 _seed_data 保持一致
        _cost_map = {
            "免费": "免费", "免费-低": "低", "低": "低",
            "中等": "中等", "较高": "较高", "高": "高",
        }

        inserted = 0
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
                loc.get("description", ""),
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
            inserted += 1

        conn.commit()
        logger.info(f"✅ 重新导入完成：删除旧记录 {old_count} 条，插入新记录 {inserted} 条")

        cursor.execute("SELECT COUNT(*) FROM attractions WHERE city = ?", ("上海",))
        logger.info(f"校验：数据库中现有「上海」景点 {cursor.fetchone()[0]} 条")

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ 重新导入失败，已回滚: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
