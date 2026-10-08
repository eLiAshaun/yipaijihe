"""本轮新增能力：开箱即跑、行程引擎、灵感提取、本地助手、游客模式、直选人格、多城市"""

import socket
from datetime import date, timedelta

import pytest

from backend.data.shanghai_locations import SHANGHAI_LOCATIONS
from backend.services.planner import build_itinerary, finalize_llm_itinerary, insights, to_min


def _catalog():
    cost = {"免费-低": "低"}
    return [{**l, "cost_level": cost.get(l.get("cost_level"), l.get("cost_level"))} for l in SHANGHAI_LOCATIONS]


def _pick(*names):
    cat = _catalog()
    return [l for l in cat if l["name"] in names]


def _next_weekday(wd):
    d = date.today() + timedelta(days=1)
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d


# ------------------------------------------------------------------ 配置 ----
def test_placeholder_secrets_are_treated_as_unset(monkeypatch):
    from backend.config import _secret

    for v in ("your-api-key-here", "your-mimo-api-key-here", "  ", "xxx"):
        monkeypatch.setenv("SOME_KEY", v)
        assert _secret("SOME_KEY") == ""
    monkeypatch.setenv("SOME_KEY", "sk-real-123")
    assert _secret("SOME_KEY") == "sk-real-123"


def test_free_port_skips_busy_port():
    from app import _free_port

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        assert _free_port("127.0.0.1", busy) != busy


def test_config_exposes_capabilities_and_cities(client):
    cfg = client.get("/api/config").get_json()
    assert cfg["web_search"] is False and cfg["asr"] is False
    assert cfg["cities"][0]["name"] == "上海" and cfg["cities"][0]["places"] >= 20


# ------------------------------------------------------------------ 洞察 ----
def test_insights_parse_closures_booking_last_ferry_and_windows():
    by = {l["name"]: insights(l) for l in _catalog()}
    assert by["M50创意园"]["closed_weekdays"] == [0]
    assert by["安福路"]["closed_weekdays"] == [1]
    assert by["哥伦比亚公园"]["needs_booking"] and by["新天地"]["needs_booking"]
    assert by["东昌路渡轮码头"]["last_time"] == 21 * 60
    assert by["外滩夜景"]["window"][0] >= 17 * 60
    assert by["武康路·武康大楼"]["window"] is None
    assert insights({"tips": "无需预约，随到随进"})["needs_booking"] is False


# ------------------------------------------------------------------ 引擎 ----
def test_engine_groups_by_area_orders_by_best_time_and_adds_meals():
    sel = _pick("外滩夜景", "豫园·城隍庙", "武康路·武康大楼", "安福路", "田子坊", "思南公馆·思南书局", "1933老场坊", "多伦路文化名人街")
    plan = build_itinerary(sel, {}, {"days": 2, "pace": "balanced"}, _catalog())
    assert len(plan["days"]) == 2
    for day in plan["days"]:
        times = [to_min(i["time"]) for i in day["items"]]
        assert times == sorted(times) and times[0] == 9 * 60 + 30
        assert len({t for t in times}) == len(times)
    names = [[i["location"]["name"] for i in d["items"]] for d in plan["days"]]
    # 夜景是当天最后一个景点（之后只可能是晚餐），且不早于 17:00
    for d in plan["days"]:
        stops = [i for i in d["items"] if i.get("kind") != "meal"]
        for idx, i in enumerate(stops):
            if i["location"]["name"] == "外滩夜景":
                assert idx == len(stops) - 1 and to_min(i["time"]) >= 17 * 60
    # 武康路与安福路相距 200 米，必须在同一天
    assert any("武康路·武康大楼" in n and "安福路" in n for n in names)
    # 跨过饭点的天有用餐安排
    assert any(i.get("kind") == "meal" or i["location"].get("type") == "food" for d in plan["days"] for i in d["items"])


def test_engine_moves_places_off_their_closed_day():
    monday = _next_weekday(0)
    sel = _pick("M50创意园", "1933老场坊", "多伦路文化名人街", "武康路·武康大楼", "安福路", "田子坊")
    for start in (monday, monday + timedelta(days=1)):  # 周一出发 / 周二出发
        plan = build_itinerary(sel, {}, {"days": 2, "start_date": start.isoformat()}, _catalog())
        for d, day in enumerate(plan["days"]):
            wd = (start + timedelta(days=d)).weekday()
            for item in day["items"]:
                assert wd not in insights(item["location"])["closed_weekdays"], (start, d, item["location"]["name"])
    # 只有一天可选时无法避开，会明确提示
    plan = build_itinerary(_pick("M50创意园"), {}, {"days": 1, "start_date": monday.isoformat()}, _catalog())
    assert any("不开放" in t for t in plan["tips"])


def test_engine_respects_pace_capacity_and_keeps_overflow_as_recommendations():
    sel = _catalog()[:12]
    plan = build_itinerary(sel, {"cd_label": "深度停留型"}, {"days": 2}, _catalog())
    real = [i for d in plan["days"] for i in d["items"] if i.get("kind") != "meal" and i.get("location_id") in {l["id"] for l in sel}]
    assert len(real) <= 8  # 悠闲：每天最多 4 个
    rec_names = {r["location"]["name"] for r in plan["recommendations"]}
    assert {l["name"] for l in sel[8:]} <= rec_names


def test_locked_time_is_never_moved():
    from backend.services.planner import schedule

    items = [{"location": _pick("豫园·城隍庙")[0]}, {"location": _pick("新天地")[0], "time": "20:00", "locked": True}]
    schedule(items, 9 * 60)
    assert items[1]["time"] == "20:00"


def test_finalize_llm_drops_invented_places_and_fixes_impossible_times():
    sel = _pick("武康路·武康大楼", "外滩夜景", "豫园·城隍庙")
    by = {l["name"]: l["id"] for l in sel}
    raw = {
        "summary": "x",
        "days": [{"title": "Day 1", "items": [
            {"time": "09:00", "location_id": by["武康路·武康大楼"]},
            {"time": "09:10", "location_id": by["外滩夜景"]},  # 9 公里外，10 分钟到不了
            {"time": "10:00", "location_id": "loc_999"},        # 编造的地点
        ]}],
        "recommendations": [],
    }
    out = finalize_llm_itinerary(raw, sel, {}, {"days": 1}, _catalog())
    items = out["days"][0]["items"]
    assert [i["location"]["name"] for i in items] == ["武康路·武康大楼", "外滩夜景"]
    assert to_min(items[1]["time"]) >= to_min(items[0]["time"]) + 30 + 20
    assert "豫园·城隍庙" in {r["location"]["name"] for r in out["recommendations"]}
    assert finalize_llm_itinerary({"days": "nope"}, sel, {}, {}, []) is None


def test_generate_endpoint_uses_local_engine_and_keeps_unknown_places_without_fake_coords(client):
    cat = client.get("/api/locations/list?city=上海").get_json()["locations"]
    preview = [{**cat[0]}, {**cat[4]}, {"name": "朋友推荐的面馆", "type": "food"}]
    res = client.post("/api/itinerary/generate", json={"destination": "上海", "days": 1, "preview_locations": preview}).get_json()
    assert res["engine"] == "local"
    items = res["itinerary"]["days"][0]["items"]
    noodle = next(i for i in items if i["location"]["name"] == "朋友推荐的面馆")
    assert noodle["location"].get("lat") is None  # 不再编造人民广场坐标
    # 景点库地点带回了完整数据（建议时段 / 贴士）
    assert any(i["location"].get("tips") for i in items)


# ------------------------------------------------------------------ 推荐 ----
def test_default_recommend_without_web_search_uses_whole_catalog_ranked_by_persona(client):
    res = client.post("/api/locations/default-recommend", json={"city": "上海", "days": 2, "profile": {"mbti": "DRPT", "di_label": "记录表达型"}}).get_json()
    assert res["source"] == "local" and len(res["attractions"]) >= 20
    scores = [a["fit_score"] for a in res["attractions"]]
    assert scores == sorted(scores, reverse=True)
    assert any(a["selected"] for a in res["attractions"]) and not all(a["selected"] for a in res["attractions"])

    other = client.post("/api/locations/default-recommend", json={"city": "杭州"}).get_json()
    assert other["attractions"] == [] and "DEEPSEEK_API_KEY" in other["message"]


# ------------------------------------------------------------------ 灵感 ----
def test_inspiration_extracts_places_with_their_sentence(client, auth):
    text = "上海citywalk｜早上先去武康大楼拍照，人少！然后安福路喝咖啡。晚上外滩看夜景，最后坐东昌路渡轮。还有外白渡桥。"
    assert client.post("/api/inspiration/extract", json={"text": text}).status_code == 401
    res = client.post("/api/inspiration/extract", json={"text": text}, headers={"Authorization": auth["Authorization"]}).get_json()
    names = [p["name"] for p in res["places"]]
    assert names[:5] == ["武康路·武康大楼", "安福路", "外滩夜景", "东昌路渡轮码头", "外白渡桥"]
    assert all(p.get("lat") for p in res["places"])
    assert "喝咖啡" in res["places"][1]["reason"]


def test_video_analyze_without_asr_reads_share_text_and_never_returns_demo_data(client, auth, monkeypatch):
    from backend.services import video_processor

    def offline(self, url, timeout=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(video_processor.VideoProcessor, "_load_share_item", offline)
    hdr = {"Authorization": auth["Authorization"]}
    share = "5.8 复制打开抖音，看看【小王的作品】上海一日游 武康路+外滩夜景 https://v.douyin.com/abc123/"
    res = client.post("/api/video/analyze", json={"urls": ["https://v.douyin.com/abc123/"], "text": share}, headers=hdr).get_json()
    assert [l["name"] for l in res["locations"]] == ["武康路·武康大楼", "外滩夜景"]
    assert res["asr"] is False

    empty = client.post("/api/video/analyze", json={"urls": ["https://v.douyin.com/zzz999/"], "text": "https://v.douyin.com/zzz999/"}, headers=hdr).get_json()
    assert empty["locations"] == [] and empty["errors"] and "fallback" not in empty


# ------------------------------------------------------------------ 助手 ----
def test_local_assistant_answers_from_itinerary_and_catalog(client):
    sel = _pick("田子坊", "武康路·武康大楼", "外滩夜景")
    plan = build_itinerary(sel, {}, {"days": 1}, _catalog())
    ctx = {"itinerary": plan, "trip": {"city": "上海", "budget": 100}, "weather": [{"rain_prob": 90}]}
    food = client.post("/api/chat/message", json={"message": "附近有什么好吃的", "context": ctx}).get_json()
    assert food["engine"] == "local" and "永康路" in food["reply"]
    rain = client.post("/api/chat/message", json={"message": "下雨了怎么办", "context": ctx}).get_json()["reply"]
    assert "第 1 天" in rain and "室内" in rain
    budget = client.post("/api/chat/message", json={"message": "预算还剩多少", "context": ctx}).get_json()["reply"]
    assert "¥100" in budget
    nxt = client.post("/api/chat/message", json={"message": "下一站怎么走", "context": ctx}).get_json()["reply"]
    assert "下一站是" in nxt and "分钟" in nxt


# ------------------------------------------------------------------ 账号 ----
def test_guest_can_start_immediately_and_claim_account_later(client):
    res = client.post("/api/auth/guest")
    assert res.status_code == 201
    body = res.get_json()
    hdr = {"Authorization": f"Bearer {body['token']}"}
    prof = client.get("/api/auth/profile", headers=hdr).get_json()["profile"]
    assert prof["is_guest"] is True and prof["username"].startswith("旅客")

    client.post("/api/trips", json={"itinerary": {"days": [{"items": []}]}}, headers=hdr)
    assert client.put("/api/auth/account", json={"username": "ab", "password": "secret123"}, headers=hdr).status_code == 400
    ok = client.put("/api/auth/account", json={"username": "转正用户", "password": "secret123"}, headers=hdr)
    assert ok.status_code == 200
    again = client.post("/api/auth/login", json={"username": "转正用户", "password": "secret123"}).get_json()
    hdr2 = {"Authorization": f"Bearer {again['token']}"}
    assert client.get("/api/auth/profile", headers=hdr2).get_json()["profile"]["is_guest"] is False
    assert len(client.get("/api/trips", headers=hdr2).get_json()["trips"]) == 1  # 游客期间的行程还在
    assert client.put("/api/auth/account", json={"username": "x12", "password": "secret123"}, headers=hdr2).status_code == 400


# ------------------------------------------------------------------ 人格 ----
def test_persona_can_be_picked_directly(client):
    personas = client.get("/api/mbti/personas").get_json()["personas"]
    assert len(personas) == 6 and {p["code"] for p in personas} >= {"DRPT", "ILSC"}
    res = client.post("/api/mbti/pick", json={"code": "ILSC"}).get_json()
    assert res["mbti"] == "ILSC" and res["personality"]["name"] and len(res["dimensions"]) == 4
    assert client.post("/api/mbti/pick", json={"code": "ZZZZ"}).status_code == 400


# ------------------------------------------------------------------ 天气 ----
def test_weather_for_city_without_catalog_uses_geocoding(client, monkeypatch):
    import backend.routes.trips as mod

    d0 = date.today() + timedelta(days=1)

    class R:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    def fake_get(url, params=None, timeout=None):
        if "geocoding" in url:
            assert params["name"] == "杭州"
            return R({"results": [{"latitude": 30.27, "longitude": 120.15}]})
        assert params["latitude"] == 30.27
        return R({"daily": {"time": [d0.isoformat()], "weathercode": [3], "temperature_2m_max": [25], "temperature_2m_min": [18], "precipitation_probability_max": [20]}})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    out = client.get(f"/api/weather?city=杭州&start={d0.isoformat()}&days=1").get_json()
    assert out["available"] and out["days"][0]["code"] == 3


@pytest.mark.parametrize("path", ["/api/locations/videos"])
def test_fake_video_feed_is_gone(client, path):
    assert "videos" not in (client.get(path).get_json() or {})


def test_evening_spots_wait_for_dusk_on_short_days():
    from backend.services.planner import schedule, _make_item

    items = [_make_item(l) for l in _pick("豫园·城隍庙", "外滩夜景", "东昌路渡轮码头")]
    items.sort(key=lambda i: ["豫园·城隍庙", "外滩夜景", "东昌路渡轮码头"].index(i["location"]["name"]))
    schedule(items, 10 * 60)
    assert items[1]["time"] == "17:00" and to_min(items[2]["time"]) >= 18 * 60
