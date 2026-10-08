"""
互联网渠道。选型参照 Agent Reach（https://github.com/Panniantong/agent-reach）：
直接使用它路由到的上游工具，不经过任何封装层，网站运行时也不依赖 agent-reach / mcporter 命令。

  · Jina Reader  r.jina.ai/<url>   读任意网页正文，包括头条、知乎这类要执行 JS 才显示内容的页面
  · Exa          mcp.exa.ai/mcp    语义搜索（结果自带正文摘录，免 Key）；web_fetch 读网页，作为 Jina 的后备
  · yt-dlp                         下载 B 站 / YouTube / 小红书 / 西瓜视频；抖音分享页解析失败时也用它兜底

每个渠道失败都只返回空结果，由调用方换下一条路。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests

from backend.config import Config

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

# 读到这些标题说明被登录墙 / 风控挡住了，拿到的不是正文
_WALL_TITLES = ("小红书 - 你的生活兴趣社区", "安全验证", "验证码", "知乎 - 有问题，就会有答案", "没有知识存在的荒原", "Just a moment", "访问被拒绝")


def public_url(url: str) -> bool:
    """只接受公网 http(s) 地址（拒绝 localhost / 内网 IP），防止被当作探测内网的跳板"""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host


# ------------------------------------------------------------------ Exa ----
def _exa_call(tool: str, args: dict, timeout: float = 20) -> str:
    """调用 Exa 的 MCP 工具（Streamable HTTP，无状态，单次 JSON-RPC 请求即可）"""
    url = Config.EXA_MCP_URL + (f"?exaApiKey={Config.EXA_API_KEY}" if Config.EXA_API_KEY else "")
    resp = requests.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}},
        headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    # SSE 响应头没有声明字符集，requests 会按 ISO-8859-1 解码，中文会乱、还会被误切行：按 UTF-8 解码并只按 \n 切
    body = resp.content.decode("utf-8", "replace")
    if "data:" in body[:200]:
        body = "\n".join(line[5:].strip() for line in body.split("\n") if line.startswith("data:"))
    data = json.loads(body)
    if data.get("error") or (data.get("result") or {}).get("isError"):
        raise RuntimeError(str(data.get("error") or data["result"].get("content"))[:200])
    return "\n".join(c.get("text", "") for c in (data.get("result") or {}).get("content", []) if c.get("type") == "text")


def _exa_blocks(text: str) -> list[dict]:
    """Exa 返回的纯文本：每条以 Title: / URL: / Published: / Highlights 或 Text 开头"""
    out = []
    for block in re.split(r"\n(?=Title: )", "\n" + text):
        title = re.search(r"^Title: (.*)$", block, re.M)
        url = re.search(r"^URL: (\S+)", block, re.M)
        if not (title and url):
            continue
        body = re.split(r"^(?:Highlights|Text|Summary):\s*$", block, maxsplit=1, flags=re.M)
        content = body[1] if len(body) > 1 else ""
        content = re.sub(r"\n-{3,}\s*$", "", content).replace("\n...\n", "\n").strip()
        published = re.search(r"^Published: (\S+)", block, re.M)
        out.append({"title": title.group(1).strip(), "url": url.group(1).strip(), "content": content, "published": published.group(1)[:10] if published else ""})
    return out


def exa_search(query: str, num: int = 8) -> list[dict]:
    """Exa 语义搜索。结果带正文摘录（比普通搜索摘要信息多得多），跳过 Exa 自己生成的聚合页。"""
    items = []
    for b in _exa_blocks(_exa_call("web_search_exa", {"query": query, "numResults": num})):
        if "exa.ai/" in b["url"] or not b["content"]:
            continue
        content = re.sub(r"\s+", " ", re.sub(r"[#>*`]+", " ", b["content"])).strip()
        items.append({"title": b["title"], "url": b["url"], "snippet": content[:320], "content": content[:2500], "engine": "Exa", "published": b["published"]})
    return items


# ------------------------------------------------------------- 读网页 ----
def _clean_markdown(md: str) -> str:
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)  # 图片
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)  # 链接只留文字
    lines = []
    for line in md.splitlines():
        line = line.strip(" \t#>*-|")
        # 导航栏、按钮这类很短又没有中文句子的行没有信息量
        if len(line) < 6 and not re.search(r"[一-龥]{2,}", line):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _jina(url: str, timeout: float) -> dict:
    # 用如实的程序标识：Jina 会拒绝冒充浏览器的请求（403）
    headers = {"User-Agent": "yipaijihe/1.0 (travel planner)", "X-Return-Format": "markdown"}
    if Config.JINA_API_KEY:
        headers["Authorization"] = f"Bearer {Config.JINA_API_KEY}"
    resp = requests.get(f"https://r.jina.ai/{url}", headers=headers, timeout=timeout)
    resp.raise_for_status()
    raw = resp.content.decode("utf-8", "replace")
    title = re.search(r"^Title: (.*)$", raw, re.M)
    body = raw.split("Markdown Content:", 1)[-1]
    return {"title": title.group(1).strip() if title else "", "text": _clean_markdown(body)}


def read_url(url: str, limit: int = 6000, timeout: float = 25, fallback: bool = True) -> dict:
    """
    读网页正文 → {"title", "text", "via", "error"}。先用 Jina Reader，失败或被登录墙挡住再用 Exa web_fetch（fallback=False 时不用）。
    请求由 Jina / Exa 的服务器发出，本机不会直接访问用户给的地址。
    """
    if not Config.HAS_READER:
        return {"title": "", "text": "", "via": "", "error": "没有开启网页读取"}
    if not public_url(url):
        return {"title": "", "text": "", "via": "", "error": "链接地址不合法"}
    errors = []
    channels = [("Jina Reader", lambda: _jina(url, timeout)), ("Exa", lambda: _exa_page(url, timeout))]
    for via, fn in channels if fallback else channels[:1]:
        try:
            got = fn()
        except Exception as e:  # noqa: BLE001 — 换下一个渠道
            errors.append(f"{via}: {str(e)[:80]}")
            continue
        if any(w in got["title"] for w in _WALL_TITLES) or got["title"].startswith("登录") or len(re.findall(r"[一-龥A-Za-z]", got["text"])) < 20:
            errors.append(f"{via}: 页面需要登录或没有正文")
            continue
        text = got["text"]
        # 正文前面常是导航栏（「关注 推荐 北京 视频…」），文章页都会再写一遍标题：从标题处开始取
        head = got["title"][:12]
        if head and 0 < text.find(head) < len(text) // 2:
            text = text[text.find(head):]
        return {"title": got["title"][:80], "text": text[:limit], "via": via, "error": ""}
    logger.info("读取网页失败 %s：%s", url, "；".join(errors))
    return {"title": "", "text": "", "via": "", "error": "需要登录或无法读取正文"}


def _exa_page(url: str, timeout: float) -> dict:
    blocks = _exa_blocks(_exa_call("web_fetch_exa", {"urls": [url], "maxCharacters": 6000}, timeout))
    if not blocks:
        raise RuntimeError("Exa 没有返回内容")
    return {"title": blocks[0]["title"], "text": _clean_markdown(blocks[0]["content"])}


# ------------------------------------------------------------------ yt-dlp ----
def ytdlp_available() -> bool:
    return Config.HAS_YTDLP


class _QuietLogger:
    """yt-dlp 的提示和报错都转到日志里（quiet 只关进度，不关报错输出）"""

    def debug(self, msg):
        pass

    info = debug

    def warning(self, msg):
        logger.debug("yt-dlp: %s", msg)

    def error(self, msg):
        logger.info("yt-dlp: %s", msg)


def _ytdlp_opts(**extra) -> dict:
    # YouTube 需要 JS 运行时解签名：有哪个用哪个（Agent Reach 也是给 yt-dlp 配 node）
    runtimes = {name: {} for name in ("deno", "node", "bun") if shutil.which(name)}
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
        "noplaylist": True,
        "socket_timeout": 20,
        "max_filesize": 200 * 1024 * 1024,
        "http_headers": {"User-Agent": _UA},
    }
    if runtimes:
        opts["js_runtimes"] = runtimes
    if Config.YTDLP_COOKIES and os.path.isfile(Config.YTDLP_COOKIES):
        opts["cookiefile"] = Config.YTDLP_COOKIES
    opts.update(extra)
    return opts


def ytdlp_info(url: str) -> dict:
    """只取元数据：标题、简介、时长、封面"""
    import yt_dlp

    with yt_dlp.YoutubeDL(_ytdlp_opts(skip_download=True)) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next(e for e in info["entries"] if e)
    return {
        "title": (info.get("title") or "").strip(),
        "description": (info.get("description") or "").strip()[:3000],
        "duration": int(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail") or "",
        "uploader": info.get("uploader") or "",
        "webpage_url": info.get("webpage_url") or url,
    }


def ytdlp_download(url: str, fmt: str, dest: Path, name: str) -> Path:
    """按格式下载到 dest；只选单文件格式（不需要 ffmpeg 合并音视频）"""
    import yt_dlp

    with yt_dlp.YoutubeDL(_ytdlp_opts(format=fmt, outtmpl=str(dest / f"{name}.%(ext)s"))) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist" and info.get("entries"):
            info = next(e for e in info["entries"] if e)
        path = Path(ydl.prepare_filename(info))
    if not path.exists():
        found = sorted(dest.glob(f"{name}.*"))
        if not found:
            raise RuntimeError("下载没有产生文件")
        path = found[0]
    return path
