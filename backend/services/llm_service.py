"""
LLM 服务 - 封装与大语言模型的交互
· OpenAI 兼容接口（默认 DeepSeek deepseek-flash；也支持 OpenAI / 通义千问 / Kimi / 本地 Ollama 等）
· 豆包 (Doubao / 火山方舟 Ark) Responses API（自带联网搜索，可选）
· 没有 Key 或调用失败时返回空，由调用方改用本地能力（行程引擎 / 本地助手 / 规则识别）
"""

import json
import logging
import re
import time
import requests
from openai import OpenAI
from backend.config import Config

logger = logging.getLogger(__name__)

_TRAVEL_STYLE_FIT_SCHEMA = {
    "pace": {"any", "rush", "slow"},
    "pref": {"any", "classic", "hidden"},
    "exp": {"any", "scene", "food"},
    "social": {"any", "social", "solo"},
}

# 初始化 LLM 客户端
client = None
if Config.HAS_LLM:
    client = OpenAI(
        api_key=Config.LLM_API_KEY,
        base_url=Config.LLM_BASE_URL,
        timeout=Config.LLM_TIMEOUT,
        max_retries=Config.LLM_MAX_RETRIES,
    )


# ---------------------------------------------------------------- 熔断 ----
# Key 写错 / 服务不可达时，每次调用都会等到超时（几十秒），整个应用像卡死一样。
# 连续失败后在冷却期内直接跳过远程调用，走本地规则引擎，过后自动重试。
_BREAKER = {"llm": 0.0, "doubao": 0.0}
_COOLDOWN_SECONDS = 180


def _available(name: str) -> bool:
    return time.time() >= _BREAKER[name]


def _trip(name: str, err) -> None:
    _BREAKER[name] = time.time() + _COOLDOWN_SECONDS
    logger.warning("%s 调用失败，%d 秒内改用本地能力：%s", name, _COOLDOWN_SECONDS, err)


def _reset(name: str) -> None:
    _BREAKER[name] = 0.0


def llm_status() -> dict:
    """供 /api/health、/api/config 展示当前 AI 能力是否可用"""
    from backend.services import asr

    llm_ok = Config.HAS_LLM and _available("llm")
    return {
        "llm": llm_ok,
        "web_search": Config.HAS_WEB_SEARCH and (llm_ok or (Config.HAS_DOUBAO and _available("doubao"))),
        "vision": Config.HAS_VISION and llm_ok,
        "asr": asr.status()["ready"],
        "asr_engine": asr.status(),
    }


def _extract_responses_text(data: dict) -> str:
    """从 Responses API 返回中提取文本内容"""
    if not isinstance(data, dict):
        return ""

    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str) and text:
                chunks.append(text)

    return "".join(chunks).strip()


def _extract_responses_stream_text(text: str) -> str:
    """从 Responses API SSE 事件流中提取文本内容"""
    if not text:
        return ""

    chunks = []
    completed_text = ""
    for block in text.split("\n\n"):
        data_lines = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if not data_lines:
            continue
        raw = "\n".join(data_lines).strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")
        if event_type == "response.output_text.delta" and event.get("delta"):
            chunks.append(event["delta"])
        elif event_type == "response.completed":
            completed_text = _extract_responses_text(event.get("response", {}))

        for choice in event.get("choices") or []:
            delta = (choice.get("delta") or {}).get("content")
            if delta:
                chunks.append(delta)

    text_from_deltas = "".join(chunks).strip()
    return text_from_deltas or completed_text.strip()


def _call_openai_responses(prompt: str, use_web_search: bool = False, model: str = None) -> str:
    """调用 OpenAI 兼容 Responses API，可选 live web_search 工具"""
    if not Config.HAS_LLM or not _available("llm"):
        return ""

    url = f"{Config.LLM_BASE_URL.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {Config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or Config.LLM_MODEL,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "stream": True,
    }

    if use_web_search:
        payload["tools"] = [{"type": "web_search"}]

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=Config.LLM_TIMEOUT)
        resp.raise_for_status()
        response_text = resp.content.decode("utf-8", "replace")
        text = _extract_responses_stream_text(response_text)
        if text:
            _reset("llm")
            return text
        logger.warning("OpenAI Responses API returned no text")
        return ""
    except Exception as e:
        _trip("llm", e)
        return ""


def _call_doubao_responses(prompt: str, use_web_search: bool = False) -> str:
    """
    调用豆包 (火山方舟 Ark) Responses API
    use_web_search=True 时启用联网搜索工具
    """
    if not Config.HAS_DOUBAO or not _available("doubao"):
        return ""

    url = f"{Config.DOUBAO_BASE_URL}/responses"
    headers = {
        "Authorization": f"Bearer {Config.DOUBAO_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": Config.DOUBAO_MODEL,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
    }

    if use_web_search:
        payload["tools"] = [{"type": "web_search"}]

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        # 从 Responses API 返回中提取文本
        output_text = ""
        for item in data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text += content.get("text", "")

        _reset("doubao")
        return output_text.strip()
    except Exception as e:
        _trip("doubao", e)
        return ""


def parse_json(text: str):
    """从模型回复里解析 JSON（对象或数组）：容忍代码块围栏、前后说明文字、被截断的数组"""
    if not text:
        return None
    text = text.strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                continue
    # 输出被截断：保留最后一个完整对象，补齐括号
    i = text.find("[")
    k = text.rfind("}")
    if 0 <= i < k:
        head = text[:i]
        body = text[i:k + 1] + "]"
        closing = "}" * (head.count("{") - head.count("}"))
        try:
            return json.loads(head + body + closing)
        except json.JSONDecodeError:
            return None
    return None


def _extract_json_array(text: str):
    """解析模型返回的数组；也接受 {"places": [...]} 这类被包在对象里的数组（JSON 模式只能输出对象）"""
    data = parse_json(text)
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), None)
    return data if isinstance(data, list) else None


def _normalize_travel_style_fit(raw_fit: dict) -> dict:
    """清洗并标准化地点的人格匹配字段"""
    if not isinstance(raw_fit, dict):
        return {}

    normalized = {}
    for key, allowed_values in _TRAVEL_STYLE_FIT_SCHEMA.items():
        value = raw_fit.get(key)
        if isinstance(value, str):
            value = value.strip().lower()
            if value in allowed_values:
                normalized[key] = value

    return normalized


def _has_structured_travel_style_fit(fit: dict) -> bool:
    """判断地点是否已有可用的人格匹配字段"""
    return bool(_normalize_travel_style_fit(fit))


def enrich_locations_travel_style_fit(locations: list, video_title: str = "") -> list:
    """使用现有 LLM 能力为视频提取景点补全 travel_style_fit"""
    if not locations:
        return locations

    targets = []
    for loc in locations:
        if not isinstance(loc, dict) or not loc.get("name"):
            continue

        existing_fit = loc.get("travel_style_fit") or loc.get("personality_fit") or {}
        normalized_fit = _normalize_travel_style_fit(existing_fit)
        if normalized_fit:
            loc["travel_style_fit"] = normalized_fit
        else:
            targets.append(loc)

    if not targets:
        return locations

    location_payload = [
        {
            "name": loc.get("name", ""),
            "type": loc.get("type", ""),
            "keywords": loc.get("keywords") or loc.get("tags") or [],
            "reason": loc.get("reason") or loc.get("description") or "",
        }
        for loc in targets
    ]

    prompt = f"""你是一名旅行人格匹配标注专家。请根据地点名称、类型、关键词和视频描述，为每个地点补全 travel_style_fit。

## 视频标题
{video_title or "未知"}

## 待标注地点
{json.dumps(location_payload, ensure_ascii=False, indent=2)}

## 字段含义与合法值
- pace: rush=适合高效打卡/快速覆盖，slow=适合慢逛沉浸，any=两者皆可
- pref: classic=经典知名/稳定出片，hidden=本地烟火/小众隐藏，any=两者皆可
- exp: scene=偏景观/建筑/展馆/路线体验，food=偏美食/咖啡/探店，any=两者皆可
- social: social=适合结伴互动/多人同行，solo=适合独处深度停留，any=两者皆可

这些字段用于匹配新版旅行人格：D/I + R/L + P/S + C/T。
其中 P 更匹配 scene，S 更匹配 food；C 更匹配 social，T 更匹配 solo。

只输出 JSON 数组，不要输出任何其他文字。数组元素格式如下：
[
  {{
    "name": "地点名，必须和输入完全一致",
    "travel_style_fit": {{
      "pace": "rush|slow|any",
      "pref": "classic|hidden|any",
      "exp": "scene|food|any",
      "social": "social|solo|any"
    }}
  }}
]"""

    messages = [
        {"role": "system", "content": "你只输出合法 JSON 数组，不要解释、不要 Markdown。"},
        {"role": "user", "content": prompt},
    ]
    result = chat_completion(messages, temperature=0.2, max_tokens=3000, json_mode=True)

    if not result:
        result = _call_doubao_responses(prompt, use_web_search=False)

    enriched = _extract_json_array(result)
    if not enriched:
        logger.warning("enrich_locations_travel_style_fit: 无法解析 LLM 返回，保留原始地点")
        return locations

    fits_by_name = {}
    for item in enriched:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        fit = _normalize_travel_style_fit(item.get("travel_style_fit", {}))
        if name and fit:
            fits_by_name[name] = fit

    for loc in targets:
        name = (loc.get("name") or "").strip()
        if name in fits_by_name:
            loc["travel_style_fit"] = fits_by_name[name]

    return locations


def filter_default_attractions(profile: dict, attractions: list) -> list:
    """
    根据用户旅行风格偏好筛选推荐景点（豆包）
    返回筛选后的景点列表，每个景点带 selected 和 reason 字段
    """
    if not attractions:
        return attractions

    names = [a["name"] for a in attractions]

    # 优先使用旅行风格主画像测试结果中的「画像描述文本」（来自 MBTI 主画像 description 字段），
    # 把这段第一人称的画像描述原文发给豆包，让模型基于这段文字真正理解用户的旅行风格，
    # 而不是仅凭几个标签做粗略匹配；若没有画像描述，则退化为 JSON 画像或通用提示。
    persona_name = (profile.get("personality_name") or "").strip()
    persona_desc = (profile.get("description") or "").strip()
    style_labels = [
        profile.get(k) for k in ("di_label", "rl_label", "ps_label", "cd_label") if profile.get(k)
    ]

    if persona_desc:
        profile_text = f"用户的旅行人格主画像：{persona_name or '未知'}\n画像描述原文：\n{persona_desc}"
        if style_labels:
            profile_text += f"\n风格标签：{' / '.join(style_labels)}"
    elif profile:
        profile_text = json.dumps(profile, ensure_ascii=False, indent=2)
    else:
        profile_text = "（暂无用户旅行风格主画像，请凭常识推荐适合大众的景点）"

    prompt = f"""你是一名专业的旅行顾问。下面是某位用户的旅行风格主画像测试结果：
{profile_text}

候选景点列表：{json.dumps(names, ensure_ascii=False)}

请仔细阅读上面这段旅行风格主画像描述，并据此从候选景点中挑选出最符合该用户偏好的景点
（可以是部分，也可以是全部或一个都不选），
并为每个被选中的景点生成一句简短、有针对性的推荐理由（20-40字以内，需要结合画像描述中的具体特征来说明为什么适合TA，而不要泛泛而谈）。

只输出一个 JSON 数组，不要输出任何其他文字、解释或代码块标记。数组中每个元素是一个对象，格式为：
{{"name": "候选景点列表中原始的名称字符串", "reason": "推荐理由"}}
例如：[{{"name": "外滩", "reason": "夜景与建筑群很适合喜欢拍照记录的你，沿江漫步也契合悠闲节奏"}}, {{"name": "豫园", "reason": "古典园林与小吃街区满足你对本地烟火气和文化体验的偏好"}}]"""

    result = chat_completion([
        {"role": "system", "content": "你是专业旅行顾问。只输出合法 JSON 数组，不要解释、不要 Markdown。"},
        {"role": "user", "content": prompt},
    ], temperature=0.3, max_tokens=3000, json_mode=True)

    if not result and Config.HAS_DOUBAO:
        logger.warning("filter_default_attractions: OpenAI 兼容 LLM 未返回内容，尝试豆包筛选")
        result = _call_doubao_responses(prompt, use_web_search=False)

    if not result:
        logger.warning("filter_default_attractions: LLM 未返回内容（可能调用失败/超时），保留原始候选列表")
        return attractions

    selected = _extract_json_array(result)
    if selected is None:
        logger.warning(f"filter_default_attractions: 无法从豆包返回内容中解析出 JSON 数组，原始返回前 300 字: {result[:300]!r}")
        return attractions

    try:
        selected_names = {item["name"]: item.get("reason", "") for item in selected if "name" in item}

        for attr in attractions:
            if attr["name"] in selected_names:
                attr["selected"] = True
                attr["reason"] = selected_names[attr["name"]]
            else:
                attr["selected"] = False
                attr["reason"] = ""

        return attractions
    except (TypeError, KeyError) as e:
        logger.warning(f"Failed to process filter_default_attractions response: {e}")
        return attractions


def discover_trip_attractions(city: str, days: int, profile: dict) -> tuple[list, dict]:
    """联网搜索「{城市}{天数}日游」攻略，归纳候选地点并按人格预选。详见 backend/services/web_search.py"""
    if not Config.HAS_WEB_SEARCH:
        return [], {"mode": "none", "sources": []}
    from backend.services.web_search import discover_attractions

    return discover_attractions(city or "上海", days or 3, profile or {})


def _request_options(json_mode: bool, thinking: bool | None, max_tokens: int) -> dict:
    """不同服务商的扩展参数：DeepSeek 的思考开关、JSON 模式（只对确定支持的服务商开启）"""
    opts: dict = {"max_tokens": max_tokens}
    if Config.LLM_PROVIDER == "deepseek":
        think = (Config.LLM_THINKING == "on") if thinking is None else thinking
        opts["extra_body"] = {"thinking": {"type": "enabled" if think else "disabled"}}
        if think:
            # 思考过程也计入 max_tokens，不放宽的话答案会被截成空串
            opts["max_tokens"] = max_tokens + 8000
    if json_mode and Config.LLM_PROVIDER in ("deepseek", "openai"):
        opts["response_format"] = {"type": "json_object"}
    return opts


def chat_completion(messages: list, temperature: float = 0.7, max_tokens: int = 2000, json_mode: bool = False, thinking: bool | None = None) -> str:
    """
    调用 LLM 进行对话补全。失败（含熔断冷却期内）返回空串，调用方应改用本地能力。
    json_mode=True 时提示词里必须出现「JSON」字样（OpenAI / DeepSeek 的要求）。
    """
    if not Config.HAS_LLM or not _available("llm"):
        return ""

    multimodal = any(isinstance(m.get("content"), list) for m in messages)
    if Config.LLM_WIRE_API == "responses" and not multimodal:
        prompt = "\n\n".join(f"{m.get('role', 'user')}: {m['content']}" for m in messages if m.get("content"))
        text = _call_openai_responses(prompt, use_web_search=False, model=Config.LLM_MODEL)
        if text or not _available("llm"):
            return text

    if not client:
        return ""

    try:
        response = client.chat.completions.create(
            model=Config.LLM_MODEL,
            messages=messages,
            temperature=temperature,
            **_request_options(json_mode, thinking, max_tokens),
        )
        choice = response.choices[0]
        content = choice.message.content
        if not content:
            logger.warning("LLM 返回空内容（finish_reason=%s）", choice.finish_reason)
            return ""
        _reset("llm")
        return content.strip()
    except Exception as e:
        _trip("llm", e)
        return ""


def chat_with_tools(messages: list, tools: list, handlers: dict, max_rounds: int = 3, temperature: float = 0.6, max_tokens: int = 1500) -> str:
    """
    带工具调用的对话（Chat Completions 的 function calling）。
    handlers: 工具名 → 函数(**arguments) -> str。模型不再调用工具时返回最终回答；失败返回空串。
    """
    if not Config.HAS_LLM or not _available("llm") or not client or Config.LLM_WIRE_API == "responses":
        return ""
    msgs = list(messages)
    try:
        for round_no in range(max_rounds + 1):
            kwargs = _request_options(False, False, max_tokens)
            if round_no < max_rounds:
                kwargs.update(tools=tools, tool_choice="auto")
            response = client.chat.completions.create(model=Config.LLM_MODEL, messages=msgs, temperature=temperature, **kwargs)
            msg = response.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                _reset("llm")
                return (msg.content or "").strip()
            msgs.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls],
            })
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                    result = handlers[c.function.name](**args)
                except Exception as e:  # noqa: BLE001 — 工具失败也要告诉模型，让它换个说法回答
                    result = f"工具调用失败：{str(e)[:100]}"
                msgs.append({"role": "tool", "tool_call_id": c.id, "content": result or "（没有结果）"})
        return ""
    except Exception as e:
        _trip("llm", e)
        return ""


def generate_itinerary(locations: list, user_profile: dict, trip_config: dict, catalog: list | None = None) -> dict:
    """
    生成行程：有大模型时让它编排，再用行程引擎校验与修正；没有或失败时直接用行程引擎。
    返回的 dict 带一个内部字段 _engine（llm / local），由路由层取出。
    """
    from backend.services.planner import PACES, build_itinerary, finalize_llm_itinerary, insights, pace_of

    catalog = catalog or []
    profile = user_profile or {}
    pace_key = pace_of(profile, trip_config.get("pace"))

    if Config.HAS_LLM and _available("llm"):
        days = trip_config.get("days", 2)
        loc_lines = []
        for loc in locations:
            info = insights(loc)
            extra = []
            if info["closed_weekdays"]:
                extra.append("周" + "".join("一二三四五六日"[w] for w in info["closed_weekdays"]) + "不开放")
            if info["needs_booking"]:
                extra.append("需预约")
            loc_lines.append(
                f"- [{loc['id']}] {loc['name']}（{loc.get('category') or loc.get('type')}）建议时段：{loc.get('best_time') or '不限'}；"
                f"停留约 {loc.get('duration_min') or 60} 分钟；坐标 {loc.get('lat')},{loc.get('lng')}"
                + (f"；{'；'.join(extra)}" if extra else "")
                + (f"；{loc.get('tips')}" if loc.get("tips") else "")
            )
        labels = " / ".join(profile.get(k) for k in ("di_label", "rl_label", "ps_label", "cd_label") if profile.get(k))
        deep = profile.get("deep_profile") or {}
        persona = f"旅行人格：{profile.get('personality_name') or '未测试'}" + (f"（{labels}）" if labels else "")
        if deep.get("summary"):
            persona += f"\n深度画像：{deep['summary']}"
        if deep.get("avoid"):
            persona += f"\n想避免：{'、'.join(deep['avoid'])}"
        start = trip_config.get("start_date")
        prompt = f"""你是专业的旅行路线规划师。只能使用下面列出的地点（用方括号里的 id 引用），不要编造新地点。

## 候选地点
{chr(10).join(loc_lines)}

## 用户
{persona}
- 天数：{days} 天{f"，{start} 出发" if start else ""}
- 节奏：{PACES[pace_key]['label']}（每天最多 {PACES[pace_key]['max_stops']} 个地点）
- 同行：{trip_config.get('companions') or '未说明'}；预算：{trip_config.get('budget') or '未说明'}

## 规则
1. 按地理位置把相邻地点放在同一天，避免来回折返
2. 尊重「建议时段」：夜景等傍晚 / 夜间景点放在当天最后
3. 遵守不开放日；时间要留出停留时长与通勤
4. 放不下的地点放进 recommendations

只输出 JSON：
{{"summary": "2-3 句概述", "days": [{{"day": 1, "title": "Day 1 · 主题", "items": [{{"time": "09:30", "location_id": "loc_001", "activity": "做什么", "notes": "一句实用提示"}}]}}],
 "recommendations": [{{"location_id": "loc_002", "activity": "做什么", "reason": "一句理由"}}], "tips": ["整体建议"]}}"""
        result = chat_completion(
            [
                {"role": "system", "content": "你是专业的旅行规划师。只输出合法 JSON，不要 Markdown、不要解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=6000,
            json_mode=True,
        )
        raw = parse_json(result) if result else None
        if result and not isinstance(raw, dict):
            logger.warning("大模型返回的行程不是合法 JSON，改用行程引擎")
            raw = None
        fixed = finalize_llm_itinerary(raw, locations, profile, trip_config, catalog) if raw else None
        if fixed:
            fixed["_engine"] = "llm"
            return fixed

    plan = build_itinerary(locations, profile, trip_config, catalog)
    plan["_engine"] = "local"
    return plan


_WMO = (((0,), "晴"), ((1, 2, 3), "多云"), ((45, 48), "雾"), (tuple(range(51, 68)), "雨"), (tuple(range(71, 78)), "雪"), ((80, 81, 82), "阵雨"), ((85, 86), "阵雪"), ((95, 96, 99), "雷雨"))


def _compact_trip(context: dict) -> str:
    """把前端传来的行程压缩成几行文字（整份 JSON 动辄几万字，既慢又分散模型注意力）"""
    lines = []
    trip = context.get("trip") or {}
    if trip:
        lines.append(f"目的地：{trip.get('city') or '未知'}；出发：{trip.get('startDate') or trip.get('start_date') or '未定'}；{trip.get('days') or '?'} 天；预算：{trip.get('budget') or '未说明'}")
    itinerary = context.get("itinerary") or {}
    for d in (itinerary.get("days") or [])[:14]:
        stops = []
        for it in d.get("items") or []:
            loc = it.get("location") or {}
            name = loc.get("name") or it.get("activity") or ""
            if name:
                stops.append(f"{it.get('time') or ''} {name}".strip())
        if stops:
            lines.append(f"Day {d.get('day')}：" + " → ".join(stops))
    weather = context.get("weather")
    for w in ((weather.get("days") if isinstance(weather, dict) else weather) or [])[:7]:
        if isinstance(w, dict) and w.get("date") and w.get("code") is not None:
            sky = next((t for codes, t in _WMO if w["code"] in codes), "多云")
            lines.append(f"{w['date']} {sky}，{w.get('tmin')}~{w.get('tmax')}°C，降水概率 {w.get('rain_prob', '?')}%")
    return "\n".join(lines) or "（还没有行程）"


_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "联网搜索实时信息：营业时间、门票价格、预约方式、闭馆通知、展览演出、交通线路、最新开业或关停等。知识可能过时的问题都应该先搜索。",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索词，包含城市名和地点名，如「成都 大熊猫基地 预约 门票」"}},
            "required": ["query"],
        },
    },
}


def chat_with_companion(message: str, context: dict, local_hint: str = "") -> tuple[str, list]:
    """
    旅行搭子对话（支持多轮）。返回 (回答, 引用的资料)。
    开启联网搜索时模型可以自己决定是否搜索；local_hint 是本地助手基于行程算出来的参考答案（距离、时间、预算等）。
    """
    from datetime import date

    profile = context.get("profile") or {}
    city = ((context.get("trip") or {}).get("city") or "").strip()
    persona = profile.get("personality_name") or profile.get("mbti") or "未测试"
    system_prompt = f"""你是「旅搭子」，一个熟悉当地、温暖实用的旅行伙伴。今天是 {date.today().isoformat()}。

## 用户的旅行
{_compact_trip(context)}
旅行人格：{persona}
{f"## 参考（根据行程计算的事实，可直接引用）{chr(10)}{local_hint}" if local_hint else ""}

## 回答方式
1. 像本地朋友一样直接给建议，200 字以内，可以用列表
2. 问路线调整时给出具体方案（第几天、挪到哪、为什么）
3. 营业时间、门票、预约、活动这类会变的信息{"先用 web_search 查，回答里用 [1] [2] 标注出处" if Config.HAS_WEB_SEARCH else "提醒用户出发前再确认"}
4. 不确定就直说，不要编造；行程里没写的信息（比如出发日期没定）不要自己假设"""

    messages = [{"role": "system", "content": system_prompt}]
    for turn in (context.get("chat_history") or [])[-10:]:
        role, content = turn.get("role"), turn.get("content")
        if role in ("user", "assistant") and content and content != message:
            messages.append({"role": role, "content": str(content)[:2000]})
    messages.append({"role": "user", "content": message})

    if not Config.HAS_WEB_SEARCH or Config.LLM_WIRE_API == "responses":
        return chat_completion(messages, temperature=0.7, max_tokens=1200), []

    from backend.services.web_search import answer_sources

    sources: list[dict] = []

    def web_search(query: str) -> str:
        text, items = answer_sources(str(query)[:80], city)
        start = len(sources) + 1
        sources.extend(items)
        if not items:
            return "没有搜到相关结果"
        # 编号接着之前的往下排，模型引用 [n] 时与返回给前端的列表一一对应
        return re.sub(r"^\[(\d+)\]", lambda m: f"[{int(m.group(1)) + start - 1}]", text, flags=re.M)

    text = chat_with_tools(messages, [_SEARCH_TOOL], {"web_search": web_search}, max_rounds=2, temperature=0.6, max_tokens=1200)
    if not text:
        return chat_completion(messages, temperature=0.7, max_tokens=1200), []
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text) if 0 < int(n) <= len(sources)})
    return text, [{**sources[n - 1], "n": n} for n in cited]


def polish_transcript(text: str, city: str = "", hints: list[str] | None = None) -> str:
    """
    语音转写常把地名听成同音字（「五康路」「外摊」），也可能夹杂繁体。
    让大模型结合城市与候选地名改正错字、统一为简体，不增删内容；失败时原样返回。
    """
    if not text or not Config.HAS_LLM:
        return text
    prompt = f"""下面是一段{city}旅行视频的语音识别结果，可能有同音错字（尤其是地名、店名）和繁体字。
请改正错字、统一为简体中文、补全标点。不要增加或删除内容，不要总结。
{f"可能出现的地名：{'、'.join(hints[:60])}" if hints else ""}

识别结果：
{text[:6000]}

只输出 JSON：{{"text": "改正后的全文"}}"""
    out = parse_json(chat_completion([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=4000, json_mode=True))
    fixed = (out or {}).get("text") if isinstance(out, dict) else None
    # 防止模型擅自总结：改正后的长度应与原文相近
    if isinstance(fixed, str) and 0.6 * len(text[:6000]) <= len(fixed) <= 1.5 * len(text[:6000]) + 50:
        return fixed.strip() + text[6000:]
    return text
