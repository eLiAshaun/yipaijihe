"""
LLM 服务 - 封装与大语言模型的交互
支持 OpenAI 兼容接口（OpenAI / DeepSeek / 通义千问 / 本地 Ollama 等）
支持豆包 (Doubao / 火山方舟 Ark) Responses API（联网搜索）
无 API Key 时自动降级为本地规则引擎（Demo 模式）
"""

import json
import logging
import re
import requests
from urllib.parse import quote
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
    if not Config.HAS_LLM:
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

    if use_web_search and Config.LLM_WEB_SEARCH == "live":
        payload["tools"] = [{"type": "web_search"}]

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=Config.LLM_TIMEOUT)
        resp.raise_for_status()
        response_text = resp.content.decode("utf-8", "replace")
        text = _extract_responses_stream_text(response_text)
        if text:
            return text
        logger.warning("OpenAI Responses API returned no text")
        return ""
    except Exception as e:
        logger.error(f"OpenAI Responses API error: {e}")
        return ""


def _call_openai_web_search(prompt: str) -> str:
    """调用 OpenAI 兼容 Responses API 做 live 联网搜索"""
    return _call_openai_responses(prompt, use_web_search=True, model=Config.LLM_WEB_SEARCH_MODEL)


def _call_doubao_responses(prompt: str, use_web_search: bool = False) -> str:
    """
    调用豆包 (火山方舟 Ark) Responses API
    use_web_search=True 时启用联网搜索工具
    """
    if not Config.HAS_DOUBAO:
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

        return output_text.strip()
    except Exception as e:
        logger.error(f"Doubao Responses API error: {e}")
        return ""


def _extract_json_array(text: str):
    """
    尽量健壮地从模型回复中解析出 JSON 数组。

    豆包在联网搜索后经常会在 JSON 前后附带说明文字，或用 ```json ... ``` /
    ``` ... ``` 代码块包裹结果，即使提示词中明确要求"只输出 JSON 数组"。
    如果直接 json.loads 失败就直接判定为"无返回"并触发降级到静态默认列表，
    会导致联网搜索结果被白白丢弃（这正是之前"豆包候选景点一直只有 8 个静态默认景点"的根因之一）。
    这里做多级尝试：先整体解析，再剥离代码块围栏解析，最后在原文中正则提取
    第一段形如 [...] 的片段解析，尽量从模型的真实回复里把数据捞出来。
    """
    if not text:
        return None
    text = text.strip()

    # 1) 直接尝试整体解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 2) 去除 ```json ... ``` 或 ``` ... ``` 代码块围栏后再解析
    if "```" in text:
        stripped = re.sub(r"```[a-zA-Z]*\s*", "", text)
        stripped = stripped.replace("```", "").strip()
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    # 3) 退而求其次：在文本中正则提取第一段完整的 JSON 数组片段
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None


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
    result = chat_completion(messages, temperature=0.2, max_tokens=3000)

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
    ], temperature=0.3, max_tokens=3000)

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


def discover_trip_attractions(city: str, days: int, profile: dict) -> list:
    """
    用豆包 (Doubao / 火山方舟 Ark) Responses API 的联网搜索能力（web_search 工具），
    搜索"{city}{days}日游攻略"相关内容（N 为用户填写的出行天数），归纳总结其中
    被多篇攻略反复提及的景点 / 餐厅 / 街区，作为"地图预览"页的默认地点来源。

    重要说明：豆包联网搜索拿到的是网页文本摘要，并非真实的抖音视频列表，因此这里
    不会编造虚假的视频标题/封面/点赞数据，而是为每个归纳出的地点生成一个
    真实可跳转的"抖音搜索结果"链接（douyin.com/search/...），点击后会跳转到
    抖音站内对该地点相关内容的搜索结果页；并附带一句"内容提要"（video_hint）
    用于在 UI 上模拟展示效果（明确标注为 AI 归纳，非真实视频数据）。

    随后结合用户的旅行风格主画像测试结果（profile），调用 filter_default_attractions
    让豆包基于画像描述文本对这些地点进行选中标记 + 生成推荐理由。

    返回约 20 个地点，每个包含
    name/type/lat/lng/keywords/video_hint/douyin_search_url/link_label/selected/reason
    """
    if not Config.HAS_LLM and not Config.HAS_DOUBAO:
        return []

    city = city or "上海"
    days = days or 3
    query_phrase = f"{city}{days}日游攻略"

    discover_prompt = f"""你是一名熟悉社交媒体旅行内容生态的研究员。请联网搜索与"{query_phrase}"相关的攻略内容
（可尝试搜索"{query_phrase}"、"{query_phrase} 抖音"、"{city} {days}天 旅行攻略 必去景点/美食"等关键词），
并基于搜索到的真实内容，归纳总结其中**被多篇攻略反复提及**的景点、街区、餐厅或小吃店
（尽量多挑选一些，争取找到约 18-22 个、需位于{city}市内、互不重复，可以包含景点也可以包含美食地点；
如确实搜索不到这么多被多次提及的地点，可适当放宽"反复提及"的标准，但不要编造不存在的地点）。

对每一个地点，请给出以下字段：
- name: 地点名称（简洁、常见、可直接用于地图搜索）
- type: 从 ["food","nature","culture","landmark","street"] 中选择最贴切的一个
  （food=美食/餐厅小吃，nature=自然景观/公园绿地，culture=人文古迹/博物馆/展馆，landmark=地标建筑，street=商业街区/特色马路）
- lat / lng: 该地点在{city}的大致 WGS84 经纬度坐标（数字，保留4位小数；不确定时给出所在区域中心的合理估计值）
- keywords: 1-3 个简短关键词标签（数组）
- video_hint: 用一句话客观描述"搜索到的攻略/笔记通常会怎样介绍这个地方"（20字以内，仅作内容提要展示）

只输出一个 JSON 数组，不要输出任何其他文字、解释或代码块标记，格式如下：
[{{"name": "外滩", "type": "landmark", "lat": 31.2400, "lng": 121.4900, "keywords": ["夜景", "万国建筑"], "video_hint": "常作为{city}{days}日游开篇打卡点被提及"}}]"""

    result = _call_openai_web_search(discover_prompt)
    if result:
        logger.info("discover_trip_attractions: OpenAI 兼容联网搜索返回内容")
    elif Config.HAS_DOUBAO:
        logger.warning("discover_trip_attractions: OpenAI 兼容联网搜索未返回内容，尝试豆包联网搜索")
        result = _call_doubao_responses(discover_prompt, use_web_search=True)

    if not result:
        logger.warning("discover_trip_attractions: 联网搜索未返回内容（调用失败/超时/无 API Key），将降级到静态默认景点列表")
        return []

    discovered = _extract_json_array(result)
    if discovered is None:
        # 直接 json.loads 容易因为模型在 JSON 前后附带说明文字或代码块围栏而失败，
        # 进而被错误地当成"无返回"触发降级 —— 这正是之前"候选精选景点一直只有 8 个（静态默认列表数量）"的根因。
        # _extract_json_array 已尝试多种容错解析方式，仍失败时才在此记录原始内容用于排查。
        logger.warning(f"discover_trip_attractions: 无法从豆包返回内容中解析出 JSON 数组，原始返回前 500 字: {result[:500]!r}")
        return []

    try:
        # 整理地点数据：去重、生成唯一 ID、补全默认提要，并为每个地点生成
        # 真实可跳转的抖音搜索结果链接（搜索该地点相关内容，而非具体某条视频）
        attractions = []
        seen_names = set()
        for i, attr in enumerate(discovered):
            if not isinstance(attr, dict):
                continue
            name = (attr.get("name") or "").strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)

            attr["name"] = name
            attr["id"] = f"loc_{len(attractions)+1:03d}"
            attr["selected"] = True  # 默认全选，后续由 filter_default_attractions 按用户画像筛选

            search_query = f"{name} {city} {days}日游"
            attr["douyin_search_url"] = f"https://www.douyin.com/search/{quote(search_query)}"
            attr["link_label"] = f"在抖音搜索「{name}」相关内容"
            attr["source_label"] = "AI 联网搜索归纳的内容提要 · 非真实视频数据"
            if not (attr.get("video_hint") or "").strip():
                attr["video_hint"] = f"多篇「{query_phrase}」笔记提到了「{name}」"

            attractions.append(attr)

        logger.info(f"discover_trip_attractions: 豆包联网搜索归纳出 {len(attractions)} 个去重后的地点（{city}{days}日游）")

        if not attractions:
            return []

        # 结合用户旅行风格主画像测试结果，把画像描述文本发给豆包，
        # 让它基于画像去挑选最符合该用户偏好的地点并生成推荐理由
        if profile:
            attractions = filter_default_attractions(profile, attractions)

        return attractions
    except (TypeError, AttributeError) as e:
        logger.warning(f"Failed to process discover_trip_attractions response: {e}")
        return []


def chat_completion(messages: list, temperature: float = 0.7, max_tokens: int = 2000) -> str:
    """
    调用 LLM 进行对话补全
    """
    if not Config.HAS_LLM:
        return ""

    prompt_parts = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if content:
            prompt_parts.append(f"{role}: {content}")
    prompt = "\n\n".join(prompt_parts)

    if Config.LLM_WIRE_API == "responses":
        return _call_openai_responses(prompt, use_web_search=False, model=Config.LLM_MODEL)

    if not client:
        return ""

    try:
        response = client.chat.completions.create(
            model=Config.LLM_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        if content is None:
            logger.warning("LLM 返回空内容")
            return ""
        return content.strip()
    except Exception as e:
        logger.error(f"LLM API error: {e}")
        return ""


def generate_itinerary(locations: list, user_profile: dict, trip_config: dict) -> dict:
    """
    生成个性化旅行路线
    """
    # 构建地点信息
    locations_text = "\n".join([
        f"- {loc['name']} ({loc['category']})：{loc['description']}"
        f"  标签：{', '.join(loc['tags'])}"
        f"  停留时间：约{loc['duration_min']}分钟"
        f"  拥挤度：{loc['crowd_level']}"
        f"  费用：{loc['cost_level']}"
        for loc in locations
    ])

    # 构建用户画像
    profile_text = ""
    if user_profile:
        p = user_profile
        profile_text = f"""
用户旅行人格：{p.get('personality_name', '未知')}
- 节奏偏好：{p.get('pace_label', '适中')}
- 地点偏好：{p.get('pref_label', '混合')}
- 体验偏好：{p.get('exp_label', '综合')}
- 社交偏好：{p.get('social_label', '灵活')}
"""

    days = trip_config.get("days", 2)
    companions = trip_config.get("companions", "")
    budget = trip_config.get("budget", "中等")

    companion_line = f"- 同行人：{companions}" if companions else ""

    prompt = f"""你是一个专业的旅行路线规划师。请根据以下信息生成一份详细的旅行路线。

## 可选地点
{locations_text}

## 用户信息
{profile_text}
- 旅行天数：{days}天
{companion_line}
- 预算：{budget}

## 要求
1. 根据地理位置的相邻性安排路线，减少来回奔波
2. 根据用户旅行人格调整节奏和内容
3. **每天最多安排 4 个核心景点**，留出休息和用餐时间
4. 考虑地点的最佳到访时间
5. 给出实用的交通建议
6. 把未安排进每天行程的备选景点放入 recommendations（推荐池），供用户自由选择

请以 JSON 格式输出，格式如下：
{{
  "summary": "路线概述（2-3句话）",
  "days": [
    {{
      "day": 1,
      "title": "Day 1 主题",
      "items": [
        {{
          "time": "09:00",
          "location_id": "loc_xxx",
          "activity": "活动描述",
          "notes": "小贴士"
        }}
      ]
    }}
  ],
  "recommendations": [
    {{
      "location_id": "loc_xxx",
      "activity": "推荐活动",
      "reason": "推荐理由（一句话）"
    }}
  ],
  "tips": ["整体建议1", "整体建议2"]
}}"""

    messages = [
        {"role": "system", "content": "你是一个专业的旅行规划师，擅长根据用户偏好生成个性化路线。只输出JSON，不要其他文字。"},
        {"role": "user", "content": prompt},
    ]

    result = chat_completion(messages, temperature=0.7)

    if result:
        try:
            # 尝试提取 JSON
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON")

    # 降级到本地规则生成
    return _generate_fallback_itinerary(locations, user_profile, trip_config)


def chat_with_companion(message: str, context: dict) -> str:
    """
    旅行搭子对话（支持多轮）
    """
    # 构建上下文
    itinerary = context.get("itinerary", {})
    profile = context.get("profile", {})
    current_location = context.get("current_location", "")
    chat_history = context.get("chat_history", [])

    system_prompt = f"""你是"旅搭子"，一个温暖、有趣、实用的 AI 旅行伙伴。

当前旅行信息：
- 路线：{json.dumps(itinerary, ensure_ascii=False) if itinerary else '暂无'}
- 用户偏好：{json.dumps(profile, ensure_ascii=False) if profile else '暂无'}
- 当前位置：{current_location or '未知'}

你的角色：
1. 像一个本地朋友一样给出建议
2. 回答简洁实用，不超过200字
3. 如果用户问路线调整，给出具体方案
4. 语气亲切自然，可以用 emoji
5. 如果不确定，坦诚告知
6. 记住之前的对话内容，保持连贯"""

    messages = [{"role": "system", "content": system_prompt}]

    # 加入历史对话（最多10轮）
    if chat_history:
        for turn in chat_history[-10:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    # 加入当前消息
    messages.append({"role": "user", "content": message})

    result = chat_completion(messages, temperature=0.8)

    if result:
        return result

    # 降级到本地回复
    return _generate_fallback_reply(message, context)


def _generate_fallback_itinerary(locations: list, user_profile: dict, trip_config: dict) -> dict:
    """
    本地规则引擎生成路线（无 LLM 时的降级方案）
    已安排景点每天最多 4 个（有明确时间），多余景点放入推荐池
    """
    days = trip_config.get("days", 2)

    # 按地理位置简单分组（按纬度+经度的和排序，实现简单的地理聚类）
    sorted_locs = sorted(locations, key=lambda l: l["lat"] + l["lng"])

    # 每天最多安排 4 个景点
    max_per_day = 4
    total_scheduled = max_per_day * days

    scheduled_locs = sorted_locs[:total_scheduled]
    extra_locs = sorted_locs[total_scheduled:]

    # 分配已安排景点到各天
    days_plan = []
    for day_idx in range(days):
        start = day_idx * max_per_day
        end = start + max_per_day
        day_locs = scheduled_locs[start:end]

        items = []
        times = ["09:30", "12:00", "14:30", "17:00"]
        for i, loc in enumerate(day_locs):
            items.append({
                "time": times[i] if i < len(times) else "19:00",
                "location_id": loc["id"],
                "activity": f"探索{loc['name']}",
                "notes": loc.get("tips", ""),
            })

        days_plan.append({
            "day": day_idx + 1,
            "title": f"Day {day_idx + 1}",
            "items": items,
        })

    # 推荐池：多余的景点
    recommendations = []
    for loc in extra_locs:
        recommendations.append({
            "location_id": loc["id"],
            "activity": f"探索{loc['name']}",
            "reason": loc.get("description", "") or loc.get("tips", "") or f"{loc['name']}值得一逛",
        })

    result = {
        "summary": f"为您规划了{days}天的上海旅行路线，已安排 {len(scheduled_locs)} 个核心景点。",
        "days": days_plan,
        "recommendations": recommendations,
        "tips": ["建议穿舒适的步行鞋", "上海地铁很方便，建议多利用地铁出行"],
    }
    return result


def _generate_fallback_reply(message: str, context: dict) -> str:
    """
    本地规则引擎回复（无 LLM 时的降级方案）
    """
    msg = message.lower()

    if any(w in msg for w in ["下雨", "雨", "天气"]):
        return "下雨了？别担心！建议去室内景点逛逛，比如 1933老场坊 或 M50创意园，都是室内的，拍照也很出片 ☔"

    if any(w in msg for w in ["累", "休息", "疲惫", "坐下"]):
        return "走累了吧？找个咖啡店坐坐吧～推荐去东平路或安福路附近，梧桐树下喝杯咖啡，歇歇脚 ☕"

    if any(w in msg for w in ["吃", "餐厅", "饿", "午饭", "晚饭"]):
        return "想吃东西的话，乌鲁木齐中路有很多不错的小店！或者去田子坊附近，小吃选择很多 🍜"

    if any(w in msg for w in ["拍照", "出片", "好看"]):
        return "想拍照的话，武康大楼绝对是首选！光影效果一流。如果想人少点，推荐去1933老场坊，建筑结构特别出片 📸"

    if any(w in msg for w in ["人多", "排队", "拥挤"]):
        return "觉得人多？可以试试去 M50创意园 或 甜爱路，这两个地方相对小众，人少很多 👍"

    if any(w in msg for w in ["路线", "怎么走", "交通"]):
        return "上海地铁很方便！推荐下载高德地图，步行导航很准。两个地点之间如果超过3公里，建议地铁出行 🚇"

    return "我在呢！有什么想问的尽管说～可以问我路线调整、美食推荐、拍照点、或者任何临时的问题 😊"
