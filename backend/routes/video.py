"""
视频分析路由 - 接收用户粘贴的视频链接，调用 agent-reach 进行语音转写 + LLM 提取
支持并行处理多个视频
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from flask import Blueprint, jsonify, request
from backend.config import Config
from backend.routes.auth import login_required

logger = logging.getLogger(__name__)

video_bp = Blueprint("video", __name__)

# 并行处理线程池（最多同时处理 3 个视频，避免资源争抢）
_executor = ThreadPoolExecutor(max_workers=3)

# 服务端会主动请求用户提交的链接 —— 只允许抖音系域名，防止被当作 SSRF 跳板
_ALLOWED_VIDEO_HOSTS = ("douyin.com", "iesdouyin.com", "amemv.com")
MAX_VIDEO_URLS = 10


def is_allowed_video_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and any(host == d or host.endswith("." + d) for d in _ALLOWED_VIDEO_HOSTS)

# 视频地点提取后置过滤：排除城市/行政区/交通住宿/泛称等非游玩点
_GENERIC_LOCATION_NAMES = {
    "上海", "魔都", "上海市", "市区", "市中心", "附近", "周边", "这里", "那里",
    "浦东", "浦西", "黄浦", "徐汇", "静安", "长宁", "虹口", "杨浦", "普陀",
    "黄浦区", "徐汇区", "静安区", "长宁区", "虹口区", "杨浦区", "普陀区",
    "地铁", "地铁站", "公交站", "车站", "机场", "火车站", "高铁站",
    "酒店", "民宿", "住处", "住宿", "餐厅", "咖啡店", "小店", "商场",
    "景点", "地标", "路线", "街区", "城市", "目的地", "打卡点", "机位",
}

_GENERIC_LOCATION_SUFFIXES = ("区", "市", "省", "县", "镇", "乡", "村")
_NAMED_PLACE_SUFFIXES = (
    "路", "街", "巷", "弄", "桥", "寺", "庙", "馆", "园", "坊", "楼", "塔", "店", "场",
    "广场", "公园", "码头", "渡口", "书局", "书店", "美术馆", "博物馆", "步行街",
)

_INFERRED_LOCATION_ALIASES = {
    "上海环球金融中心": ("陆家嘴三件套", "三件套"),
    "金茂大厦": ("陆家嘴三件套", "三件套"),
    "上海中心大厦": ("陆家嘴三件套", "三件套"),
    "东方明珠": ("陆家嘴三件套", "三件套"),
    "上海博物馆东馆": ("上博东馆",),
    "泰公线轮渡": ("泰公线",),
}


def _context_for(url: str, share_text: str) -> str:
    """分享文案里与这条链接同一行 / 同一段的文字（抖音分享文案通常包含标题）"""
    for block in re.split(r"\n\s*\n|\n", share_text or ""):
        if url in block:
            return block
    return ""


def _process_single_video(url: str, index: int, total: int, mbti: str, share_text: str = "", city: str = "上海", catalog: list | None = None) -> dict:
    """
    处理单个视频（在线程中运行）：
      · 配置了语音转写（MIMO_API_KEY）：下载 → 转写 → 提取地点
      · 没配置或转写失败：读取作品标题 / 文案 + 用户粘贴的分享文案 → 提取地点
    """
    from backend.services.inspiration import extract_places

    url = url.strip()
    base = {"index": index, "url": url, "title": "", "transcript": None, "locations": [], "error": None, "mode": ""}
    logger.info(f"[{index+1}/{total}] 开始处理视频: {url}")

    asr_err = ""
    if Config.HAS_ASR:
        transcript, video_title, asr_err = _transcribe_video(url)
        if transcript:
            locations = _extract_locations_from_text(transcript, video_title, mbti)
            return {**base, "success": True, "title": video_title, "transcript": transcript, "locations": locations, "mode": "asr"}

    title, title_err = "", ""
    try:
        from backend.services.video_processor import VideoProcessor

        title = VideoProcessor().fetch_title(url)
    except Exception as e:  # noqa: BLE001 — 网络 / 链接失效
        title_err = str(e)[:80]
    text = "\n".join(t for t in (title, _context_for(url, share_text)) if t)
    locations = extract_places(text, city, catalog or [])
    if locations:
        for loc in locations:
            loc["source"] = "video"
        return {**base, "success": True, "title": title, "locations": locations, "mode": "title"}

    reasons = []
    if asr_err:
        reasons.append(f"语音转写失败（{asr_err[:60]}）")
    elif not Config.HAS_ASR:
        reasons.append("未配置语音转写，只能读取标题和文案")
    if title_err:
        reasons.append(f"读取视频标题失败（{title_err}）")
    elif title:
        reasons.append(f"标题「{title[:30]}」里没有具体地点")
    return {**base, "success": False, "title": title, "error": "；".join(reasons) or "没有识别到具体地点", "mode": "title"}


@video_bp.route("/analyze", methods=["POST"])
@login_required
def analyze_video():
    """
    分析用户提供的视频链接（并行处理）

    请求体：
    {
        "urls": ["https://v.douyin.com/xxxxx", ...],
        "personality": { "mbti": "DRPC", "personality_name": "..." }
    }
    """
    data = request.get_json()
    if not data or not data.get("urls"):
        return jsonify({"error": "请提供视频链接"}), 400

    if not isinstance(data["urls"], list):
        return jsonify({"error": "urls 需要是链接数组"}), 400
    urls = [u.strip() for u in data["urls"] if isinstance(u, str) and u.strip()]
    if len(urls) > MAX_VIDEO_URLS:
        return jsonify({"error": f"一次最多分析 {MAX_VIDEO_URLS} 个视频"}), 400
    bad = [u for u in urls if not is_allowed_video_url(u)]
    if bad:
        return jsonify({"error": "仅支持抖音视频链接（douyin.com / iesdouyin.com）", "invalid": bad[:3]}), 400
    personality = data.get("personality", {})
    mbti = personality.get("mbti", "")
    share_text = str(data.get("text") or "")[:20000]
    city = str(data.get("city") or "上海")[:20]
    from backend.database import get_db as _get_db
    from backend.routes.itinerary import _db_row_to_location

    _db = _get_db()
    try:
        catalog = [_db_row_to_location(r) for r in _db.execute("SELECT * FROM attractions WHERE city = ?", (city,)).fetchall()]
    finally:
        _db.close()

    if not urls:
        return jsonify({"error": "请提供有效的视频链接"}), 400

    logger.info(f"收到 {len(urls)} 个视频链接，开始并行分析...")

    # 并行提交所有视频处理任务
    futures = {
        _executor.submit(_process_single_video, url, i, len(urls), mbti, share_text, city, catalog): i
        for i, url in enumerate(urls)
    }

    # 收集结果（按完成顺序）
    results = [None] * len(urls)
    for future in as_completed(futures):
        try:
            result = future.result()
            results[result["index"]] = result
        except Exception as e:
            idx = futures[future]
            logger.error(f"视频 {idx+1} 处理异常: {e}")
            results[idx] = {
                "index": idx, "success": False, "url": urls[idx],
                "title": "", "transcript": None, "locations": [],
                "error": f"处理异常: {str(e)}",
            }

    # 汇总结果
    all_locations = []
    transcripts = []
    errors = []

    for r in results:
        if r is None:
            continue
        if r["success"]:
            transcripts.append({"url": r["url"], "title": r["title"], "text": r["transcript"], "mode": r.get("mode")})
            all_locations.extend(r["locations"])
        else:
            errors.append({"url": r["url"], "error": r["error"]})

    # 去重（按景点名称）
    seen = set()
    unique_locations = []
    for loc in all_locations:
        key = loc["name"].strip().lower()
        if key not in seen:
            seen.add(key)
            unique_locations.append(loc)

    logger.info(f"分析完成：{len(transcripts)}/{len(urls)} 个视频成功，提取 {len(unique_locations)} 个景点")

    # 持久化到数据库（作为预备默认景点）
    saved_count = _save_locations_to_db(unique_locations)
    if saved_count > 0:
        logger.info(f"已将 {saved_count} 个新景点写入数据库")

    return jsonify({
        "locations": unique_locations,
        "transcripts": transcripts,
        "summary": f"从 {len(urls)} 个视频中提取了 {len(unique_locations)} 个景点",
        "video_count": len(urls),
        "success_count": len(transcripts),
        "total_locations": len(unique_locations),
        "errors": errors,
        "asr": Config.HAS_ASR,
    })


@video_bp.route("/transcribe", methods=["POST"])
@login_required
def transcribe_single():
    """
    单个视频转写（用于实时进度展示）

    请求体：{ "url": "https://v.douyin.com/xxxxx" }
    """
    data = request.get_json()
    if not data or not data.get("url"):
        return jsonify({"error": "请提供视频链接"}), 400

    url = data["url"].strip()
    if not is_allowed_video_url(url):
        return jsonify({"error": "仅支持抖音视频链接（douyin.com / iesdouyin.com）"}), 400
    transcript, video_title, err_msg = _transcribe_video(url)

    if not transcript:
        return jsonify({"error": err_msg or "语音转写失败", "url": url}), 500

    return jsonify({
        "url": url,
        "title": video_title,
        "transcript": transcript,
    })


def _call_mcporter(tool: str, args: dict, timeout: int = 120) -> tuple[dict | str | None, str]:
    """
    调用 mcporter CLI 执行 MCP 工具

    Args:
        tool: 工具名，如 "douyin.parse_douyin_video_info"
        args: 参数字典
        timeout: 超时秒数

    Returns:
        (result, error_msg) — 成功时 (parsed_data, "")，失败时 (None, error_message)
    """
    # mcporter 配置文件路径
    import os
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "mcporter.json")

    # mcporter --timeout 接收毫秒，Python timeout 接收秒
    mcporter_timeout_ms = str(timeout * 1000)

    cmd = ["mcporter", "--config", config_path, "call", tool, "--timeout", mcporter_timeout_ms]
    for k, v in args.items():
        cmd.append(f"{k}={v}")

    try:
        logger.info(f"[mcporter] calling: {tool}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # mcporter 输出格式：JSON 包含 "result" 字段（字符串化的工具返回值）
        output = result.stdout.strip()

        # 先检查 stderr 是否有错误信息
        stderr_text = result.stderr.strip()
        if stderr_text:
            logger.warning(f"[mcporter] stderr: {stderr_text}")

        if result.returncode != 0 and not output:
            return None, stderr_text or f"mcporter 退出码: {result.returncode}"

        if not output:
            return None, stderr_text or "mcporter 无输出"

        # 解析 mcporter 的 JSON 包装
        parsed = json.loads(output)

        # mcporter 返回 {"result": "..."} 格式
        if isinstance(parsed, dict) and "result" in parsed:
            inner = parsed["result"]

            # 检查是否是错误响应
            if isinstance(inner, dict) and inner.get("status") == "error":
                error_msg = inner.get("error", "未知错误")
                logger.error(f"[mcporter] tool error: {error_msg}")
                return None, error_msg

            if isinstance(inner, str):
                # 检查是否是错误消息
                try:
                    inner_parsed = json.loads(inner)
                    if isinstance(inner_parsed, dict) and inner_parsed.get("status") == "error":
                        error_msg = inner_parsed.get("error", "未知错误")
                        logger.error(f"[mcporter] tool error: {error_msg}")
                        return None, error_msg
                    return inner_parsed, ""
                except json.JSONDecodeError:
                    return inner, ""  # 非 JSON 字符串（如转写文本）
            return inner, ""

        return parsed, ""

    except subprocess.TimeoutExpired:
        error_msg = f"处理超时（{timeout}秒），视频可能过大或网络不稳定"
        logger.error(f"[mcporter] {error_msg}")
        return None, error_msg
    except json.JSONDecodeError as e:
        error_msg = f"解析返回数据失败: {e}"
        logger.error(f"[mcporter] {error_msg}")
        return None, error_msg
    except Exception as e:
        error_msg = f"调用失败: {e}"
        logger.error(f"[mcporter] {error_msg}")
        return None, error_msg


def _transcribe_video(url: str) -> tuple[str | None, str, str]:
    """
    对视频进行语音转写（切片并行处理）

    Returns:
        (transcript_text, video_title, error_msg) — 转写失败时 (None, "", error_msg)
    """
    try:
        from backend.services.video_processor import VideoProcessor
        processor = VideoProcessor()
        transcript, video_title, err_msg = processor.process_video(url)
        if transcript:
            return transcript, video_title, ""

        logger.warning(f"[VideoProcessor] 主流程失败，降级到 mcporter: {err_msg}")
        fallback_text, fallback_title, fallback_err = _transcribe_video_mcporter(url)
        if fallback_text:
            return fallback_text, fallback_title or video_title, ""

        errors = []
        if err_msg:
            errors.append(f"主流程失败: {err_msg}")
        if fallback_err:
            errors.append(f"降级失败: {fallback_err}")
        return None, video_title or fallback_title, "；".join(errors) or "语音转写失败"
    except ImportError as e:
        logger.warning(f"[VideoProcessor] 导入失败，降级到 mcporter: {e}")
        return _transcribe_video_mcporter(url)
    except Exception as e:
        logger.error(f"[VideoProcessor] 处理异常，降级到 mcporter: {e}")
        fallback_text, fallback_title, fallback_err = _transcribe_video_mcporter(url)
        if fallback_text:
            return fallback_text, fallback_title, ""
        return None, fallback_title, f"主流程异常: {e}；降级失败: {fallback_err}"


def _transcribe_video_mcporter(url: str) -> tuple[str | None, str, str]:
    """
    降级方案：通过 mcporter 调用（串行处理）
    """
    # 先解析视频信息获取标题
    info, err = _call_mcporter("douyin.parse_douyin_video_info", {"share_link": url}, timeout=30)
    video_title = ""
    if info and isinstance(info, dict):
        if info.get("status") == "success":
            video_title = info.get("title", "")
        elif info.get("status") == "error":
            return None, "", info.get("error", "视频解析失败")

    if err and not info:
        return None, "", f"视频解析失败: {err}"

    # 语音转写
    result, err2 = _call_mcporter("douyin.extract_douyin_text", {"share_link": url}, timeout=300)

    if err2 and not result:
        return None, video_title, f"语音转写失败: {err2}"

    if result and isinstance(result, str) and len(result) > 10:
        return result, video_title, ""

    if result and isinstance(result, dict):
        text = result.get("text", "") or result.get("content", "")
        if text and len(text) > 10:
            return text, video_title, ""

    return None, video_title, "未能从视频中提取到有效文本"


def _extract_locations_from_text(transcript: str, video_title: str, mbti: str) -> list:
    """
    使用 LLM 从转写文本中提取具体可到访地点，并做后置过滤
    """
    from backend.services.llm_service import chat_completion, enrich_locations_travel_style_fit

    # 不截断文本，完整送入 LLM
    rule_locations = _extract_locations_with_rules(transcript, video_title, mbti)

    prompt = f"""你是一个旅行信息提取专家。请从以下抖音旅行视频的语音转写文本中，提取**明确、具体、可到访**的地点。

## 视频标题
{video_title}

## 转写文本
{transcript}

## 提取规则（非常重要，请严格遵守）

1. **只提取明确具体地点**：地点名必须在标题或转写文本中明确出现，且是用户能真实前往的景点、街道、建筑、店铺、展馆、公园、码头等。

2. **不要过度识别**：以下内容不要作为地点输出：
   - 城市/行政区/区域泛称：上海、浦东、浦西、黄浦区、市中心、附近、周边
   - 交通和住宿泛称：地铁、地铁站、公交站、机场、酒店、民宿、住处
   - 普通品类词：餐厅、咖啡店、小店、商场、景点、打卡点、机位
   - 文本没有直接说出的推测地点；不要因为“外滩夜景”就额外脑补一串周边地点

3. **粒度原则**：
   - "陆家嘴三件套"→ 可提取"陆家嘴"，以及文本明确围绕三件套介绍时的"上海环球金融中心""金茂大厦""上海中心大厦"
   - "武康路、安福路漫步"→ 分别提取"武康路"和"安福路"
   - "乍浦路桥上能拍到外白渡桥和东方明珠"→ 提取"乍浦路桥"，也可提取被明确提到的"外白渡桥""东方明珠"

4. **坐标处理**：上海知名景点尽量给出经纬度，不确定的写 null（系统会自动补全）

5. **reason 写法**：用一句话概括博主对这个地方说了什么，不要泛泛而谈

## 输出格式

严格输出 JSON 数组，不要任何其他文字。每个元素格式：
```json
{{
  "name": "地点名称",
  "type": "landmark|street|food|culture",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "reason": "博主对这个地点的一句话描述",
  "lat": 31.2400,
  "lng": 121.4900
}}
```

type 分类说明：
- landmark：地标建筑、景点、桥梁、广场
- street：街道、路名、步行街、弄堂
- food：餐厅、咖啡馆、小吃街、美食
- culture：博物馆、美术馆、书店、寺庙、文创空间

现在请提取："""

    messages = [
        {
            "role": "system",
            "content": (
                "你是旅行信息提取专家。你的任务是从语音转写文本中提取明确具体、可到访的地点。"
                "原则：宁可少一点，也不要把城市、区域、交通、住宿、普通品类词或推测地点误识别成景点。"
                "只输出 JSON 数组，不要任何其他文字或解释。"
            ),
        },
        {"role": "user", "content": prompt},
    ]

    # mimo-v2.5-pro 需要较多 tokens 用于 reasoning，必须给够
    # 全量提取场景下可能产出 20+ 景点，给足 8000 tokens
    result = chat_completion(messages, temperature=0.3, max_tokens=8000)

    source_text = f"{video_title}\n{transcript}"
    if not result:
        logger.warning("LLM 提取地点失败，使用本地规则兜底")
        return _filter_extracted_locations(rule_locations, source_text)

    try:
        # 提取 JSON
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]

        # 尝试解析，如果失败则尝试修复截断的 JSON
        try:
            locations = json.loads(result.strip())
        except json.JSONDecodeError:
            # 尝试修复截断的 JSON：找到最后一个完整的 } 并闭合数组
            fixed = _repair_truncated_json(result.strip())
            locations = json.loads(fixed)

        if not isinstance(locations, list):
            return []

        # 为每个景点添加 MBTI 标签
        for loc in locations:
            if not isinstance(loc, dict) or not loc.get("name"):
                continue
            base_labels = loc.get("keywords", [])[:3]
            loc["labels"] = _match_labels(base_labels, mbti)
            loc["source"] = loc.get("source") or "video"

        source_text = f"{video_title}\n{transcript}"
        locations = [loc for loc in locations if isinstance(loc, dict) and loc.get("name")]
        locations = _merge_locations(locations, rule_locations)
        locations = _filter_extracted_locations(locations, source_text)
        return enrich_locations_travel_style_fit(locations, video_title=video_title)

    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"LLM 提取结果解析失败: {e}")
        return _filter_extracted_locations(rule_locations, f"{video_title}\n{transcript}")


def _merge_locations(primary: list, fallback: list) -> list:
    """按名称合并 LLM 和规则提取结果，保留 LLM 的描述优先级。"""
    merged = []
    seen = set()
    for loc in primary + fallback:
        if not isinstance(loc, dict) or not loc.get("name"):
            continue
        key = loc["name"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(loc)
    return merged


def _normalize_extracted_location_name(name: str) -> str:
    """标准化 LLM 返回的地点名称，去掉常见装饰符号。"""
    if not isinstance(name, str):
        return ""
    return re.sub(r"[\s·・,，。；;：:（）()【】\[\]{}<>《》\"'“”‘’]+", "", name).strip()


def _source_mentions_location(name: str, source_text: str) -> bool:
    """判断地点是否在标题或转写文本中有明确证据。"""
    normalized_name = _normalize_extracted_location_name(name)
    normalized_source = _normalize_extracted_location_name(source_text)
    if not normalized_name or not normalized_source:
        return False
    if normalized_name in normalized_source:
        return True
    for alias in _INFERRED_LOCATION_ALIASES.get(name, ()):  # 允许少量明确别名/集合表达
        if _normalize_extracted_location_name(alias) in normalized_source:
            return True
    return False


def _is_generic_location_name(name: str) -> bool:
    """过滤城市、行政区、泛称、交通住宿等不适合作为游玩点的名称。"""
    normalized_name = _normalize_extracted_location_name(name)
    if not normalized_name:
        return True
    if normalized_name in _GENERIC_LOCATION_NAMES:
        return True
    if len(normalized_name) <= 1:
        return True
    if len(normalized_name) <= 3 and normalized_name.endswith(_GENERIC_LOCATION_SUFFIXES):
        return True
    if any(word in normalized_name for word in ("附近", "周边", "旁边", "对面", "入口", "出口")):
        return True
    if normalized_name.endswith(("站", "机场", "酒店", "民宿")) and normalized_name not in _SHANGHAI_COORD_FALLBACK:
        return True
    return False


def _looks_like_specific_place(name: str, loc: dict) -> bool:
    """判断名称是否像一个具体可到访地点。"""
    normalized_name = _normalize_extracted_location_name(name)
    if normalized_name in _SHANGHAI_COORD_FALLBACK:
        return True
    if normalized_name.endswith(_NAMED_PLACE_SUFFIXES):
        return True
    keywords = " ".join(loc.get("keywords") or loc.get("tags") or [])
    if any(word in keywords for word in ("美食", "咖啡", "面馆", "餐厅", "展览", "拍照", "citywalk")):
        return True
    return len(normalized_name) >= 4


def _filter_extracted_locations(locations: list, source_text: str, max_locations: int = 15) -> list:
    """对 LLM/规则提取结果做后置过滤，降低过度识别。"""
    filtered = []
    seen = set()
    dropped = []

    for loc in locations:
        if not isinstance(loc, dict):
            continue
        name = (loc.get("name") or "").strip()
        normalized_name = _normalize_extracted_location_name(name).lower()
        if not name or normalized_name in seen:
            continue

        drop_reason = ""
        if _is_generic_location_name(name):
            drop_reason = "generic"
        elif not _source_mentions_location(name, source_text):
            drop_reason = "not_in_transcript"
        elif not _looks_like_specific_place(name, loc):
            drop_reason = "not_specific_place"

        if drop_reason:
            dropped.append(f"{name}:{drop_reason}")
            continue

        seen.add(normalized_name)
        filtered.append(loc)
        if len(filtered) >= max_locations:
            break

    if dropped:
        logger.info("视频地点过滤丢弃 %s", ", ".join(dropped[:12]))
    return filtered


def _extract_locations_with_rules(transcript: str, video_title: str, mbti: str) -> list:
    """
    LLM 不可用或超时时的本地兜底：从标题和转写文本里匹配常见上海地点。
    这不是替代 LLM，而是避免"转写成功但地点为空"。
    """
    text = f"{video_title}\n{transcript}"
    if not text.strip():
        return []

    hints = {
        "陆家嘴三件套": {"type": "landmark", "keywords": ["天际线", "地标", "拍照"]},
        "上海博物馆东馆": {"type": "culture", "keywords": ["博物馆", "展厅", "文化"]},
        "上博东馆": {"alias": "上海博物馆东馆", "type": "culture", "keywords": ["博物馆", "展厅", "文化"]},
        "北外滩小巨蛋": {"type": "landmark", "keywords": ["北外滩", "东方明珠", "拍照"]},
        "泰公线轮渡": {"type": "landmark", "keywords": ["轮渡", "黄浦江", "2元"]},
        "泰公线": {"alias": "泰公线轮渡", "type": "landmark", "keywords": ["轮渡", "黄浦江", "2元"]},
        "沪西老弄堂面馆": {"type": "food", "keywords": ["面馆", "本地美食", "蛤蜊猪肝"]},
        "味香斋": {"type": "food", "keywords": ["芝麻酱拌面", "本地美食", "老字号"]},
        "PAOPAO": {"type": "food", "keywords": ["蛋糕", "甜品", "拍照"]},
        "AMAN LONBAKERY TOWN": {"type": "food", "keywords": ["面包", "甜品", "小狗面包"]},
    }

    candidate_names = set(_SHANGHAI_COORD_FALLBACK.keys()) | set(hints.keys())
    matches = []
    for name in candidate_names:
        flags = re.IGNORECASE if name.isascii() else 0
        for match in re.finditer(re.escape(name), text, flags):
            matches.append((match.start(), match.end(), name))

    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected = []
    spans = []
    seen = set()
    for start, end, raw_name in matches:
        hint = hints.get(raw_name, {})
        name = hint.get("alias", raw_name)
        key = name.lower()
        if key in seen:
            continue
        if any(start >= s and end <= e for s, e, _ in spans):
            continue
        spans.append((start, end, name))
        seen.add(key)

        keywords = hint.get("keywords") or _keywords_for_rule_location(name)
        loc_type = hint.get("type") or _infer_type_from_keywords(keywords)
        lat, lng = (None, None)
        if name in _SHANGHAI_COORD_FALLBACK:
            lat, lng = _SHANGHAI_COORD_FALLBACK[name]
        elif raw_name in _SHANGHAI_COORD_FALLBACK:
            lat, lng = _SHANGHAI_COORD_FALLBACK[raw_name]

        selected.append({
            "name": name,
            "type": loc_type,
            "keywords": keywords,
            "reason": "视频标题或转写文本中明确提到了这个地点。",
            "lat": lat,
            "lng": lng,
            "labels": _match_labels(keywords[:3], mbti),
            "source": "video",
        })

    return selected


def _keywords_for_rule_location(name: str) -> list:
    if any(word in name for word in ["面", "斋", "PAOPAO", "BAKERY", "蛋糕", "咖啡"]):
        return ["美食", "探店", "本地推荐"]
    if any(word in name for word in ["路", "街", "南京", "淮海", "新天地"]):
        return ["citywalk", "街区", "逛吃"]
    if any(word in name for word in ["博物馆", "寺", "美术馆", "书店"]):
        return ["文化", "展览", "室内"]
    if any(word in name for word in ["轮渡", "桥", "外滩", "陆家嘴", "东方明珠"]):
        return ["地标", "拍照", "夜景"]
    return ["景点", "打卡", "旅行"]


def _repair_truncated_json(text: str) -> str:
    """
    修复被截断的 JSON 数组
    找到最后一个完整的 } 并闭合数组
    """
    # 找到最后一个 } 的位置
    last_brace = text.rfind("}")
    if last_brace == -1:
        raise ValueError("无法修复 JSON")

    # 截取到最后一个 } 之后
    truncated = text[:last_brace + 1]

    # 检查是否有未闭合的引号
    in_string = False
    escape_next = False
    for i, c in enumerate(truncated):
        if escape_next:
            escape_next = False
            continue
        if c == "\\":
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string

    # 如果在字符串中间截断，移除不完整的部分
    if in_string:
        # 找到最后一个完整字符串的结束位置
        last_quote = truncated.rfind('"')
        if last_quote > 0:
            truncated = truncated[:last_quote]
            # 确保最后是 } 或 ]
            truncated = truncated.rstrip() + "\n  }"

    # 闭合数组
    return truncated + "\n]"


def _match_labels(base_labels: list, mbti: str) -> list:
    """
    根据用户MBTI人格类型，匹配额外的个性化label
    """
    labels = list(base_labels)

    if not mbti or len(mbti) < 4:
        return labels

    # D=记录表达型 / I=沉浸感受型
    if mbti[0] == "D":
        labels.append("📸 拍照友好")
    else:
        labels.append("🧘 沉浸体验")

    # R=精致风格型 / L=本地烟火型
    if mbti[1] == "R":
        labels.append("✨ 精致推荐")
    else:
        labels.append("🏠 本地风味")

    # P=计划依赖型 / F=灵感优先型
    if mbti[2] == "P":
        labels.append("📋 经典路线")
    else:
        labels.append("🎲 随性探索")

    # C=覆盖打卡型 / S=深度停留型
    if mbti[3] == "C":
        labels.append("✅ 必打卡")
    else:
        labels.append("⏳ 值得停留")

    return labels


# 上海常见地名坐标兜底（LLM 未给坐标时自动补全）
_SHANGHAI_COORD_FALLBACK = {
    # 经典地标
    "外滩": (31.2400, 121.4900),
    "东方明珠": (31.2397, 121.4998),
    "陆家嘴": (31.2353, 121.4990),
    "上海环球金融中心": (31.2360, 121.5015),
    "金茂大厦": (31.2357, 121.5005),
    "上海中心大厦": (31.2335, 121.5010),
    "上海金茂大厦": (31.2357, 121.5005),
    "武康大楼": (31.2097, 121.4367),
    "静安寺": (31.2230, 121.4480),
    "豫园": (31.2270, 121.4920),
    "城隍庙": (31.2270, 121.4920),
    "新天地": (31.2165, 121.4735),
    "田子坊": (31.2105, 121.4680),
    "和平饭店": (31.2405, 121.4905),
    "南京路步行街": (31.2350, 121.4740),
    "南京路": (31.2350, 121.4740),
    "南京东路": (31.2350, 121.4740),
    "淮海中路": (31.2150, 121.4530),
    "人民广场": (31.2310, 121.4700),
    # 街道/路名
    "武康路": (31.2100, 121.4370),
    "安福路": (31.2085, 121.4389),
    "乌鲁木齐中路": (31.2115, 121.4401),
    "东平路": (31.2130, 121.4450),
    "衡山路": (31.2100, 121.4450),
    "愚园路": (31.2220, 121.4270),
    "甜爱路": (31.2600, 121.4800),
    "多伦路": (31.2530, 121.4810),
    "永康路": (31.2180, 121.4480),
    "利西路": (31.2150, 121.4350),
    # 桥梁
    "外白渡桥": (31.2440, 121.4900),
    "乍浦路桥": (31.2430, 121.4870),
    # 博物馆/文化
    "上海博物馆": (31.2280, 121.4700),
    "上海博物馆东馆": (31.2130, 121.5050),
    "上海邮政博物馆": (31.2440, 121.4860),
    "1933老场坊": (31.2550, 121.4840),
    "M50创意园": (31.2520, 121.4590),
    "油罐艺术公园": (31.1530, 121.4680),
    # 商圈/商场
    "白玉兰广场": (31.2470, 121.4930),
    "环球港": (31.2370, 121.4150),
    "徐汇滨江": (31.1600, 121.4620),
    "北外滩": (31.2500, 121.4950),
    "外滩观景平台": (31.2400, 121.4900),
    # 寺庙/宗教
    "玉佛寺": (31.2410, 121.4450),
    "龙华寺": (31.1770, 121.4510),
    # 公园
    "世纪公园": (31.2100, 121.5440),
    "共青森林公园": (31.3050, 121.5350),
    "嘉定秋霞圃": (31.3850, 121.2500),
    # 渡轮/交通
    "东昌路渡轮码头": (31.2350, 121.5050),
    "太古线轮渡": (31.2400, 121.5000),
    "上海站": (31.2530, 121.4570),
    "上海火车站": (31.2530, 121.4570),
    "虹桥站": (31.1940, 121.3300),
    # 其他
    "思南公馆": (31.2135, 121.4695),
    "哥伦比亚公园": (31.2200, 121.4180),
    "苏州河": (31.2450, 121.4700),
    "黄浦江": (31.2350, 121.4900),
    "杨浦滨江": (31.2600, 121.5300),
    "徐汇滨江绿道": (31.1600, 121.4620),
    "多伦路文化名人街": (31.2530, 121.4810),
    "东昌路": (31.2350, 121.5050),
}


def _fill_coords(name: str, lat, lng):
    """如果坐标为空，从兜底表中补全；仍无则用上海市中心默认值"""
    if lat is not None and lng is not None:
        return lat, lng

    # 精确匹配
    if name in _SHANGHAI_COORD_FALLBACK:
        return _SHANGHAI_COORD_FALLBACK[name]

    # 模糊匹配：名称包含关系
    name_lower = name.lower()
    for key, coords in _SHANGHAI_COORD_FALLBACK.items():
        if key in name or name in key:
            return coords

    # 查不到就如实返回空，交给前端用地图搜索定位，而不是编造一个市中心坐标
    return None, None


def _infer_type_from_keywords(keywords: list) -> str:
    """根据关键词推断景点类型（匹配 attractions 表的 CHECK 约束）"""
    text = " ".join(keywords).lower()
    if any(w in text for w in ["吃", "餐", "美食", "小吃", "咖啡", "冰淇淋", "面", "包"]):
        return "food"
    if any(w in text for w in ["街", "路", "弄", "巷", "步行街", "商业"]):
        return "street"
    if any(w in text for w in ["馆", "院", "寺", "园", "庙", "博物馆", "故居", "文化"]):
        return "culture"
    return "landmark"


def _save_locations_to_db(locations: list) -> int:
    """
    将视频提取的景点持久化到 attractions 表
    使用 INSERT OR IGNORE 避免重复（UNIQUE name+city 约束）
    返回实际新增的条数
    """
    from backend.database import get_db

    if not locations:
        return 0

    db = get_db()
    saved = 0
    try:
        for loc in locations:
            name = (loc.get("name") or "").strip()
            if not name:
                continue

            # 坐标补全：LLM 给了就用，没给就从兜底表查，再没有就用上海市中心
            lat, lng = _fill_coords(name, loc.get("lat"), loc.get("lng"))
            if lat is None or lng is None:
                continue

            keywords = loc.get("keywords", [])
            # 优先用 LLM 给的 type，没有则从关键词推断
            raw_type = (loc.get("type") or "").strip().lower()
            if raw_type in ("landmark", "street", "food", "culture"):
                loc_type = raw_type
            else:
                loc_type = _infer_type_from_keywords(keywords)

            try:
                cursor = db.execute(
                    """INSERT OR IGNORE INTO attractions
                       (name, city, type, category, description, address,
                        lat, lng, tags, crowd_level, cost_level, duration_min,
                        best_time, suitable_for, personality_fit, tips, risks)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        name,
                        "上海",
                        loc_type,
                        "视频推荐",
                        loc.get("reason", ""),
                        "",
                        lat,
                        lng,
                        json.dumps(keywords, ensure_ascii=False),
                        "medium",
                        "中等",
                        60,
                        "全天",
                        json.dumps([], ensure_ascii=False),
                        json.dumps(loc.get("travel_style_fit", {}), ensure_ascii=False),
                        "",
                        "",
                    ),
                )
                if cursor.rowcount > 0:
                    saved += 1
            except Exception as e:
                logger.warning(f"保存景点 [{name}] 失败: {e}")

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"批量保存景点失败: {e}")
    finally:
        db.close()

    return saved
