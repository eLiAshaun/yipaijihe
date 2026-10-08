"""行程仓储：trips 表的读写，路由层只管 HTTP。"""

import json
import secrets
import uuid

from backend.database import get_db

MAX_ITINERARY_BYTES = 512 * 1024  # 单条行程上限，防止被塞入超大 JSON


class TripError(ValueError):
    """业务校验失败（映射为 400）"""


def _clean_int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _validate_itinerary(itinerary):
    if not isinstance(itinerary, dict) or not isinstance(itinerary.get("days"), list):
        raise TripError("行程格式不正确")
    raw = json.dumps(itinerary, ensure_ascii=False)
    if len(raw.encode("utf-8")) > MAX_ITINERARY_BYTES:
        raise TripError("行程内容过大")
    return raw


def _date(value):
    value = (value or "").strip()
    if not value:
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise TripError("日期格式应为 YYYY-MM-DD")
    return value


def row_to_trip(row, full=True):
    trip = {
        "id": row["id"],
        "title": row["title"],
        "city": row["city"],
        "days": row["days"],
        "budget": row["budget"],
        "companions": row["companions"],
        "start_date": row["start_date"],
        "mbti_type": row["mbti_type"],
        "shared": bool(row["share_token"]),
        "share_token": row["share_token"],
        "date": (row["created_at"] or "")[:10],
        "updated_at": row["updated_at"],
        "meta": json.loads(row["meta"]) if row["meta"] else {},
    }
    itinerary = json.loads(row["itinerary"])
    trip["stops"] = sum(len(d.get("items") or []) for d in itinerary.get("days", []))
    if full:
        trip["itinerary"] = itinerary
    return trip


def list_trips(user_id, full=False):
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM trips WHERE user_id = ? ORDER BY updated_at DESC, rowid DESC", (user_id,)).fetchall()
        return [row_to_trip(r, full=full) for r in rows]
    finally:
        db.close()


def get_trip(user_id, trip_id):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)).fetchone()
        return row_to_trip(row) if row else None
    finally:
        db.close()


def create_trip(user, data):
    raw = _validate_itinerary(data.get("itinerary"))
    trip_id = uuid.uuid4().hex[:12]
    itinerary = data["itinerary"]
    db = get_db()
    try:
        db.execute(
            """INSERT INTO trips (id, user_id, title, city, days, budget, companions, start_date, mbti_type, itinerary, meta)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trip_id,
                user["id"],
                (data.get("title") or itinerary.get("summary") or "")[:60],
                (data.get("city") or "上海")[:50],
                _clean_int(data.get("days") or len(itinerary["days"]), 1, 1, 60),
                _clean_int(data.get("budget_amount", data.get("budget")), 0, 0, 1_000_000),
                (data.get("companions") or "")[:40],
                _date(data.get("start_date")),
                user.get("mbti_type"),
                raw,
                json.dumps(data.get("meta") or {}, ensure_ascii=False),
            ),
        )
        db.commit()
    finally:
        db.close()
    return get_trip(user["id"], trip_id)


_UPDATABLE = {"title", "city", "days", "budget", "companions", "start_date", "itinerary", "meta"}


def update_trip(user_id, trip_id, data):
    if not get_trip(user_id, trip_id):
        return None
    sets, params = [], []
    if "itinerary" in data:
        sets.append("itinerary = ?")
        params.append(_validate_itinerary(data["itinerary"]))
    if "title" in data:
        sets.append("title = ?")
        params.append((data["title"] or "")[:60])
    if "city" in data:
        sets.append("city = ?")
        params.append((data["city"] or "上海")[:50])
    if "days" in data:
        sets.append("days = ?")
        params.append(_clean_int(data["days"], 1, 1, 60))
    if "budget" in data or "budget_amount" in data:
        sets.append("budget = ?")
        params.append(_clean_int(data.get("budget_amount", data.get("budget")), 0, 0, 1_000_000))
    if "companions" in data:
        sets.append("companions = ?")
        params.append((data["companions"] or "")[:40])
    if "start_date" in data:
        sets.append("start_date = ?")
        params.append(_date(data["start_date"]))
    if "meta" in data:
        sets.append("meta = ?")
        params.append(json.dumps(data["meta"] or {}, ensure_ascii=False))
    if sets:
        sets.append("updated_at = CURRENT_TIMESTAMP")
        db = get_db()
        try:
            db.execute(f"UPDATE trips SET {', '.join(sets)} WHERE id = ? AND user_id = ?", (*params, trip_id, user_id))
            db.commit()
        finally:
            db.close()
    return get_trip(user_id, trip_id)


def delete_trip(user_id, trip_id):
    db = get_db()
    try:
        cur = db.execute("DELETE FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id))
        db.commit()
        return cur.rowcount > 0
    finally:
        db.close()


def set_share(user_id, trip_id, enabled=True):
    """开启 / 关闭分享。开启时生成不可猜测的 token（幂等）。"""
    trip = get_trip(user_id, trip_id)
    if not trip:
        return None
    token = (trip["share_token"] or secrets.token_urlsafe(9)) if enabled else None
    db = get_db()
    try:
        db.execute("UPDATE trips SET share_token = ? WHERE id = ? AND user_id = ?", (token, trip_id, user_id))
        db.commit()
    finally:
        db.close()
    return token


def get_shared(token):
    """公开读取：只暴露行程本身与作者昵称，不含 user_id / 其他行程。"""
    if not token or len(token) > 40:
        return None
    db = get_db()
    try:
        row = db.execute(
            """SELECT t.*, u.username AS author FROM trips t JOIN users u ON u.id = t.user_id
               WHERE t.share_token = ?""",
            (token,),
        ).fetchone()
        if not row:
            return None
        trip = row_to_trip(row)
        trip.pop("share_token", None)
        trip["author"] = row["author"]
        return trip
    finally:
        db.close()
