"""
灵感提取：从任意文字（抖音 / 小红书文案、攻略、地名清单、视频转写）里找出可以去的地点。

收藏的灵感来自很多地方，不只有抖音视频。这里不要求语音转写：
  1. 景点库匹配（含「武康路·武康大楼」这类组合名的别名）—— 带完整数据（坐标、建议时段、贴士）
  2. 常见地名坐标表（来自视频提取模块）
  3. 配置了大模型时，再让大模型补充识别（并做防编造过滤）
每个结果都附上原文里提到它的那句话，方便用户回忆「为什么想去」。
"""

from __future__ import annotations

import re

from backend.config import Config

# 组合名里可以单独作为别名的部分要至少 2 个字；这些后缀去掉后剩下的部分也能当别名（如「外滩夜景」→「外滩」）
_STRIP_SUFFIXES = ("夜景", "工业遗存", "文化名人街", "创意园", "渡轮码头", "咖啡带", "绿道", "步道", "艺术公园", "森林公园")
_GENERIC_PARTS = {"网红冰淇淋", "思南书局"}


def _aliases(name: str) -> list[str]:
    out = {name}
    for part in name.split("·"):
        part = part.strip()
        if len(part) >= 2 and part not in _GENERIC_PARTS:
            out.add(part)
    for a in list(out):
        for suf in _STRIP_SUFFIXES:
            if a.endswith(suf) and len(a) - len(suf) >= 2:
                out.add(a[: -len(suf)])
    return sorted(out, key=len, reverse=True)


def _snippet(text: str, start: int, end: int) -> str:
    """原文中提到地点的那一句"""
    left = max(text.rfind(ch, 0, start) for ch in "。！？!?\n；;") + 1
    rights = [i for i in (text.find(ch, end) for ch in "。！？!?\n；;") if i != -1]
    right = min(rights) if rights else len(text)
    sentence = re.sub(r"https?://\S+", "", text[left:right])
    # 去掉抖音分享文案里的模板噪音：「5.8 复制打开抖音，看看【xx的作品】」「复制此链接」等
    sentence = re.sub(r"^\s*\d+(\.\d+)?\s*", "", sentence)
    sentence = re.sub(r"复制(打开|此链接)[^，,]*[，,]?\s*(看看)?|【[^】]{0,30}的作品】|[#＃]\S+", "", sentence)
    sentence = re.sub(r"\s{2,}", " ", sentence).strip(" ，,、@：:|｜")
    return sentence[:60] + ("…" if len(sentence) > 60 else "")


def extract_places(text: str, city: str, catalog: list[dict], use_llm: bool = True) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []
    found: dict[str, dict] = {}  # 规范化名称 → 结果
    spans: list[tuple[int, int]] = []

    def add(loc: dict, start: int, end: int):
        key = loc["name"].lower()
        if key in found or any(start >= s and end <= e for s, e in spans):
            return
        spans.append((start, end))
        item = dict(loc)
        item["reason"] = _snippet(text, start, end) or item.get("reason") or ""
        item["source"] = "inspiration"
        item["_pos"] = start
        found[key] = item

    # 1) 景点库（长别名优先，避免「武康路」盖掉「武康路·武康大楼」）
    alias_map = []
    for loc in catalog:
        for a in _aliases(loc["name"]):
            alias_map.append((a, loc))
    alias_map.sort(key=lambda x: len(x[0]), reverse=True)
    for alias, loc in alias_map:
        for m in re.finditer(re.escape(alias), text, re.IGNORECASE if alias.isascii() else 0):
            add(loc, m.start(), m.end())

    # 2) 常见地名坐标表（目前覆盖上海）
    if city == "上海":
        from backend.routes.video import _SHANGHAI_COORD_FALLBACK, _infer_type_from_keywords, _keywords_for_rule_location

        catalog_names = " ".join(l["name"] for l in catalog)
        for name, (lat, lng) in sorted(_SHANGHAI_COORD_FALLBACK.items(), key=lambda x: len(x[0]), reverse=True):
            if name in catalog_names:  # 已被景点库覆盖
                continue
            for m in re.finditer(re.escape(name), text):
                kws = _keywords_for_rule_location(name)
                add({"id": f"gaz_{name}", "name": name, "lat": lat, "lng": lng, "type": _infer_type_from_keywords(kws), "keywords": kws, "tags": kws}, m.start(), m.end())

    # 3) 大模型补充（只接受原文里确实出现过的名字）
    if use_llm and Config.HAS_LLM and len(text) >= 6:
        try:
            from backend.routes.video import _extract_locations_from_text

            for loc in _extract_locations_from_text(text, "", ""):
                name = (loc.get("name") or "").strip()
                pos = text.find(name) if name else -1
                if pos >= 0:
                    add({**loc, "id": loc.get("id") or f"llm_{name}"}, pos, pos + len(name))
        except Exception:  # noqa: BLE001 — 大模型补充失败不影响规则结果
            pass

    out = sorted(found.values(), key=lambda x: x.pop("_pos"))
    # 纯地名清单（「武康路、外滩、豫园」）的原句没有额外信息，不当作推荐理由
    names = sorted({a for o in out for a in _aliases(o["name"])}, key=len, reverse=True)
    for o in out:
        o.setdefault("keywords", o.get("tags") or [])
        rest = o.get("reason") or ""
        for n in names:
            rest = rest.replace(n, "")
        if len(re.findall(r"[\u4e00-\u9fa5A-Za-z]", rest)) < 4:
            o["reason"] = ""
    return out
