"""
大模型相关能力的测试：全部离线，用假的搜索结果 / 假的大模型回复驱动真实代码路径。
"""

import json
import time
from types import SimpleNamespace

import pytest

from backend.config import Config


@pytest.fixture()
def llm_on(monkeypatch):
    """假装配置了 DeepSeek（不会真的发请求：调用点都被替换）"""
    monkeypatch.setattr(Config, "HAS_LLM", True)
    monkeypatch.setattr(Config, "HAS_WEB_SEARCH", True)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "deepseek")
    from backend.services import llm_service

    llm_service._reset("llm")
    return llm_service


# ------------------------------------------------------------ 基础工具 ----
def test_parse_json_handles_fences_wrappers_and_truncation():
    from backend.services.llm_service import _extract_json_array, parse_json

    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('好的，结果如下：{"a": [1, 2]} 希望有帮助') == {"a": [1, 2]}
    assert _extract_json_array('{"places": [{"name": "外滩"}]}') == [{"name": "外滩"}]
    # 输出被截断：保留完整的对象
    assert _extract_json_array('[{"name": "外滩"}, {"name": "豫园"}, {"name": "武') == [{"name": "外滩"}, {"name": "豫园"}]
    assert parse_json("完全不是 JSON") is None


def test_deepseek_request_options(monkeypatch):
    from backend.services.llm_service import _request_options

    monkeypatch.setattr(Config, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(Config, "LLM_THINKING", "off")
    opts = _request_options(True, None, 2000)
    assert opts["extra_body"] == {"thinking": {"type": "disabled"}}
    assert opts["response_format"] == {"type": "json_object"} and opts["max_tokens"] == 2000
    # 开思考时 max_tokens 要放宽，否则思考过程吃光额度、答案为空
    assert _request_options(False, True, 2000)["max_tokens"] == 10000

    monkeypatch.setattr(Config, "LLM_PROVIDER", "other")
    assert _request_options(True, None, 2000) == {"max_tokens": 2000}


def test_wgs84_to_gcj02():
    from backend.services.geo import km_between, wgs84_to_gcj02

    lat, lng = wgs84_to_gcj02(31.2304, 121.4737)
    # 上海一带 GCJ-02 相对 WGS-84 约向东南偏 300-600 米
    assert -0.004 < lat - 31.2304 < 0 and 0.003 < lng - 121.4737 < 0.006
    assert 0.2 < km_between((31.2304, 121.4737), (lat, lng)) < 0.7
    assert wgs84_to_gcj02(35.68, 139.76) == (35.68, 139.76)  # 国外不偏移


# ------------------------------------------------------------ 联网搜索 ----
_TOUTIAO_HTML = """
<div class="result-content" cr-params="{&quot;gid&quot;:&quot;123&quot;,&quot;title&quot;:&quot;成都三日游&lt;em&gt;攻略&lt;/em&gt;&quot;}">
  <div class="l-paragraph mt-8">Day1 宽窄巷子→人民公园→春熙路</div></div>
<div class="result-content" cr-params="{&quot;gid&quot;:&quot;456&quot;,&quot;title&quot;:&quot;无摘要的卡片&quot;}"></div>
"""


def test_toutiao_parser_and_relevance_filter(monkeypatch):
    from backend.services import web_search

    class R:
        status_code = 200
        text = _TOUTIAO_HTML

        def raise_for_status(self):
            pass

    monkeypatch.setattr(web_search.requests, "get", lambda *a, **k: R())
    items = web_search._toutiao("成都3日游攻略")
    assert items == [{"title": "成都三日游攻略", "url": "https://www.toutiao.com/article/123/", "snippet": "Day1 宽窄巷子→人民公园→春熙路", "engine": "头条搜索"}]

    # Bing 有时对程序请求返回无关的热门结果：必须过滤掉
    noise = {"title": "To lube or not to lube", "snippet": "rifle forum"}
    assert not web_search._relevant(noise, "成都3日游攻略 必去景点", ("成都",))
    assert web_search._relevant(items[0], "成都3日游攻略 必去景点", ("成都",))


def _fake_places(sources):
    return json.dumps({"places": [
        {"name": "宽窄巷子", "type": "street", "best_time": "下午-傍晚", "duration_min": 120, "cost_level": "免费", "reason": "老成都街巷", "sources": sources, "pick": True, "fit_reason": "适合慢逛", "lat": 30.66, "lng": 104.05},
        {"name": "成都", "type": "landmark"},  # 城市本身：应被丢弃
        {"name": "人民公园", "type": "nature", "tips": "周一闭馆", "sources": sources[:1], "lat": 99, "lng": 99},
    ]}, ensure_ascii=False)


def test_discover_cites_sources_and_falls_back_to_model_knowledge(monkeypatch, llm_on):
    from backend.services import geo, web_search

    web_search._CACHE.clear()
    monkeypatch.setattr(geo, "city_center", lambda city: (30.66, 104.06))
    monkeypatch.setattr(geo, "locate", lambda name, city, near=None: (30.6577, 104.0617) if name == "人民公园" else None)
    sources = [{"title": f"成都攻略{i}", "url": f"https://example.com/{i}", "snippet": "宽窄巷子 人民公园", "engine": "头条搜索"} for i in range(4)]
    monkeypatch.setattr(web_search, "_gather_sources", lambda *a: sources)
    prompts = []
    monkeypatch.setattr(web_search, "_ask_llm", lambda prompt: prompts.append(prompt) or _fake_places([1, 2]))

    places, meta = web_search.discover_attractions("成都", 2, {"mbti": "ILST"})
    assert meta["mode"] == "web" and [p["name"] for p in places] == ["宽窄巷子", "人民公园"]
    assert "[1] 成都攻略0" in prompts[0]  # 资料编号后交给模型
    kz, park = places
    assert kz["selected"] and kz["reason"] == "适合慢逛" and [s["url"] for s in kz["sources"]] == ["https://example.com/0", "https://example.com/1"]
    assert park["tips"] == "周一闭馆" and (park["lat"], park["lng"]) == (30.6577, 104.0617)  # 地理编码优先于模型坐标
    assert kz["lat"] != 30.66  # 模型坐标按 WGS-84 转成 GCJ-02
    assert {s["url"] for s in meta["sources"]} == {"https://example.com/0", "https://example.com/1"}

    # 搜索引擎全挂了：退回大模型自身知识，并明确标注未核实
    web_search._CACHE.clear()
    monkeypatch.setattr(web_search, "_gather_sources", lambda *a: [])
    places, meta = web_search.discover_attractions("成都", 2, {})
    assert meta["mode"] == "knowledge" and "未联网核实" in places[0]["source_label"] and places[0]["sources"] == []
    assert "当前无法联网" in prompts[-1]


def test_recommend_puts_web_results_first_and_saves_them(client, monkeypatch):
    import backend.routes.locations as mod
    from backend.services import geo

    monkeypatch.setattr(geo, "city_center", lambda city: (31.23, 121.47))
    web = [
        {"name": "外滩", "type": "landmark", "lat": 31.24, "lng": 121.49, "selected": True, "reason": "夜景", "source": "ai_discover", "sources": [{"title": "攻略", "url": "https://e.com/1"}]},
        {"name": "茂昌眼镜博物馆", "type": "culture", "lat": 31.233, "lng": 121.48, "selected": True, "reason": "小众", "source": "ai_discover", "sources": []},
        {"name": "没有坐标的小店", "type": "food", "lat": None, "lng": None, "selected": False, "source": "ai_discover", "sources": []},
    ]
    monkeypatch.setattr(mod, "discover_trip_attractions", lambda city, days, profile: ([dict(w) for w in web], {"mode": "web", "sources": [{"title": "攻略", "url": "https://e.com/1", "engine": "Bing"}]}))
    res = client.post("/api/locations/default-recommend", json={"city": "上海", "days": 2}).get_json()
    assert res["source"] == "web_search" and res["sources"][0]["url"] == "https://e.com/1"
    names = [a["name"] for a in res["attractions"]]
    assert names[:3] == ["外滩", "茂昌眼镜博物馆", "没有坐标的小店"]
    bund = res["attractions"][0]
    catalog_bund = next(a for a in client.get("/api/locations/list?city=上海").get_json()["locations"] if a["name"] == "外滩夜景")
    assert bund["id"] == catalog_bund["id"]  # 「外滩」沿用库里「外滩夜景」那条，行程能用上完整数据
    assert res["attractions"][1]["id"].startswith("loc_")  # 新地点写进了景点库
    extras = res["attractions"][3:]
    assert extras and all(a["source"] == "builtin" and not a["selected"] for a in extras) and "外滩夜景" not in [a["name"] for a in extras]

    # 新城市：自动建城市记录（地图中心 / 天气要用）。用虚构城市名，避免影响其他用例对真实城市的假设
    monkeypatch.setattr(mod, "discover_trip_attractions", lambda *a: ([{"name": "示例湖", "type": "landmark", "lat": 30.25, "lng": 120.14, "selected": True, "source": "ai_discover", "sources": []}], {"mode": "web", "sources": []}))
    monkeypatch.setattr(geo, "city_center", lambda city: (30.27, 120.15))
    client.post("/api/locations/default-recommend", json={"city": "示例市", "days": 1})
    city = client.get("/api/locations/list?city=示例市").get_json()
    assert city["total"] == 1 and abs(city["city_center"]["lat"] - 30.27) < 0.01


# ------------------------------------------------------------ 对话 ----
def _msg(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls), finish_reason="stop")])


def test_chat_can_search_the_web_and_cites_sources(client, monkeypatch, llm_on):
    from backend.services import web_search

    seen = {}

    class FakeCompletions:
        def __init__(self):
            self.n = 0

        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                assert kw["tools"][0]["function"]["name"] == "web_search"
                seen["system"] = kw["messages"][0]["content"]
                call = SimpleNamespace(id="c1", function=SimpleNamespace(name="web_search", arguments='{"query": "上海博物馆东馆 预约"}'))
                return _msg(None, [call])
            seen["tool"] = kw["messages"][-1]["content"]
            return _msg("东馆散客免预约，周二闭馆 [1]")

    monkeypatch.setattr(llm_on, "client", SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))
    monkeypatch.setattr(web_search, "answer_sources", lambda q, city: ("[1] 上博开放公告（头条搜索）\n散客免预约", [{"title": "上博开放公告", "url": "https://e.com/sh", "engine": "头条搜索"}]))
    ctx = {"trip": {"city": "上海", "days": 2}, "itinerary": {"days": [{"day": 1, "items": [{"time": "09:00", "location": {"name": "外滩夜景"}}]}]}}
    res = client.post("/api/chat/message", json={"message": "上博东馆要预约吗", "context": ctx}).get_json()
    assert res["engine"] == "llm" and res["reply"].startswith("东馆散客免预约")
    assert res["sources"] == [{"title": "上博开放公告", "url": "https://e.com/sh", "engine": "头条搜索", "n": 1}]
    assert "Day 1：09:00 外滩夜景" in seen["system"] and "散客免预约" in seen["tool"]


def test_chat_falls_back_to_local_assistant_when_llm_fails(client, monkeypatch, llm_on):
    class Boom:
        def create(self, **kw):
            raise TimeoutError("timeout")

    monkeypatch.setattr(llm_on, "client", SimpleNamespace(chat=SimpleNamespace(completions=Boom())))
    res = client.post("/api/chat/message", json={"message": "下雨了怎么办", "context": {"trip": {"city": "上海"}}}).get_json()
    assert res["engine"] == "local" and res["reply"] and res["sources"] == []
    llm_on._reset("llm")


# ------------------------------------------------------------ 视频 ----
def test_video_job_reports_progress_and_uses_what_it_saw(client, auth, monkeypatch):
    from backend.services import video_processor

    def fake_understand(self, url, city="", hints=None, progress=None):
        for stage in ("读取视频信息", "下载视频", "看画面"):
            progress(stage)
        return {"title": "上海一日游", "transcript": "", "seen": {"text": ["今天去武康路拍照"], "places": [{"name": "外滩夜景", "evidence": "字幕"}], "summary": ""}, "steps": ["title", "vision"], "notes": ["本地语音模型还在准备（40%），这次没有听语音"]}

    monkeypatch.setattr(video_processor.VideoProcessor, "understand", fake_understand)
    hdr = {"Authorization": auth["Authorization"]}
    job = client.post("/api/video/jobs", json={"urls": ["https://v.douyin.com/abc/"], "city": "上海"}, headers=hdr)
    assert job.status_code == 202
    job_id = job.get_json()["job_id"]
    for _ in range(100):
        state = client.get(f"/api/video/jobs/{job_id}", headers=hdr).get_json()
        if state["status"] != "running":
            break
        time.sleep(0.05)
    assert state["status"] == "done" and state["items"][0]["stage"] == "完成"
    result = state["result"]
    assert {l["name"] for l in result["locations"]} == {"武康路·武康大楼", "外滩夜景"}
    t = result["transcripts"][0]
    assert t["done"] == ["读了标题", "看了画面"] and "40%" in t["notes"][0] and "武康路" in t["screen"]

    # 别人的任务看不到
    other = client.post("/api/auth/guest").get_json()["token"]
    assert client.get(f"/api/video/jobs/{job_id}", headers={"Authorization": f"Bearer {other}"}).status_code == 404


def test_vision_text_and_transcript_guard(monkeypatch, llm_on):
    from backend.services import vision

    assert vision.as_text({"text": ["宽窄巷子", "人均 30"], "places": [{"name": "人民公园"}]}) == "画面文字：宽窄巷子；人均 30\n画面中的地点：人民公园"
    # 校对转写时模型擅自总结（长度差太多）→ 保留原文
    monkeypatch.setattr(llm_on, "chat_completion", lambda *a, **k: '{"text": "去了外滩"}')
    raw = "今天我们先去五康路拍照然后去外摊看夜景晚上吃了生煎包真的很好吃"
    assert llm_on.polish_transcript(raw, "上海") == raw
    monkeypatch.setattr(llm_on, "chat_completion", lambda *a, **k: '{"text": "今天我们先去武康路拍照，然后去外滩看夜景，晚上吃了生煎包，真的很好吃。"}')
    assert "武康路" in llm_on.polish_transcript(raw, "上海")


def test_asr_status_when_disabled():
    from backend.services import asr

    assert asr.engine() == "none" and asr.status() == {"engine": "none", "ready": False, "state": "unavailable"}


def test_text_extraction_prefers_longer_place_names(client, auth):
    text = "晚上去了北外滩的白玉兰广场看夜景，顺路在虹口吃了一家老字号生煎"
    res = client.post("/api/inspiration/extract", json={"text": text, "city": "上海"}, headers={"Authorization": auth["Authorization"]}).get_json()
    names = [p["name"] for p in res["places"]]
    assert "北外滩" in names and "外滩夜景" not in names
    assert next(p for p in res["places"] if p["name"] == "北外滩")["reason"].startswith("晚上去了北外滩")


def test_short_natural_landmarks_are_kept():
    from backend.routes.video import _filter_extracted_locations

    text = "打算去杭州，西湖边走走，再去灵隐寺，晚上河坊街吃东西，路过附近的商场，第二天去乌镇，住在桐乡市"
    locs = [{"name": n, "type": "landmark"} for n in ("西湖", "灵隐寺", "河坊街", "商场", "附近", "乌镇", "桐乡市")]
    assert [l["name"] for l in _filter_extracted_locations(locs, text)] == ["西湖", "灵隐寺", "河坊街", "乌镇"]
