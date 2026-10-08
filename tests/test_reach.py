"""
互联网渠道（选型参照 Agent Reach：Exa / Jina Reader / yt-dlp）的离线测试：用假响应驱动真实解析与降级逻辑。
"""

from types import SimpleNamespace

import pytest

from backend.config import Config

_EXA_TEXT = """Title: 成都三日游攻略 - 去哪儿
URL: https://travelnews.qunar.com/ugc/chengdu-3-day
Published: 2025-10-05T00:00:00.000Z
Author: N/A
Highlights:
# 成都三日游
Day1 宽窄巷子 → 人民公园
...
鹤鸣茶社喝盖碗茶

---

Title: 成都 小众景点 - Exa Places
URL: https://exa.ai/library/places?q=abc
Published: 2026-10-08T00:00:00.000Z
Highlights:
Ten places are listed here
"""


def test_exa_results_are_parsed_and_aggregator_pages_skipped(monkeypatch):
    from backend.services import reach

    monkeypatch.setattr(reach, "_exa_call", lambda tool, args, timeout=20: _EXA_TEXT)
    items = reach.exa_search("成都 攻略")
    assert len(items) == 1
    it = items[0]
    assert it["engine"] == "Exa" and it["published"] == "2025-10-05" and it["url"].startswith("https://travelnews.qunar.com")
    assert "宽窄巷子" in it["content"] and "鹤鸣茶社" in it["content"] and "#" not in it["content"]


def test_exa_sse_body_is_decoded_as_utf8(monkeypatch):
    """SSE 响应头不带字符集：必须按 UTF-8 解码，否则中文乱码、JSON 被误切行"""
    from backend.services import reach

    payload = '{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"Title: 宽窄巷子\\nURL: https://a.com/1"}]}}'

    class R:
        content = f"event: message\ndata: {payload}\n\n".encode("utf-8")
        encoding = "ISO-8859-1"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(reach.requests, "post", lambda *a, **k: R())
    assert reach._exa_call("web_search_exa", {"query": "x"}) == "Title: 宽窄巷子\nURL: https://a.com/1"


def test_read_url_trims_navigation_detects_login_walls_and_falls_back(monkeypatch):
    from backend.services import reach

    monkeypatch.setattr(Config, "HAS_READER", True)
    article = {"title": "成都三日深度游本地人私藏路线", "text": "关注\n推荐\n北京\n成都三日深度游本地人私藏路线\nDay 1 熊猫基地→文殊院→人民公园→宽窄巷子，早上七点半开门就进去，熊猫最活跃。"}
    monkeypatch.setattr(reach, "_jina", lambda url, timeout: article)
    got = reach.read_url("https://www.toutiao.com/article/1/")
    assert got["via"] == "Jina Reader" and got["text"].startswith("成都三日深度游")

    # Jina 被登录墙挡住 → 改用 Exa
    monkeypatch.setattr(reach, "_jina", lambda url, timeout: {"title": "小红书 - 你的生活兴趣社区", "text": "发现 直播 发布 通知"})
    monkeypatch.setattr(reach, "_exa_page", lambda url, timeout: {"title": "厦门三天两夜", "text": "第一天鼓浪屿，坐轮渡上岛，记得提前在小程序预约船票；晚上中山路吃沙茶面。"})
    got = reach.read_url("https://www.xiaohongshu.com/explore/abc")
    assert got["via"] == "Exa" and "鼓浪屿" in got["text"]

    # 都读不到；以及内网地址直接拒绝
    monkeypatch.setattr(reach, "_exa_page", lambda url, timeout: (_ for _ in ()).throw(RuntimeError("CRAWL_EMPTY_CONTENT")))
    assert reach.read_url("https://www.xiaohongshu.com/explore/abc")["error"]
    for bad in ("http://127.0.0.1:8000/", "http://192.168.1.1/admin", "file:///etc/passwd", "http://localhost/"):
        assert reach.read_url(bad)["error"] == "链接地址不合法"


def test_article_links_are_read_and_places_cited(client, auth, monkeypatch):
    from backend.services import reach

    pages = {
        "https://mp.weixin.qq.com/s/abc": {"title": "上海周末这样玩", "text": "上午先去武康路·武康大楼拍照，然后沿着安福路喝咖啡。傍晚去外滩看夜景。", "via": "Jina Reader", "error": ""},
        "https://www.zhihu.com/question/1": {"title": "", "text": "", "via": "", "error": "需要登录或无法读取正文"},
    }
    monkeypatch.setattr(reach, "read_url", lambda url, limit=8000, timeout=25: pages[url])
    res = client.post("/api/inspiration/extract", json={"urls": list(pages), "city": "上海"}, headers={"Authorization": auth["Authorization"]}).get_json()
    assert [l["ok"] for l in res["links"]] == [True, False] and res["links"][0]["title"] == "上海周末这样玩"
    assert "需要登录" in res["links"][1]["error"]
    names = [p["name"] for p in res["places"]]
    assert names[:3] == ["武康路·武康大楼", "安福路", "外滩夜景"]
    assert "喝咖啡" in res["places"][1]["reason"]


def test_video_platforms_allowlist():
    from backend.routes.video import is_allowed_video_url

    for ok in ("https://www.bilibili.com/video/BV1xx", "https://b23.tv/abc", "https://youtu.be/x", "https://www.xiaohongshu.com/explore/1", "http://xhslink.com/a/b"):
        assert is_allowed_video_url(ok)
    for bad in ("https://evil.com/bilibili.com", "https://bilibili.com.evil.com/x", "http://127.0.0.1/x"):
        assert not is_allowed_video_url(bad)


@pytest.fixture()
def no_ai(monkeypatch):
    from backend.services import asr

    monkeypatch.setattr(Config, "HAS_VISION", False)
    monkeypatch.setattr(asr, "status", lambda: {"engine": "none", "ready": False, "state": "unavailable"})


def test_video_routes_douyin_failure_to_ytdlp_and_falls_back_to_page_text(monkeypatch, no_ai):
    from backend.services import reach
    from backend.services.video_processor import VideoProcessor

    def douyin_down(self, url, timeout=None):
        raise ValueError("抖音没有返回作品数据")

    monkeypatch.setattr(VideoProcessor, "_load_share_item", douyin_down)
    monkeypatch.setattr(reach, "ytdlp_available", lambda: True)
    monkeypatch.setattr(reach, "ytdlp_info", lambda url: {"title": "上海一日游", "description": "路线：武康路、外滩", "duration": 300, "thumbnail": "", "uploader": "", "webpage_url": url})
    got = VideoProcessor().understand("https://v.douyin.com/abc/")
    assert got["title"] == "上海一日游" and got["description"] == "路线：武康路、外滩" and got["steps"] == ["title"]

    # B 站图文 / 小红书图文笔记：yt-dlp 拿不到视频 → 读网页文字
    monkeypatch.setattr(reach, "ytdlp_info", lambda url: (_ for _ in ()).throw(RuntimeError("ERROR: No video formats found")))
    monkeypatch.setattr(reach, "read_url", lambda url, limit=6000, timeout=20: {"title": "厦门笔记", "text": "鼓浪屿和沙坡尾都很好逛", "via": "Jina Reader", "error": ""})
    got = VideoProcessor().understand("https://www.xiaohongshu.com/explore/1")
    assert got["steps"] == ["page"] and "鼓浪屿" in got["page_text"] and "No video formats" in got["notes"][0]

    # 什么都读不到：抛出异常，由路由退回只用分享文案
    monkeypatch.setattr(reach, "read_url", lambda url, limit=6000, timeout=20: {"title": "", "text": "", "via": "", "error": "需要登录或无法读取正文"})
    with pytest.raises(RuntimeError):
        VideoProcessor().understand("https://www.xiaohongshu.com/explore/1")


def test_long_videos_are_not_downloaded(monkeypatch, no_ai):
    from backend.services import reach
    from backend.services.video_processor import VideoProcessor

    monkeypatch.setattr(Config, "HAS_VISION", True)
    monkeypatch.setattr(reach, "ytdlp_available", lambda: True)
    monkeypatch.setattr(reach, "ytdlp_info", lambda url: {"title": "云南 20 天", "description": "", "duration": 3 * 3600, "thumbnail": "", "uploader": "", "webpage_url": url})
    monkeypatch.setattr(reach, "ytdlp_download", lambda *a, **k: pytest.fail("不应下载超长视频"))
    got = VideoProcessor().understand("https://www.bilibili.com/video/BV1")
    assert "超过 30 分钟" in got["notes"][0]


def test_search_reads_js_pages_through_reader(monkeypatch):
    from backend.services import reach, web_search

    calls = []
    monkeypatch.setattr(reach, "read_url", lambda url, limit=6000, timeout=25, fallback=True: calls.append((url, fallback)) or {"title": "t", "text": "正文" * 50, "via": "Jina Reader", "error": ""})
    monkeypatch.setattr(web_search, "_fetch_direct", lambda url: pytest.fail("头条要执行 JS，不应直接抓取"))
    assert web_search.fetch_text("https://www.toutiao.com/article/1/").startswith("正文")
    assert calls == [("https://www.toutiao.com/article/1/", False)]
    assert web_search._exa in web_search._ENGINES
