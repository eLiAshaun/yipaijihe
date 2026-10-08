"""
本地旅行助手（没有大模型或大模型不可用时使用）

不是写死的客套话：每个回答都基于用户当前的行程、景点库和天气计算得出——
离「当前这一站」最近的吃饭 / 咖啡 / 拍照 / 室内去处、下一站怎么走、预算还剩多少。
"""

from __future__ import annotations

from datetime import date, datetime

from backend.services.planner import duration_of, estimate_travel, fmt, has_coords, haversine, insights, to_min

MODE_LABEL = {"walk": "步行", "transit": "地铁/公交", "taxi": "打车"}
COST = {"food": {"免费": 0, "低": 35, "中等": 80, "较高": 150, "高": 300}, "spot": {"免费": 0, "低": 20, "中等": 50, "较高": 100, "高": 200}}
INDOOR_HINT = ("书店", "美术馆", "博物馆", "画廊", "艺术", "展", "室内", "咖啡", "商场", "创意")
OUTDOOR_HINT = ("滨江", "公园", "散步", "citywalk", "步道", "夜景", "草坪", "野餐", "骑行")

INTENTS = [
    ("rain", ("下雨", "雨", "天气", "冷", "热", "晒")),
    ("coffee", ("咖啡", "累", "休息", "歇", "坐坐", "坐一会")),
    ("food", ("吃", "饿", "餐厅", "美食", "午饭", "晚饭", "早饭", "小吃", "夜宵")),
    ("photo", ("拍照", "出片", "机位", "好看")),
    ("crowd", ("人多", "人太多", "太挤", "排队", "拥挤", "人少", "小众")),
    ("budget", ("预算", "花多少", "多少钱", "省钱", "贵")),
    ("next", ("下一站", "接下来", "然后去", "下一个")),
    ("route", ("怎么走", "交通", "多远", "地铁", "打车", "路线", "顺路")),
    ("more", ("推荐", "还有什么", "好玩", "去哪", "加一个")),
]


def _stops(itinerary: dict | None) -> list[tuple[int, dict]]:
    out = []
    for d, day in enumerate((itinerary or {}).get("days") or []):
        for it in day.get("items") or []:
            if isinstance(it, dict):
                out.append((d, it))
    return out


def _loc(it: dict) -> dict:
    return it.get("location") or {}


def _focus(itinerary: dict | None, trip: dict | None, message: str, catalog: list[dict]) -> tuple[dict | None, str]:
    """确定「你现在在哪」：消息里提到的地点 > 行程当天的进行中 / 下一站 > 第一站"""
    stops = _stops(itinerary)
    for _, it in stops:
        name = _loc(it).get("name") or ""
        if name and any(part and part in message for part in name.split("·")):
            return _loc(it), f"「{name}」"
    for c in catalog:
        if any(part and len(part) >= 2 and part in message for part in c["name"].split("·")):
            return c, f"「{c['name']}」"
    start = (trip or {}).get("startDate") or (trip or {}).get("start_date")
    try:
        day_idx = (date.today() - date.fromisoformat(start)).days if start else -1
    except ValueError:
        day_idx = -1
    if stops and 0 <= day_idx < len((itinerary or {}).get("days") or []):
        now = datetime.now().hour * 60 + datetime.now().minute
        today = [it for d, it in stops if d == day_idx and has_coords(_loc(it))]
        current = [it for it in today if (to_min(it.get("time")) or 0) <= now]
        if current:
            return _loc(current[-1]), f"当前这站「{_loc(current[-1]).get('name')}」"
        if today:
            return _loc(today[0]), f"今天第一站「{_loc(today[0]).get('name')}」"
    geo = [it for _, it in stops if has_coords(_loc(it))]
    if geo:
        return _loc(geo[0]), f"行程第一站「{_loc(geo[0]).get('name')}」"
    return None, ""


def _nearest(catalog: list[dict], focus: dict | None, pred, exclude: set, n: int = 3) -> list[tuple[dict, float]]:
    cands = [c for c in catalog if pred(c) and c.get("name") not in exclude and has_coords(c)]
    if focus and has_coords(focus):
        ranked = sorted(((c, haversine(focus, c)) for c in cands), key=lambda x: x[1])
    else:
        ranked = [(c, 0.0) for c in cands]
    return ranked[:n]


def _dist(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{int(m // 50 * 50) or 50} 米"


def _line(c: dict, m: float) -> str:
    bits = [f"**{c['name']}**"]
    if m:
        bits.append(_dist(m))
    if c.get("best_time") and c["best_time"] != "全天":
        bits.append(f"建议{c['best_time']}")
    tip = c.get("tips") or c.get("description") or ""
    return "- " + " · ".join(bits) + (f"：{tip}" if tip else "")


def _text_of(c: dict) -> str:
    return " ".join([c.get("name", ""), c.get("category", ""), " ".join(c.get("tags") or []), c.get("description", "")])


def intent_of(message: str) -> str:
    """识别问题类型；没有命中任何关键词时为 summary（概览）"""
    return next((name for name, words in INTENTS if any(w in message for w in words)), "summary")


def reply(message: str, context: dict, catalog: list[dict]) -> tuple[str, list[str]]:
    message = (message or "").strip()
    context = context or {}
    itinerary = context.get("itinerary") or {}
    trip = context.get("trip") or {}
    weather = context.get("weather") or []
    in_trip = {(_loc(it).get("name") or "") for _, it in _stops(itinerary)}
    focus, where = _focus(itinerary, trip, message, catalog)
    near = f"离{where}" if where else "在景点库里"
    intent = intent_of(message)

    if intent == "rain":
        rainy = [i for i, w in enumerate(weather) if isinstance(w, dict) and (w.get("rain_prob") or 0) >= 50]
        indoor = _nearest(catalog, focus, lambda c: any(h in _text_of(c) for h in INDOOR_HINT), in_trip)
        outdoor = [(_loc(it).get("name"), d) for d, it in _stops(itinerary) if any(h in _text_of(_loc(it)) for h in OUTDOOR_HINT)]
        lines = []
        if rainy:
            lines.append(f"天气预报显示 **第 {'、'.join(str(i + 1) for i in rainy)} 天** 降水概率较高。")
        if outdoor:
            lines.append("这些行程偏户外，下雨时可以换掉或挪到别的天：")
            lines += [f"- 第 {d + 1} 天 · {n}" for n, d in outdoor[:4]]
        if indoor:
            lines.append(f"{near}最近的室内去处：")
            lines += [_line(c, m) for c, m in indoor]
        if not lines:
            lines.append("目前行程里没有明显的户外点，下雨影响不大。记得带伞，地铁出行最稳。")
        return "\n".join(lines), ["把户外点挪到晴天", "附近有什么好吃的", "下一站怎么走"]

    if intent in ("food", "coffee"):
        want_coffee = intent == "coffee"
        pred = (lambda c: "咖啡" in _text_of(c)) if want_coffee else (lambda c: c.get("type") == "food")
        picks = _nearest(catalog, focus, pred, set())
        if not picks and want_coffee:
            picks = _nearest(catalog, focus, lambda c: c.get("type") == "food", set())
        head = f"{near}最近的{'咖啡 / 歇脚' if want_coffee else '吃饭'}去处："
        lines = [head] + [_line(c, m) for c, m in picks] if picks else ["景点库里这一带暂时没有收录餐饮点。"]
        if focus and has_coords(focus):
            lines.append(f"想看更多店：在行程里点这一站的「附近餐厅」，会打开高德搜索 {focus.get('name')} 周边。")
        return "\n".join(lines), ["附近拍照点", "下一站怎么走", "预算还剩多少"]

    if intent == "photo":
        picks = _nearest(catalog, focus, lambda c: "拍照" in (c.get("tags") or []) or "摄影" in (c.get("tags") or []), set())
        lines = [f"{near}最近的出片点："] + [_line(c, m) for c, m in picks]
        return "\n".join(lines), ["人少一点的地方", "附近有咖啡吗", "下一站怎么走"]

    if intent == "crowd":
        picks = _nearest(catalog, focus, lambda c: "小众" in (c.get("tags") or []) or c.get("crowd_level") == "low", in_trip)
        crowded = [_loc(it).get("name") for _, it in _stops(itinerary) if "周末" in str(_loc(it).get("risks") or "") + str(_loc(it).get("tips") or "") or "人流" in str(_loc(it).get("risks") or "")]
        lines = []
        if crowded:
            lines.append(f"行程里容易人多的：{'、'.join(crowded[:4])}，尽量早上去或避开周末。")
        lines.append(f"{near}人少一些的地方：")
        lines += [_line(c, m) for c, m in picks]
        return "\n".join(lines), ["附近拍照点", "附近有什么好吃的"]

    if intent == "budget":
        total = 0
        for _, it in _stops(itinerary):
            loc = _loc(it)
            kind = "food" if loc.get("type") == "food" else "spot"
            total += COST[kind].get(loc.get("cost_level"), 80 if kind == "food" else 30)
        budget = int(trip.get("budget") or 0)
        if not _stops(itinerary):
            return "还没有行程，生成路线后我可以帮你算预算。", ["怎么规划比较好"]
        lines = [f"按景点和餐饮的消费档位估算，人均约 **¥{total}**（不含住宿与市内交通，交通在「预算」页单独算）。"]
        if budget:
            lines.append(f"你的预算是 ¥{budget}，" + (f"还剩约 ¥{budget - total}。" if budget >= total else f"超出约 ¥{total - budget}。"))
        pricey = [(_loc(it).get("name"), _loc(it).get("cost_level")) for _, it in _stops(itinerary) if _loc(it).get("cost_level") in ("较高", "高")]
        if pricey:
            lines.append("花费较高的地点：" + "、".join(f"{n}（{c}）" for n, c in pricey) + "，想省钱可以先从这里调整。")
        return "\n".join(lines), ["有没有免费的地方", "附近有什么好吃的"]

    if intent in ("next", "route"):
        stops = _stops(itinerary)
        if not stops:
            return "还没有行程。生成路线后我可以告诉你每两站之间怎么走、要多久。", ["怎么规划比较好"]
        names = [_loc(it).get("name") for _, it in stops]
        idx = next((i for i, (_, it) in enumerate(stops) if _loc(it) is focus), 0)
        if idx + 1 >= len(stops):
            return f"{_loc(stops[idx][1]).get('name')} 已经是最后一站了，可以慢慢逛。", ["附近有什么好吃的", "附近拍照点"]
        cur, nxt = stops[idx][1], stops[idx + 1][1]
        t = estimate_travel(_loc(cur), _loc(nxt))
        start = to_min(cur.get("time"))
        lines = [f"下一站是 **{_loc(nxt).get('name')}**（计划 {nxt.get('time') or '时间待定'}）。"]
        if t:
            lines.append(f"从 {_loc(cur).get('name')} 过去约 {_dist(t['meters'])}，建议{MODE_LABEL[t['mode']]}，大约 {t['minutes']} 分钟。")
            if start is not None:
                leave = start + duration_of(_loc(cur))
                lines.append(f"按停留时长，{fmt(leave)} 出发，大约 {fmt(leave + t['minutes'])} 到。")
        info = insights(_loc(nxt))
        if info["needs_booking"]:
            lines.append("⚠️ 这一站需要提前预约 / 订位。")
        if info["last_time"] is not None:
            lines.append(f"⚠️ 末班约 {fmt(info['last_time'])}。")
        return "\n".join(lines), ["附近有什么好吃的", "下雨了怎么办"]

    if intent == "more":
        picks = _nearest(catalog, focus, lambda c: True, in_trip)
        lines = [f"{near}还没排进行程、离得近的地方："] + [_line(c, m) for c, m in picks]
        lines.append("在行程页的「更多推荐景点」里点 +D1 / +D2 就能加进去。")
        return "\n".join(lines), ["附近有什么好吃的", "附近拍照点"]

    # 默认：概览当前行程
    stops = _stops(itinerary)
    if not stops:
        return ("我可以根据你的行程回答：附近吃什么、下一站怎么走、下雨换哪里、预算够不够。"
                "先在「地点筛选」里选好地点生成路线，我会更有用。"), [f"{(context.get('trip') or {}).get('city') or '这里'}有什么好吃的", "适合拍照的地方"]
    days = len(itinerary.get("days") or [])
    lines = [f"你的行程共 {days} 天、{len(stops)} 站。可以问我："]
    lines += ["- **下一站怎么走**", "- **附近有什么好吃的 / 咖啡**", "- **下雨了怎么办**", "- **预算还剩多少**"]
    return "\n".join(lines), ["下一站怎么走", "附近有什么好吃的", "下雨了怎么办"]
