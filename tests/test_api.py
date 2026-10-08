import hashlib
import sqlite3

from backend.config import Config


def test_health_and_public_config(client):
    assert client.get("/api/health").get_json()["status"] == "ok"
    cfg = client.get("/api/config").get_json()
    assert "key" in cfg["amap"] and "securityJsCode" in cfg["amap"]


def test_spa_shell_and_static_assets(client):
    res = client.get("/")
    assert res.status_code == 200 and b"<div id=\"app\"" in res.data
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in res.headers
    assert client.get("/js/main.js").status_code == 200
    assert client.get("/css/tokens.css").status_code == 200


def test_unknown_api_returns_json_404(client):
    res = client.get("/api/nope")
    assert res.status_code == 404 and res.is_json


def test_mbti_questions_and_calculate(client):
    qs = client.get("/api/mbti/questions").get_json()["questions"]
    assert {q["type"] for q in qs} == {"single", "ranking", "slider"}

    answers = {}
    for q in qs:
        if q["type"] == "single":
            answers[q["id"]] = q["options"][0]["id"]
        elif q["type"] == "ranking":
            answers[q["id"]] = [o["id"] for o in q["options"]]
        else:
            answers[q["id"]] = 50
    data = client.post("/api/mbti/calculate", json={"answers": answers}).get_json()
    assert len(data["mbti"]) == 4
    assert data["personality"]["image"].endswith(".png")
    assert len(data["dimensions"]) == 4


def test_locations_list(client):
    data = client.get("/api/locations/list?city=上海").get_json()
    assert len(data["locations"]) > 5
    assert {"id", "name", "lat", "lng", "type"} <= set(data["locations"][0])


def test_register_login_profile_flow(client):
    body = {"username": "flow_user", "password": "secret123"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json=body).status_code == 409
    assert client.post("/api/auth/login", json={**body, "password": "wrongpass"}).status_code == 401

    token = client.post("/api/auth/login", json=body).get_json()["token"]
    hdr = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/auth/profile", headers=hdr).get_json()["profile"]
    assert profile["username"] == "flow_user" and profile["travel_history"] == []

    assert client.post("/api/auth/logout", headers=hdr).status_code == 200
    assert client.get("/api/auth/profile", headers=hdr).status_code == 401


def test_password_is_not_stored_as_plain_sha256(client):
    client.post("/api/auth/register", json={"username": "hash_user", "password": "secret123"})
    conn = sqlite3.connect(Config.DB_PATH)
    (stored,) = conn.execute("SELECT password_hash FROM users WHERE username='hash_user'").fetchone()
    conn.close()
    assert stored.startswith(("scrypt:", "pbkdf2:"))


def test_legacy_sha256_hash_still_logs_in_and_is_upgraded(client):
    salt = "0123456789abcdef"
    legacy = f"{salt}${hashlib.sha256((salt + 'oldpass1').encode()).hexdigest()}"
    conn = sqlite3.connect(Config.DB_PATH)
    conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("legacy_user", legacy))
    conn.commit()

    res = client.post("/api/auth/login", json={"username": "legacy_user", "password": "oldpass1"})
    assert res.status_code == 200

    (stored,) = conn.execute("SELECT password_hash FROM users WHERE username='legacy_user'").fetchone()
    conn.close()
    assert stored.startswith(("scrypt:", "pbkdf2:"))


def test_buddy_endpoints_require_login(client, auth):
    assert client.post("/api/buddy/sync", json={"buddy_identifier": auth["username"]}).status_code == 401
    assert client.get("/api/buddy/search?q=ab").status_code == 401

    hdr = {"Authorization": auth["Authorization"]}
    ok = client.post("/api/buddy/sync", json={"buddy_identifier": auth["username"]}, headers=hdr)
    assert ok.status_code == 200 and ok.get_json()["buddy"]["username"] == auth["username"]


def test_save_itinerary_requires_login_and_persists(client, auth):
    payload = {"city": "上海", "days": 1, "itinerary": {"summary": "x", "days": []}}
    assert client.post("/api/itinerary/save", json=payload).status_code == 401
    hdr = {"Authorization": auth["Authorization"]}
    assert client.post("/api/itinerary/save", json=payload, headers=hdr).status_code == 201
    hist = client.get("/api/auth/profile", headers=hdr).get_json()["profile"]["travel_history"]
    assert len(hist) == 1 and hist[0]["city"] == "上海"


def test_itinerary_generate_demo_mode(client):
    locs = client.get("/api/locations/list?city=上海").get_json()["locations"]
    res = client.post("/api/itinerary/generate", json={
        "destination": "上海", "days": 2, "budget_amount": 500,
        "selected_locations": [l["id"] for l in locs[:6]],
    })
    assert res.status_code == 200
    data = res.get_json()
    assert len(data["itinerary"]["days"]) >= 1


# ------------------------------------------------------------------ trips ----
ITIN = {"summary": "两日漫游", "days": [{"title": "Day 1", "items": [{"time": "09:00", "activity": "外滩", "location": {"name": "外滩"}}]}]}


def test_trip_crud_and_isolation(client, auth):
    hdr = {"Authorization": auth["Authorization"]}
    res = client.post("/api/trips", json={"city": "上海", "days": 1, "budget_amount": 800, "start_date": "2026-10-01", "itinerary": ITIN}, headers=hdr)
    assert res.status_code == 201
    trip = res.get_json()["trip"]
    assert trip["title"] == "两日漫游" and trip["budget"] == 800 and trip["stops"] == 1

    lst = client.get("/api/trips", headers=hdr).get_json()["trips"]
    assert [t["id"] for t in lst] == [trip["id"]] and "itinerary" not in lst[0]

    upd = {**ITIN, "days": ITIN["days"] + [{"title": "Day 2", "items": []}]}
    put = client.put(f"/api/trips/{trip['id']}", json={"itinerary": upd, "title": "改名"}, headers=hdr)
    assert put.get_json()["trip"]["title"] == "改名"
    assert len(client.get(f"/api/trips/{trip['id']}", headers=hdr).get_json()["trip"]["itinerary"]["days"]) == 2

    # 另一个用户看不到、改不了、删不了
    other = client.post("/api/auth/register", json={"username": "someone_else", "password": "secret123"}).get_json()
    ohdr = {"Authorization": f"Bearer {other['token']}"}
    assert client.get(f"/api/trips/{trip['id']}", headers=ohdr).status_code == 404
    assert client.put(f"/api/trips/{trip['id']}", json={"title": "x"}, headers=ohdr).status_code == 404
    assert client.delete(f"/api/trips/{trip['id']}", headers=ohdr).status_code == 404

    assert client.delete(f"/api/trips/{trip['id']}", headers=hdr).status_code == 200
    assert client.get(f"/api/trips/{trip['id']}", headers=hdr).status_code == 404


def test_trip_validation(client, auth):
    hdr = {"Authorization": auth["Authorization"]}
    assert client.post("/api/trips", json={"itinerary": {"nope": 1}}, headers=hdr).status_code == 400
    assert client.post("/api/trips", json={"itinerary": ITIN, "start_date": "10/01"}, headers=hdr).status_code == 400
    assert client.get("/api/trips").status_code == 401


def test_share_link_is_public_readonly_and_revocable(client, auth):
    hdr = {"Authorization": auth["Authorization"]}
    trip = client.post("/api/trips", json={"itinerary": ITIN}, headers=hdr).get_json()["trip"]
    token = client.post(f"/api/trips/{trip['id']}/share", headers=hdr).get_json()["token"]

    pub = client.get(f"/api/trips/shared/{token}")  # 无需登录
    assert pub.status_code == 200
    body = pub.get_json()["trip"]
    assert body["author"] == auth["username"] and "share_token" not in body and "user_id" not in body

    assert client.delete(f"/api/trips/{trip['id']}/share", headers=hdr).status_code == 200
    assert client.get(f"/api/trips/shared/{token}").status_code == 404
    assert client.get("/api/trips/shared/doesnotexist").status_code == 404


def test_buddy_only_sees_shared_trips(client, auth):
    hdr = {"Authorization": auth["Authorization"]}
    private = client.post("/api/trips", json={"title": "私密", "itinerary": ITIN}, headers=hdr).get_json()["trip"]
    public = client.post("/api/trips", json={"title": "公开", "itinerary": ITIN}, headers=hdr).get_json()["trip"]
    client.post(f"/api/trips/{public['id']}/share", headers=hdr)

    other = client.post("/api/auth/register", json={"username": "buddy_viewer", "password": "secret123"}).get_json()
    res = client.post("/api/buddy/sync", json={"buddy_identifier": auth["username"]},
                      headers={"Authorization": f"Bearer {other['token']}"}).get_json()
    titles = [p["title"] for p in res["shared_plans"]]
    assert titles == ["公开"] and private["title"] not in titles
    assert "itinerary" not in res["shared_plans"][0]


def test_legacy_save_endpoint_still_works(client, auth):
    hdr = {"Authorization": auth["Authorization"]}
    assert client.post("/api/itinerary/save", json={"city": "上海", "days": 1, "itinerary": ITIN}, headers=hdr).status_code == 201
    assert len(client.get("/api/auth/profile", headers=hdr).get_json()["profile"]["travel_history"]) == 1


def test_legacy_history_json_is_migrated(client):
    import json, sqlite3
    from backend.config import Config
    from backend.database import init_db

    conn = sqlite3.connect(Config.DB_PATH)
    conn.execute("INSERT INTO users (username, password_hash, travel_history) VALUES (?,?,?)",
                 ("old_timer", "x", json.dumps([{"city": "上海", "days": 2, "budget": "人均 ¥600", "itinerary": ITIN}])))
    conn.commit(); conn.close()
    init_db()

    conn = sqlite3.connect(Config.DB_PATH)
    row = conn.execute("SELECT t.budget, t.days, u.travel_history FROM trips t JOIN users u ON u.id=t.user_id WHERE u.username='old_timer'").fetchone()
    conn.close()
    assert row == (600, 2, None)


def test_weather_validation_and_graceful_degrade(client, monkeypatch):
    from datetime import date, timedelta
    import backend.routes.trips as mod

    assert client.get("/api/weather?start=bad").status_code == 400
    far = (date.today() + timedelta(days=90)).isoformat()
    assert client.get(f"/api/weather?start={far}&days=2").get_json()["available"] is False

    soon = (date.today() + timedelta(days=1)).isoformat()

    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(mod.requests, "get", boom)
    assert client.get(f"/api/weather?start={soon}&days=2").get_json()["available"] is False


def test_weather_happy_path(client, monkeypatch):
    from datetime import date, timedelta
    import backend.routes.trips as mod

    d0 = date.today() + timedelta(days=2)
    d1 = d0 + timedelta(days=1)

    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"daily": {"time": [d0.isoformat(), d1.isoformat()], "weathercode": [0, 63],
                              "temperature_2m_max": [28, 24], "temperature_2m_min": [20, 19],
                              "precipitation_probability_max": [5, 80]}}
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: R())
    out = client.get(f"/api/weather?city=上海&start={d0.isoformat()}&days=2").get_json()
    assert out["available"] and [x["code"] for x in out["days"]] == [0, 63]


# ------------------------------------------------------------------ video ----
def test_video_analyze_requires_login_and_blocks_non_douyin_hosts(client, auth):
    assert client.post("/api/video/analyze", json={"urls": ["https://v.douyin.com/abc/"]}).status_code == 401

    hdr = {"Authorization": auth["Authorization"]}
    for evil in ["http://169.254.169.254/latest/meta-data", "http://localhost:5000/api/health", "https://douyin.com.evil.io/x", "file:///etc/passwd"]:
        res = client.post("/api/video/analyze", json={"urls": [evil]}, headers=hdr)
        assert res.status_code == 400, evil
    too_many = ["https://v.douyin.com/a/"] * 11
    assert client.post("/api/video/analyze", json={"urls": too_many}, headers=hdr).status_code == 400


def test_is_allowed_video_url():
    from backend.routes.video import is_allowed_video_url

    assert is_allowed_video_url("https://v.douyin.com/xxxx/")
    assert is_allowed_video_url("https://www.iesdouyin.com/share/video/1")
    assert not is_allowed_video_url("https://notdouyin.com/x")
    assert not is_allowed_video_url("ftp://v.douyin.com/x")
