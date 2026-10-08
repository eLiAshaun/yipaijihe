"""
灵感素材：粘贴任意文字（小红书 / 抖音文案、攻略、地名清单）或文章链接（公众号、知乎、马蜂窝、携程…），提取可以去的地点。
文章链接用 Jina Reader 读正文（Exa 后备），请求由它们的服务器发出，本机不直接访问用户给的地址。
"""

from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request

from backend.database import get_db
from backend.routes.auth import login_required
from backend.services.inspiration import extract_places

inspiration_bp = Blueprint("inspiration", __name__)
MAX_URLS = 5


@inspiration_bp.post("/extract")
@login_required
def extract():
    from backend.routes.itinerary import _db_row_to_location

    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()
    urls = [u.strip() for u in (data.get("urls") or []) if isinstance(u, str) and u.strip()][:MAX_URLS] if isinstance(data.get("urls"), list) else []
    if not text and not urls:
        return jsonify({"error": "请粘贴一些文字或文章链接"}), 400
    if len(text) > 20000:
        return jsonify({"error": "文字太长了，请分几次粘贴（每次 2 万字以内）"}), 400
    city = str(data.get("city") or "上海")[:20]

    links = []
    if urls:
        from backend.services.reach import read_url

        with ThreadPoolExecutor(max_workers=MAX_URLS) as pool:
            pages = list(pool.map(lambda u: read_url(u, limit=8000, timeout=25), urls))
        parts = [text] if text else []
        for url, page in zip(urls, pages):
            links.append({"url": url, "ok": bool(page["text"]), "title": page["title"], "chars": len(page["text"]), "via": page["via"], "error": page["error"]})
            if page["text"]:
                parts.append(f"{page['title']}\n{page['text']}")
        text = "\n\n".join(parts)
    if not text:
        return jsonify({"places": [], "count": 0, "links": links})

    db = get_db()
    try:
        catalog = [_db_row_to_location(r) for r in db.execute("SELECT * FROM attractions WHERE city = ?", (city,)).fetchall()]
    finally:
        db.close()
    from backend.services.geo import fill_missing

    places = fill_missing(extract_places(text, city, catalog), city)
    return jsonify({"places": places, "count": len(places), "links": links})
