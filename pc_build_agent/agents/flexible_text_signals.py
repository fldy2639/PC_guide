from __future__ import annotations

import re
from typing import Any


CATEGORY_ALIASES = {
    "处理器": ["处理器", "CPU", "processor"],
    "显卡": ["显卡", "GPU", "graphics card"],
    "主板": ["主板", "motherboard"],
    "内存": ["内存", "RAM", "memory"],
    "硬盘": ["硬盘", "固态硬盘", "SSD", "storage"],
    "机箱": ["机箱", "case"],
    "散热": ["散热", "散热器", "cooler", "cooling"],
    "电源": ["电源", "PSU", "power supply"],
    "风扇": ["风扇", "fan"],
    "显示器": ["显示器", "monitor"],
}

CATEGORY_WORDS = {
    "处理器",
    "显卡",
    "主板",
    "内存",
    "硬盘",
    "固态硬盘",
    "机箱",
    "散热",
    "散热器",
    "电源",
    "风扇",
    "显示器",
    "CPU",
    "GPU",
    "RAM",
    "SSD",
    "PROCESSOR",
    "GRAPHICSCARD",
    "MOTHERBOARD",
    "MEMORY",
    "STORAGE",
    "CASE",
    "COOLER",
    "PSU",
    "MONITOR",
}

SPEC_INTENT_WORDS = [
    "必须使用",
    "必须用",
    "指定",
    "要用",
    "需要用",
    "希望用",
    "使用",
    "采用",
    "选择",
    "选",
    "上",
    "配",
    "买",
    "换成",
    "只要",
]

NON_SPEC_WORDS = ["不要", "不需要", "不用", "无所谓", "随便", "不限", "都行", "默认"]


def profile_text(profile: dict[str, Any]) -> str:
    preferred = [
        profile.get("original_user_text"),
        profile.get("raw_input"),
        profile.get("user_text"),
        profile.get("transcript"),
    ]
    parts = [str(item) for item in preferred if isinstance(item, str) and item.strip()]
    if parts:
        return " ".join(parts)
    return " ".join(_iter_profile_strings(profile))[:5000]


def core_keyword(text: str) -> str:
    normalized = re.sub(r"[\s\-_/·,.，。()（）]+", "", str(text or "")).upper()
    for word in CATEGORY_WORDS:
        normalized = normalized.replace(re.sub(r"[\s\-_/·,.，。()（）]+", "", word).upper(), "")
    return normalized


def extract_component_specs(text: str) -> dict[str, str]:
    specs: dict[str, str] = {}
    for chunk in _spec_text_chunks(text):
        if _is_negative_spec_chunk(chunk):
            continue
        for category, aliases in CATEGORY_ALIASES.items():
            if category in specs:
                continue
            phrase = _extract_category_phrase(chunk, category, aliases)
            if phrase:
                specs[category] = phrase
    return specs


def _iter_profile_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_profile_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_profile_strings(item)


def _spec_text_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    for sentence in re.split(r"[，。；;\n]+", str(text or "")):
        for chunk in re.split(r"\s*(?:和|以及|搭配|配上|加上|、)\s*", sentence):
            cleaned = chunk.strip(" ，。；;、")
            if cleaned:
                chunks.append(cleaned)
    return chunks


def _is_negative_spec_chunk(chunk: str) -> bool:
    return any(word in chunk for word in NON_SPEC_WORDS)


def _extract_category_phrase(chunk: str, category: str, aliases: list[str]) -> str:
    alias_pattern = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
    category_first = re.search(
        rf"(?:^|[\s:：])(?:{alias_pattern})\s*(?:[:：=是为选用要上配采用选择指定-])?\s*([^，。；;、]{{1,48}})",
        chunk,
        flags=re.IGNORECASE,
    )
    if category_first:
        phrase = _clean_specified_phrase(f"{category_first.group(1)} {category}")
        if _is_specific_phrase(phrase, chunk):
            return phrase

    category_last = re.search(rf"(.{{1,56}}?(?:{alias_pattern}))", chunk, flags=re.IGNORECASE)
    if category_last:
        phrase = _clean_specified_phrase(category_last.group(1))
        if _is_specific_phrase(phrase, chunk):
            return phrase

    return ""


def _is_specific_phrase(phrase: str, chunk: str) -> bool:
    core = core_keyword(phrase)
    if not core:
        return False
    has_intent = any(word in chunk for word in SPEC_INTENT_WORDS)
    has_model_shape = bool(re.search(r"(?:[A-Z]{1,8}\s*\d|\d{3,}|[A-Z]\d)", phrase, flags=re.IGNORECASE))
    return has_model_shape or (has_intent and len(core) >= 2)


def _clean_specified_phrase(phrase: str) -> str:
    text = re.sub(r"\s+", " ", str(phrase or "")).strip(" ，。；;、")
    for separator in SPEC_INTENT_WORDS:
        if separator in text:
            text = text.split(separator)[-1].strip(" ，。；;、")
    return re.sub(r"^(?:[:：=是为选用要上配采用选择指定-])+", "", text).strip(" ，。；;、")
