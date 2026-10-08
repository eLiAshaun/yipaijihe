"""
行程引擎（服务端）—— 没有大模型时由它排行程，有大模型时用它校验和修正大模型的输出。

针对同类产品常见的「看着好看、走不通」问题：
  · 来回折返      → 按地理位置聚类分天，天内按最短路线排序
  · 时间不合理    → 停留时长 + 通勤时间逐站推算，15 分钟取整
  · 夜景排在早上  → 读取景点的「建议时段」，排序和排时间都尊重它
  · 闭馆日去扑空  → 从景点贴士里解析「周一闭馆」等信息，有出发日期时自动换到开放的那天
  · 只逛不吃      → 跨过饭点却没有餐饮时，优先插入顺路的餐饮点，否则预留用餐时段
  · AI 编造地点   → 大模型输出里不在候选列表的地点会被丢弃

与前端 frontend/js/services/planner.js 使用相同的阈值与规则，两端结果一致。
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from itertools import permutations

# ------------------------------------------------------------------ 常量 ----
PACES = {
    "relaxed": {"label": "悠闲", "max_stops": 4, "start": 10 * 60},
    "balanced": {"label": "适中", "max_stops": 5, "start": 9 * 60 + 30},
    "packed": {"label": "紧凑", "max_stops": 7, "start": 9 * 60},
}
DEFAULT_DURATION = {"food": 75, "nature": 90, "culture": 100, "landmark": 60, "street": 90}
LUNCH = (11 * 60 + 30, 13 * 60 + 30)
DINNER = (17 * 60 + 30, 19 * 60 + 30)
WEEKDAYS = "一二三四五六日"

# 「建议时段」词 → 分钟区间
_WINDOW_WORDS = [
    ("清晨", (7 * 60, 10 * 60)),
    ("早上", (7 * 60, 10 * 60)),
    ("上午", (8 * 60 + 30, 12 * 60)),
    ("中午", (11 * 60, 14 * 60)),
    ("下午", (13 * 60, 17 * 60 + 30)),
    ("傍晚", (17 * 60, 19 * 60 + 30)),
    ("日落", (17 * 60, 19 * 60 + 30)),
    ("夜间", (19 * 60, 22 * 60)),
    ("夜晚", (19 * 60, 22 * 60)),
    ("晚上", (19 * 60, 22 * 60)),
]


# ------------------------------------------------------------------ 工具 ----
def to_min(t: str | None) -> int | None:
    m = re.fullmatch(r"\s*(\d{1,2})[:：](\d{2})\s*", t or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def fmt(minutes: float) -> str:
    m = max(0, min(int(round(minutes)), 24 * 60 - 1))
    return f"{m // 60:02d}:{m % 60:02d}"


def _round(x: float) -> int:
    """与 JS Math.round 一致的四舍五入（Python round 是银行家舍入）"""
    return int(math.floor(x + 0.5))


def snap15(minutes: float) -> int:
    return _round(minutes / 15.0) * 15


def has_coords(loc: dict | None) -> bool:
    try:
        return bool(loc) and float(loc.get("lat") or 0) != 0 and float(loc.get("lng") or 0) != 0
    except (TypeError, ValueError):
        return False


def haversine(a: dict, b: dict) -> float:
    r = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"])))
    s = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(s), math.sqrt(1 - s))


def estimate_travel(a: dict | None, b: dict | None) -> dict | None:
    """直线距离 ×1.3 ≈ 路网距离；≤1.3km 步行，≤9km 公共交通（含候车），更远打车"""
    if not has_coords(a) or not has_coords(b):
        return None
    meters = _round(haversine(a, b) * 1.3)
    km = meters / 1000
    if km <= 1.3:
        mode, minutes = "walk", km / 4.8 * 60
    elif km <= 9:
        mode, minutes = "transit", km / 24 * 60 + 12
    else:
        mode, minutes = "taxi", km / 30 * 60 + 6
    return {"meters": meters, "minutes": max(3, max(1, _round(minutes / 5.0) * 5)), "mode": mode}


def duration_of(loc: dict) -> int:
    try:
        d = int(loc.get("duration_min") or 0)
    except (TypeError, ValueError):
        d = 0
    return d if d >= 10 else DEFAULT_DURATION.get(loc.get("type"), 75)


def pace_of(profile: dict | None, explicit: str | None = None) -> str:
    """显式选择 > 人格「覆盖/深度」维度 > 适中"""
    if explicit in PACES:
        return explicit
    profile = profile or {}
    if profile.get("pace") in PACES:
        return profile["pace"]
    label = profile.get("cd_label") or ""
    code = (profile.get("mbti") or "    ")[3:4]
    if "覆盖" in label or code == "C":
        return "packed"
    if "深度" in label or code == "T":
        return "relaxed"
    return "balanced"


# -------------------------------------------------------------- 景点洞察 ----
def insights(loc: dict) -> dict:
    """从景点的「建议时段 / 贴士 / 风险」文字里解析结构化信息。只解析数据里写明的内容，不做臆测。"""
    text = " ".join(str(loc.get(k) or "") for k in ("tips", "risks", "best_time", "description"))
    closed = set()
    for m in re.finditer(r"周([一二三四五六日天])[^，。；,;]{0,6}?(闭馆|休息|休馆|不开放|关闭|闭园)", text):
        closed.add(WEEKDAYS.index(m.group(1).replace("天", "日")))
    booking = bool(re.search(r"(?<!无需)(?<!不需)(?<!不用)(预约|订位|提前订|需购票)", text))
    last = re.search(r"末班[^0-9]{0,4}(\d{1,2})[:：](\d{2})", text)
    best = str(loc.get("best_time") or "")
    spans = [w for word, w in _WINDOW_WORDS if word in best]
    window = (min(s for s, _ in spans), max(e for _, e in spans)) if spans and "全天" not in best else None
    return {
        "closed_weekdays": sorted(closed),
        "needs_booking": booking,
        "last_time": int(last.group(1)) * 60 + int(last.group(2)) if last else None,
        "window": window,
        "weekday_only": "工作日" in best,
    }


def _window_rank(loc: dict) -> int:
    """排序用：早时段景点靠前、傍晚 / 夜间景点靠后"""
    w = insights(loc)["window"]
    if not w:
        return 1
    start, _ = w
    return 0 if start < 11 * 60 else 3 if start >= 17 * 60 else 2 if start >= 13 * 60 else 1


# ------------------------------------------------------------------ 分天 ----
def _path_len(points: list[dict]) -> float:
    return sum(haversine(points[i - 1], points[i]) for i in range(1, len(points)))


def _chain(points: list[dict]) -> list[dict]:
    """最近邻串联：尝试每个起点，取总路程最短的一条"""
    best, best_len = points, math.inf
    for start in range(len(points)):
        left = points[:start] + points[start + 1:]
        path = [points[start]]
        while left:
            last = path[-1]
            i = min(range(len(left)), key=lambda k: haversine(last, left[k]))
            path.append(left.pop(i))
        length = _path_len(path)
        if length < best_len:
            best, best_len = path, length
    return best


def _order_day(stops: list[dict]) -> list[dict]:
    """天内排序：路程最短，同时尽量让「上午最佳」靠前、「傍晚 / 夜间最佳」靠后"""
    geo = [s for s in stops if has_coords(s)]
    rest = [s for s in stops if not has_coords(s)]
    if len(geo) <= 1:
        return geo + rest
    if len(geo) <= 7:
        rank_of = {id(s): _window_rank(s) for s in geo}

        def cost(order):
            ranks = [rank_of[id(s)] for s in order]
            inversions = sum(1 for i in range(len(ranks)) for j in range(i + 1, len(ranks)) if ranks[i] > ranks[j])
            return _path_len(list(order)) + inversions * 15000  # 时段倒挂（夜景排在白天景点前）代价很高
        best = min(permutations(geo), key=cost)
        return list(best) + rest
    return sorted(_chain(geo), key=_window_rank) + rest


def split_days(locs: list[dict], days: int) -> list[list[dict]]:
    """地理聚类分天：最短串联后按数量均分成连续的段，同一天的地点彼此相邻"""
    geo = [l for l in locs if has_coords(l)]
    no_geo = [l for l in locs if not has_coords(l)]
    chain = _chain(geo) if geo else []
    days = max(1, min(days, len(chain) or 1))
    base, extra = divmod(len(chain), days)
    out, i = [], 0
    for d in range(days):
        size = base + (1 if d < extra else 0)
        out.append(chain[i:i + size])
        i += size
    for j, l in enumerate(no_geo):  # 没有坐标的地点轮流放到各天末尾
        out[j % days].append(l)
    return out


def _centroid(stops: list[dict]) -> dict | None:
    geo = [x for x in stops if has_coords(x)]
    if not geo:
        return None
    return {"lat": sum(float(x["lat"]) for x in geo) / len(geo), "lng": sum(float(x["lng"]) for x in geo) / len(geo)}


def fix_closures(day_lists: list[list[dict]], start: date | None) -> list[str]:
    """
    有出发日期时：把落在闭馆日的景点和另一天里「能在这天开放、且地理上最合适」的景点对调，
    尽量不破坏按区域分天的结果。返回调整说明。
    """
    notes = []
    if not start:
        return notes
    wd_of = lambda d: (start + timedelta(days=d)).weekday()  # noqa: E731
    for d, stops in enumerate(day_lists):
        for s in list(stops):
            if wd_of(d) not in insights(s)["closed_weekdays"]:
                continue
            best = None
            for d2, other in enumerate(day_lists):
                if d2 == d or wd_of(d2) in insights(s)["closed_weekdays"]:
                    continue
                for o in other:
                    if wd_of(d) in insights(o)["closed_weekdays"]:
                        continue
                    here = _centroid([x for x in stops if x is not s])
                    there = _centroid([x for x in other if x is not o])
                    cost = (haversine(o, here) if here and has_coords(o) else 0) + (haversine(s, there) if there and has_coords(s) else 0)
                    if best is None or cost < best[0]:
                        best = (cost, d2, o)
            if best:
                _, d2, o = best
                stops[stops.index(s)] = o
                day_lists[d2][day_lists[d2].index(o)] = s
                notes.append(f"「{s['name']}」周{WEEKDAYS[wd_of(d)]}不开放，已和第 {d2 + 1} 天的「{o['name']}」对调")
            else:
                notes.append(f"「{s['name']}」在第 {d + 1} 天（周{WEEKDAYS[wd_of(d)]}）不开放，且没有可对调的日子，建议换掉")
    return notes


# ------------------------------------------------------------------ 排时间 ----
def _make_item(loc: dict, reason: str = "") -> dict:
    return {
        "time": "",
        "location_id": loc.get("id"),
        "activity": f"探索{loc['name']}",
        "notes": reason or loc.get("reason") or loc.get("tips") or "",
        "location": {k: loc.get(k) for k in ("name", "lat", "lng", "type", "category", "description", "address", "duration_min", "cost_level", "best_time", "tips", "risks", "tags") if loc.get(k) not in (None, "")},
    }


def meal_block(kind: str) -> dict:
    """预留的用餐时段：没有合适的顺路餐厅时使用，前端会给出「在高德搜附近餐厅」的入口"""
    label = "午餐" if kind == "lunch" else "晚餐"
    return {
        "time": "",
        "kind": "meal",
        "activity": label,
        "notes": "预留 1 小时用餐，在附近找家店",
        "location": {"name": f"{label} · 附近觅食", "type": "food", "duration_min": 60},
    }


def schedule(items: list[dict], start_min: int) -> list[dict]:
    """按顺序逐站推算时间：上一站结束 + 通勤；有建议时段的景点在合理等待范围内等到时段开始"""
    cursor = start_min
    prev_geo = None
    last = len(items) - 1
    lunch_used = dinner_used = False
    for i, it in enumerate(items):
        loc = it.get("location") or {}
        if i > 0:
            if it.get("kind") == "meal":
                travel = 0
            else:
                t = estimate_travel(prev_geo, loc)
                travel = t["minutes"] if t else 15
            cursor += travel
        locked = to_min(it.get("time")) if it.get("locked") else None
        if locked is not None:
            cursor = locked  # 用户锁定的时间（订好的餐厅 / 门票）永远不动，冲突交给预警提示
        else:
            win = None
            if it.get("kind") == "meal":
                win = DINNER if it.get("activity") == "晚餐" else LUNCH
            elif insights(loc)["window"]:
                win = insights(loc)["window"]
            elif loc.get("type") == "food":  # 没写建议时段的餐饮点落在饭点
                if not lunch_used and 9 * 60 <= cursor < LUNCH[1]:
                    win, lunch_used = LUNCH, True
                elif not dinner_used and 15 * 60 <= cursor < DINNER[1]:
                    win, dinner_used = DINNER, True
            if win and cursor < win[0]:
                # 剩下的都是傍晚 / 夜间景点：下午留给自由活动，到点再去（夜景排在中午毫无意义）
                rest = [x for x in items[i:] if x.get("kind") != "meal"]
                evening_tail = win[0] >= 17 * 60 and all((insights(x.get("location") or {})["window"] or (0, 0))[0] >= 17 * 60 for x in rest)
                # 傍晚 / 夜间景点、最后一站、吃饭可以多等一会儿（空档留给自由活动），其余最多等 1 小时
                patient = i == last or win[0] >= 17 * 60 or it.get("kind") == "meal" or loc.get("type") == "food"
                if evening_tail or win[0] - cursor <= (150 if patient else 60):
                    cursor = win[0]
            cursor = snap15(cursor)
        it["time"] = fmt(cursor)
        cursor += duration_of(loc)
        if has_coords(loc):
            prev_geo = loc
    return items


def _insert_meals(items: list[dict], start_min: int, catalog: list[dict], used: set) -> list[dict]:
    """跨过饭点却没有餐饮时，插入顺路餐饮点（1.5km 内），否则插入用餐时段"""
    schedule(items, start_min)
    for meal, (lo, hi) in (("lunch", LUNCH), ("dinner", DINNER)):
        times = [to_min(i["time"]) for i in items]
        ends = [t + duration_of(i.get("location") or {}) for t, i in zip(times, items)]
        if not items or ends[-1] < lo + 45 or times[0] > hi:
            continue
        if any((i.get("location") or {}).get("type") == "food" and lo - 30 <= t <= hi for t, i in zip(times, items)):
            continue
        pos = next((k for k, t in enumerate(times) if t >= lo), len(items))
        if pos == 0:
            continue
        anchor = next((items[k]["location"] for k in range(pos - 1, -1, -1) if has_coords(items[k].get("location"))), None)
        near = None
        if anchor:
            cands = [c for c in catalog if c.get("type") == "food" and c.get("name") not in used and has_coords(c) and haversine(anchor, c) <= 1500]
            near = min(cands, key=lambda c: haversine(anchor, c), default=None)
        if near:
            used.add(near["name"])
            items.insert(pos, _make_item(near, f"顺路的{'午' if meal == 'lunch' else '晚'}饭选择，距上一站约 {round(haversine(anchor, near) / 100) * 100} 米"))
        else:
            items.insert(pos, meal_block(meal))
        schedule(items, start_min)
    return items


# ------------------------------------------------------------------ 入口 ----
def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def build_itinerary(locations: list[dict], profile: dict | None, trip: dict, catalog: list[dict] | None = None) -> dict:
    """
    规则引擎生成完整行程。
    trip: {days, pace?, start_date?, city?}
    返回与大模型相同的结构：{summary, days[{day,title,items}], recommendations, tips}
    """
    catalog = catalog or []
    days = max(1, min(int(trip.get("days") or 2), 14))
    pace_key = pace_of(profile, trip.get("pace"))
    pace = PACES[pace_key]
    start = _parse_date(trip.get("start_date"))
    city = trip.get("city") or "上海"

    # 去重；超出节奏容量的地点进推荐池（保留用户给的先后顺序作为优先级）
    seen, uniq = set(), []
    for loc in locations:
        if loc.get("name") and loc["name"] not in seen:
            seen.add(loc["name"])
            uniq.append(loc)
    capacity = days * pace["max_stops"]
    chosen, overflow = uniq[:capacity], uniq[capacity:]

    day_lists = split_days(chosen, days)
    notes = fix_closures(day_lists, start)
    used = {l["name"] for l in chosen}

    out_days = []
    for d, stops in enumerate(day_lists):
        items = [_make_item(s) for s in _order_day(stops)]
        items = _insert_meals(items, pace["start"], catalog, used)
        title = f"Day {d + 1}"
        named = [i["location"]["name"] for i in items if i.get("kind") != "meal"][:2]
        if named:
            title += " · " + " → ".join(n.split("·")[0] for n in named)
        out_days.append({"day": d + 1, "title": title, "items": items})

    # 推荐池：容量外的地点 + 顺路但没被选的本地地点（餐饮优先）
    recs = [{"location_id": l.get("id"), "activity": f"探索{l['name']}", "reason": l.get("reason") or l.get("description") or "", "location": _make_item(l)["location"]} for l in overflow]
    anchors = [s for stops in day_lists for s in stops if has_coords(s)]
    if anchors:
        pool = [c for c in catalog if c.get("name") not in used and c.get("name") not in {r["location"]["name"] for r in recs} and has_coords(c)]
        pool.sort(key=lambda c: (c.get("type") != "food", min(haversine(c, a) for a in anchors)))
        for c in pool[: max(0, 8 - len(recs))]:
            near = min(anchors, key=lambda a: haversine(c, a))
            recs.append({"location_id": c.get("id"), "activity": f"探索{c['name']}", "reason": f"离「{near['name']}」约 {haversine(c, near) / 1000:.1f} km" + (f"，{c.get('tips')}" if c.get("tips") else ""), "location": _make_item(c)["location"]})

    meals = sum(1 for d in out_days for i in d["items"] if i.get("kind") == "meal" or (i.get("location") or {}).get("type") == "food")
    summary = f"按顺路程度把 {len(chosen)} 个地点分成 {len(out_days)} 天，{pace['label']}节奏（每天不超过 {pace['max_stops']} 个点）"
    summary += "，已按建议时段安排先后，并预留了用餐时间。" if meals else "，已按建议时段安排先后。"
    return {"summary": summary, "days": out_days, "recommendations": recs, "tips": notes + data_tips(chosen, start, len(out_days))}


def data_tips(locs: list[dict], start: date | None, days: int = 1) -> list[str]:
    """只从景点数据里能确认的信息生成提示，不写泛泛而谈的套话"""
    tips = []
    booking = [l["name"] for l in locs if insights(l)["needs_booking"]]
    if booking:
        tips.append(f"需要提前预约 / 订位：{'、'.join(booking)}")
    for l in locs:
        info = insights(l)
        if info["last_time"] is not None:
            tips.append(f"「{l['name']}」末班约 {fmt(info['last_time'])}，别排得太晚")
        if info["closed_weekdays"] and not start:
            tips.append(f"「{l['name']}」周{'、'.join(WEEKDAYS[w] for w in info['closed_weekdays'])}不开放，填写出发日期后会自动避开")
    crowded = [l["name"] for l in locs if "周末" in str(l.get("risks") or "") + str(l.get("tips") or "")]
    if start and crowded and any((start + timedelta(days=i)).weekday() >= 5 for i in range(days)):
        tips.append(f"行程包含周末，这些地方周末人多，尽量早到：{'、'.join(crowded[:4])}")
    return tips


def finalize_llm_itinerary(raw: dict, locations: list[dict], profile: dict | None, trip: dict, catalog: list[dict] | None = None) -> dict | None:
    """
    校验并修正大模型给出的行程：
      · 丢弃候选列表之外的 location_id（防止编造地点）与重复地点
      · 漏排的候选地点放进推荐池
      · 时间缺失或排不开的天按引擎重新排时间
    结构不合法时返回 None，由调用方改用规则引擎。
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("days"), list) or not raw["days"]:
        return None
    by_id = {l["id"]: l for l in locations if l.get("id")}
    pace = PACES[pace_of(profile, trip.get("pace"))]
    seen = set()
    days = []
    for d, day in enumerate(raw["days"]):
        if not isinstance(day, dict):
            continue
        items = []
        for it in day.get("items") or []:
            if not isinstance(it, dict):
                continue
            loc = by_id.get(it.get("location_id"))
            if not loc or loc["id"] in seen:
                continue
            seen.add(loc["id"])
            item = _make_item(loc, str(it.get("notes") or ""))
            item["activity"] = str(it.get("activity") or item["activity"])[:80]
            item["time"] = it.get("time") if to_min(it.get("time")) is not None else ""
            items.append(item)
        if not items:
            continue
        times = [to_min(i["time"]) for i in items]
        ok = all(t is not None for t in times)
        if ok:
            for k in range(1, len(items)):
                t = estimate_travel(items[k - 1]["location"], items[k]["location"])
                if times[k] < times[k - 1] + duration_of(items[k - 1]["location"]) + (t["minutes"] if t else 0) - 5:
                    ok = False
                    break
        if not ok:
            items.sort(key=lambda i: to_min(i["time"]) if to_min(i["time"]) is not None else 9999)
            schedule(items, pace["start"])
        days.append({"day": len(days) + 1, "title": str(day.get("title") or f"Day {len(days) + 1}")[:40], "items": items})
    if not days:
        return None

    recs = []
    for r in raw.get("recommendations") or []:
        loc = by_id.get((r or {}).get("location_id")) if isinstance(r, dict) else None
        if loc and loc["id"] not in seen:
            seen.add(loc["id"])
            recs.append({"location_id": loc["id"], "activity": str(r.get("activity") or f"探索{loc['name']}"), "reason": str(r.get("reason") or ""), "location": _make_item(loc)["location"]})
    for loc in locations:  # 大模型漏掉的候选地点
        if loc.get("id") and loc["id"] not in seen:
            seen.add(loc["id"])
            recs.append({"location_id": loc["id"], "activity": f"探索{loc['name']}", "reason": "你选过但这次没排进去的地点", "location": _make_item(loc)["location"]})

    tips = [str(t) for t in (raw.get("tips") or []) if isinstance(t, str)][:6]
    tips += [t for t in data_tips([by_id[i] for i in seen if i in by_id], _parse_date(trip.get("start_date")), len(days)) if t not in tips]
    return {"summary": str(raw.get("summary") or ""), "days": days, "recommendations": recs, "tips": tips}
