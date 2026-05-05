from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pc_build_agent.models.schemas import ParsedRequirements, ProductRecord, SpecifiedPartModel


COMPONENT_KEYS = ["cpu", "gpu", "ram", "ssd", "motherboard", "psu", "cooling", "case"]
CATEGORY_COMPONENT_MAP = {
    "处理器": "cpu",
    "CPU": "cpu",
    "显卡": "gpu",
    "GPU": "gpu",
    "主板": "motherboard",
    "内存": "ram",
    "硬盘": "ssd",
    "SSD": "ssd",
    "散热": "cooling",
    "散热器": "cooling",
    "电源": "psu",
    "机箱": "case",
}


def _normalize_spec_category(cat: str) -> str:
    m = {
        "GPU": "显卡",
        "CPU": "处理器",
        "COOLER": "散热",
        "MOTHERBOARD": "主板",
        "RAM": "内存",
        "SSD": "硬盘",
        "CASE": "机箱",
        "PSU": "电源",
        "FAN": "风扇",
        "MONITOR": "显示器",
    }
    if cat in m:
        return m[cat]
    return cat


def normalize_requirement_profile(input_obj: Any) -> dict[str, Any]:
    if isinstance(input_obj, dict) and "requirement_profile" in input_obj:
        return dict(input_obj["requirement_profile"] or {})

    if hasattr(input_obj, "requirement_profile"):
        profile = getattr(input_obj, "requirement_profile")
        if isinstance(profile, dict) and "requirement_profile" in profile:
            return dict(profile["requirement_profile"] or {})
        if isinstance(profile, dict):
            return dict(profile)

    if hasattr(input_obj, "requirements"):
        req = input_obj.requirements
        # TODO: remove this legacy fallback after all callers migrate to RequirementProfile.
        return {
            "performance": dict(getattr(req, "performance", {}) or {}),
            "appearance": dict(getattr(req, "appearance", {}) or {}),
            "price": dict(getattr(req, "price", {}) or {}),
            "other": _model_to_dict(getattr(req, "other", {}) or {}),
            "capability_profile": dict(getattr(input_obj, "capability_profile", {}) or {}),
            "selection_context": dict(getattr(input_obj, "selection_context", {}) or {}),
        }

    if isinstance(input_obj, dict):
        return {
            "performance": dict(input_obj.get("performance", {}) or {}),
            "appearance": dict(input_obj.get("appearance", {}) or {}),
            "price": dict(input_obj.get("price", {}) or {}),
            "other": dict(input_obj.get("other", {}) or {}),
            "capability_profile": dict(input_obj.get("capability_profile", {}) or {}),
            "selection_context": dict(input_obj.get("selection_context", {}) or {}),
        }

    return {
        "performance": {},
        "appearance": {},
        "price": {},
        "other": {},
        "capability_profile": {},
        "selection_context": {},
    }


def get_capability_profile(parsed_or_profile: Any) -> dict[str, Any]:
    if isinstance(parsed_or_profile, dict):
        if "capability_profile" in parsed_or_profile:
            return dict(parsed_or_profile.get("capability_profile") or {})
        if "requirement_profile" in parsed_or_profile:
            inner = dict(parsed_or_profile.get("requirement_profile") or {})
            return dict(inner.get("capability_profile") or {})
        return {}

    if hasattr(parsed_or_profile, "capability_profile"):
        return dict(getattr(parsed_or_profile, "capability_profile") or {})

    if hasattr(parsed_or_profile, "requirement_profile"):
        profile = getattr(parsed_or_profile, "requirement_profile")
        if isinstance(profile, dict):
            if "requirement_profile" in profile:
                return dict((profile.get("requirement_profile") or {}).get("capability_profile") or {})
            return dict(profile.get("capability_profile") or {})
    return {}


def map_category_to_component(category: str) -> str | None:
    return CATEGORY_COMPONENT_MAP.get(category)


def normalize_component_weights(component_weights: dict[str, Any]) -> dict[str, float]:
    kept: dict[str, float] = {}
    for component in COMPONENT_KEYS:
        raw = component_weights.get(component)
        if not isinstance(raw, (int, float)):
            continue
        value = max(1.0, min(5.0, float(raw)))
        kept[component] = value
    total = sum(kept.values())
    if total <= 0:
        return {}
    return {key: value / total for key, value in kept.items()}


def _spec_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.replace("，", "/").replace(",", "/").replace("|", "/")
        return [part.strip().upper() for part in text.split("/") if part.strip()]
    return []


def _model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model or {})


def _profile_usage_list(profile: dict[str, Any]) -> list[str]:
    performance = dict(profile.get("performance") or {})
    usage = list(profile.get("usage") or [])
    usage.extend([str(item) for item in performance.get("secondary_usage") or [] if item])
    usage.extend([str(item) for item in performance.get("primary_usage") or [] if item])
    return list(dict.fromkeys(usage))


def _budget_mid_from_profile(profile: dict[str, Any]) -> float | None:
    price = dict(profile.get("price") or {})
    extraction = dict(price.get("budget_extraction") or {})
    min_budget = extraction.get("min_budget")
    max_budget = extraction.get("max_budget")
    target_budget = extraction.get("target_budget")
    if min_budget is not None and max_budget is not None:
        return (float(min_budget) + float(max_budget)) / 2
    if target_budget is not None:
        return float(target_budget)
    if max_budget is not None:
        return float(max_budget)
    if min_budget is not None:
        return float(min_budget)
    total_budget = dict((profile.get("selection_context") or {}).get("budget_context", {})).get("total_budget", {})
    if total_budget.get("target_budget") is not None:
        return float(total_budget["target_budget"])
    return None


def _budget_max_from_profile(profile: dict[str, Any]) -> float | None:
    price = dict(profile.get("price") or {})
    extraction = dict(price.get("budget_extraction") or {})
    if extraction.get("max_budget") is not None:
        return float(extraction["max_budget"])
    total_budget = dict((profile.get("selection_context") or {}).get("budget_context", {})).get("total_budget", {})
    if total_budget.get("max_budget") is not None:
        return float(total_budget["max_budget"])
    return None


def _usage_blob_from_profile(profile: dict[str, Any]) -> str:
    performance = dict(profile.get("performance") or {})
    values = []
    values.extend(_profile_usage_list(profile))
    values.extend([str(item) for item in performance.get("matched_keywords") or [] if item])
    return " ".join(values)


def _appearance_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return dict(profile.get("appearance") or {})


def _selection_context_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return dict(profile.get("selection_context") or {})


def _need_monitor_from_profile(profile: dict[str, Any]) -> bool:
    other = dict(profile.get("other") or {})
    purchase_scope = dict(other.get("purchase_scope") or {})
    if purchase_scope.get("include_monitor") is True:
        return True
    if purchase_scope.get("only_host") is True or purchase_scope.get("include_monitor") is False:
        return False
    total_budget = dict(_selection_context_from_profile(profile).get("budget_context", {})).get("total_budget", {})
    if total_budget.get("effective_host_budget") is not None:
        return False
    return False


def _specified_hard_map_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    specified_parts = list(profile.get("specified_parts") or [])
    out: dict[str, Any] = {}
    for sp in specified_parts:
        if not isinstance(sp, dict):
            continue
        cat = _normalize_spec_category(str(sp.get("category") or ""))
        if sp.get("constraint_level", "hard") == "hard":
            out[cat] = sp
    return out


def _budget_mid(parsed: ParsedRequirements) -> float | None:
    b = parsed.requirements.budget
    if not b:
        return None
    if b.min is not None and b.max is not None:
        return (float(b.min) + float(b.max)) / 2
    if b.max is not None:
        return float(b.max)
    if b.min is not None:
        return float(b.min)
    return None


def _budget_max(parsed: ParsedRequirements) -> float | None:
    b = parsed.requirements.budget
    if not b or b.max is None:
        return None
    return float(b.max)


def _usage_blob(parsed: ParsedRequirements) -> str:
    return " ".join(parsed.requirements.usage or [])


def _want_integrated_only(parsed: ParsedRequirements) -> bool:
    u = _usage_blob(parsed)
    keys_game = ["游戏", "3A", "电竞", "2K", "4K", "显卡"]
    if any(k in u for k in keys_game):
        return False
    office_like = ["办公", "影音", "文档", "上网"]
    if any(k in u for k in office_like):
        return True
    return False


def _need_fan_category(parsed: ParsedRequirements) -> bool:
    ap = parsed.requirements.appearance or {}
    style = str(ap.get("style") or "")
    color_pref = str(ap.get("color") or "")
    blob = style + color_pref + _usage_blob(parsed)
    keys = ["海景房", "RGB", "灯效", "风扇", "颜值"]
    return any(k in blob for k in keys)


def categories_for_build(parsed: ParsedRequirements) -> tuple[list[str], bool, bool]:
    """返回参与装机的品类列表、(是否需要显卡独显)、是否需要风扇"""
    base = ["处理器", "显卡", "主板", "内存", "硬盘", "机箱", "散热", "电源"]
    gpu_needed = not _want_integrated_only(parsed)

    for sp in parsed.requirements.specified_parts:
        if _normalize_spec_category(sp.category) == "显卡":
            gpu_needed = True

    disp = parsed.requirements.display
    need_monitor = bool(disp and disp.need_monitor)

    want_fan = _need_fan_category(parsed)

    cats = list(base)
    if want_fan:
        cats.append("风扇")
    if need_monitor:
        cats.append("显示器")
    return cats, gpu_needed, want_fan


def specified_hard_map(parsed: ParsedRequirements) -> dict[str, SpecifiedPartModel]:
    out: dict[str, SpecifiedPartModel] = {}
    for sp in parsed.requirements.specified_parts:
        cat = _normalize_spec_category(sp.category)
        if sp.constraint_level == "hard":
            out[cat] = sp
    return out


def fuzzy_bonus(name: str, needle: str) -> float:
    needle = needle.strip().lower()
    if not needle:
        return 0.0
    ls = name.lower()
    if needle.lower() in ls:
        return 0.35
    parts = re.split(r"\s+|/", needle)
    hit = sum(1 for p in parts if len(p) >= 2 and p.lower() in ls)
    return min(0.35, 0.08 * hit)


def appearance_bonus(name: str, parsed: ParsedRequirements) -> float:
    ap = parsed.requirements.appearance or {}
    score = 0.0
    color = str(ap.get("color") or "").lower()
    style = str(ap.get("style") or "")
    if color == "white" or "白" in style:
        if "白" in name:
            score += 0.25
    if "海景房" in style:
        if "海景房" in name:
            score += 0.25
    if "rgb" in str(ap.get("rgb_preference") or "").lower() or "RGB" in style.upper():
        if "RGB" in name.upper() or "ARGB" in name.upper():
            score += 0.15
    return min(0.45, score)


def usage_bonus(category: str, name: str, parsed: ParsedRequirements) -> float:
    u = _usage_blob(parsed)
    score = 0.0
    game_hit = any(k in u for k in ["游戏", "3A", "电竞"])
    if game_hit:
        if category == "显卡" and ("RTX" in name or "RX" in name):
            score += 0.25
        if category == "处理器" and (("i7" in name) or ("i5-136" in name) or ("Ryzen 7" in name)):
            score += 0.08
    office_hit = any(k in u for k in ["办公", "剪辑", "AI", "渲染"])
    if office_hit and category == "内存" and ("32" in name or "64" in name):
        score += 0.08
    return min(0.35, score)


def ideal_share(category: str, parsed: ParsedRequirements, cats: list[str]) -> float:
    """粗粒度预算占比（游戏主机默认）"""
    disp = parsed.requirements.display
    monitor = bool(disp and disp.need_monitor)

    if monitor:
        table = {
            "显示器": 0.20,
            "显卡": 0.36,
            "处理器": 0.15,
            "主板": 0.09,
            "内存": 0.07,
            "硬盘": 0.07,
            "机箱": 0.05,
            "电源": 0.06,
            "散热": 0.03,
            "风扇": 0.02,
        }
    else:
        table = {
            "显卡": 0.42,
            "处理器": 0.18,
            "主板": 0.09,
            "内存": 0.07,
            "硬盘": 0.07,
            "机箱": 0.06,
            "电源": 0.06,
            "散热": 0.04,
            "风扇": 0.03,
            "显示器": 0.0,
        }

    if category not in cats:
        return 0.0
    return table.get(category, 0.08)


def score_product(
    category: str,
    product: ProductRecord,
    parsed: ParsedRequirements,
    cats: list[str],
) -> float:
    w = parsed.weights or {}
    wp = float(w.get("performance", 0.35))
    wprice = float(w.get("price", 0.35))
    wapp = float(w.get("appearance", 0.2))
    wother = float(w.get("other", 0.1))

    mid = _budget_mid(parsed)
    mx = _budget_max(parsed)

    share = ideal_share(category, parsed, cats)
    ideal_price = (mid or mx or 8000) * share if share > 0 else None

    price_fit = 0.55
    if ideal_price and ideal_price > 0:
        gap = abs(float(product.price) - ideal_price) / ideal_price
        price_fit = max(0.05, 1.0 - min(1.0, gap))

    perf = usage_bonus(category, product.name, parsed)

    if category == "显卡" and product.price <= 0:
        perf = 0.2 if _want_integrated_only(parsed) else 0.05

    app = appearance_bonus(product.name, parsed)

    hard_specs = specified_hard_map(parsed)
    spec_boost = 0.0
    if category in hard_specs:
        spec_boost += 0.55 + fuzzy_bonus(product.name, hard_specs[category].user_text)

    score = (
        wp * perf
        + wprice * price_fit
        + wapp * app
        + wother * min(0.35, len(product.tags) * 0.03)
        + spec_boost
        + min(0.15, len(product.name) * 0.001)
    )

    if category == "显卡" and _want_integrated_only(parsed) and (product.price <= 0 or "无需独立显卡" in product.name):
        score += 0.40

    return float(score)


@dataclass
class SelectionResult:
    sorted_by_category: dict[str, list[ProductRecord]]
    scores_by_category: dict[str, dict[str, float]]
    top3_preview: dict[str, list[dict]]


class PartsSelectionAgent:
    def select(self, requirement_profile: dict[str, Any], pool: list[ProductRecord]) -> SelectionResult:
        profile = normalize_requirement_profile(requirement_profile)
        cats, gpu_needed, want_fan = categories_for_build_from_profile(profile)
        hard_specs = _specified_hard_map_from_profile(profile)

        by_cat: dict[str, list[ProductRecord]] = {}
        for p in pool:
            by_cat.setdefault(p.category, []).append(p)

        sorted_by_category: dict[str, list[ProductRecord]] = {}
        scores_by_category: dict[str, dict[str, float]] = {}
        top3_preview: dict[str, list[dict]] = {}
        anchor_parts: dict[str, ProductRecord] = {}

        for cat in cats:
            items = list(by_cat.get(cat, []))
            if cat == "显卡" and not gpu_needed:
                items = [p for p in items if p.price <= 0 or "无需独立显卡" in p.name or "核显办公" in p.name]
                if not items:
                    items = [p for p in by_cat.get("显卡", []) if p.price <= 0]

            scored: list[tuple[float, ProductRecord]] = []
            for it in items:
                if cat in hard_specs and hard_specs[cat].get("constraint_level", "hard") == "hard":
                    needle = str(hard_specs[cat].get("user_text") or "")
                    b = fuzzy_bonus(it.name, needle)
                    if b < 0.08 and needle.strip():
                        continue
                s = score_product_from_profile(cat, it, profile, cats, anchor_parts=anchor_parts)
                scored.append((s, it))
            if not scored:
                scored = [(score_product_from_profile(cat, it, profile, cats, anchor_parts=anchor_parts), it) for it in items]
            scored.sort(key=lambda x: x[0], reverse=True)
            ordered = [p for _, p in scored]
            sorted_by_category[cat] = ordered
            scores_by_category[cat] = {p.sku_id: s for s, p in scored}
            if ordered:
                anchor_parts[cat] = ordered[0]

            preview = []
            for p in ordered[:3]:
                preview.append(
                    {
                        "sku_id": p.sku_id,
                        "name": p.name,
                        "price": p.price,
                        "score": round(scores_by_category[cat].get(p.sku_id, 0.0), 4),
                    }
                )
            top3_preview[cat] = preview

        if not want_fan and "风扇" in sorted_by_category:
            sorted_by_category.pop("风扇", None)
            scores_by_category.pop("风扇", None)
            top3_preview.pop("风扇", None)

        return SelectionResult(
            sorted_by_category=sorted_by_category,
            scores_by_category=scores_by_category,
            top3_preview=top3_preview,
        )


def categories_for_build_from_profile(profile: dict[str, Any]) -> tuple[list[str], bool, bool]:
    base = ["处理器", "显卡", "主板", "内存", "硬盘", "机箱", "散热", "电源"]
    gpu_needed = not _want_integrated_only_from_profile(profile)

    for sp in profile.get("specified_parts") or []:
        if isinstance(sp, dict) and _normalize_spec_category(str(sp.get("category") or "")) == "显卡":
            gpu_needed = True

    need_monitor = _need_monitor_from_profile(profile)
    want_fan = _need_fan_category_from_profile(profile)

    cats = list(base)
    if want_fan:
        cats.append("风扇")
    if need_monitor:
        cats.append("显示器")
    return cats, gpu_needed, want_fan


def _want_integrated_only_from_profile(profile: dict[str, Any]) -> bool:
    u = _usage_blob_from_profile(profile)
    keys_game = ["游戏", "3A", "电竞", "2K", "4K", "显卡", "aaa_gaming", "fps_esports"]
    if any(k in u for k in keys_game):
        return False
    office_like = ["办公", "影音", "文档", "上网", "general_office", "general_study"]
    if any(k in u for k in office_like):
        return True
    return False


def _need_fan_category_from_profile(profile: dict[str, Any]) -> bool:
    ap = _appearance_from_profile(profile)
    style = str(ap.get("case_style") or ap.get("style") or "")
    color_pref = str(ap.get("color") or "")
    rgb_pref = str(ap.get("rgb") or ap.get("rgb_preference") or "")
    blob = style + color_pref + rgb_pref + _usage_blob_from_profile(profile)
    keys = ["海景房", "RGB", "灯效", "风扇", "颜值", "panoramic", "rgb", "argb"]
    return any(k in blob for k in keys)


def appearance_bonus_from_profile(name: str, profile: dict[str, Any]) -> float:
    ap = _appearance_from_profile(profile)
    score = 0.0
    color = str(ap.get("color") or "").lower()
    style = str(ap.get("case_style") or ap.get("style") or "")
    if color == "white" or "白" in style:
        if "白" in name:
            score += 0.25
    if "海景房" in style or "panoramic" in style:
        if "海景房" in name:
            score += 0.25
    if "rgb" in str(ap.get("rgb") or ap.get("rgb_preference") or "").lower() or "RGB" in style.upper():
        if "RGB" in name.upper() or "ARGB" in name.upper():
            score += 0.15
    return min(0.45, score)


def usage_bonus_from_profile(category: str, name: str, profile: dict[str, Any]) -> float:
    u = _usage_blob_from_profile(profile)
    score = 0.0
    game_hit = any(k in u for k in ["游戏", "3A", "电竞", "aaa_gaming", "fps_esports"])
    if game_hit:
        if category == "显卡" and ("RTX" in name or "RX" in name):
            score += 0.25
        if category == "处理器" and (("i7" in name) or ("i5-136" in name) or ("Ryzen 7" in name)):
            score += 0.08
    office_hit = any(k in u for k in ["办公", "剪辑", "AI", "渲染", "programming_development", "local_llm_inference"])
    if office_hit and category == "内存" and ("32" in name or "64" in name):
        score += 0.08
    return min(0.35, score)


def _spec_values_as_text(product: ProductRecord) -> str:
    if not product.specs:
        return ""
    chunks: list[str] = []
    for key, value in product.specs.items():
        if isinstance(value, list):
            chunks.extend(str(item) for item in value)
        else:
            chunks.append(f"{key}:{value}")
    return " ".join(chunks)


def _component_structured_score(component: str | None, product: ProductRecord, profile: dict[str, Any]) -> float:
    specs = dict(product.specs or {})
    if not component or not specs:
        return 0.0

    usage_blob = _usage_blob_from_profile(profile).lower()
    score = 0.0

    if component == "cpu":
        score += min(0.3, float(specs.get("cpu_single_core_score") or 0) / 5000)
        score += min(0.35, float(specs.get("cpu_multi_core_score") or 0) / 20000)
        score += min(0.12, float(specs.get("cores") or 0) / 32)
        score += min(0.08, float(specs.get("threads") or 0) / 64)
        if "office" in usage_blob or "general_office" in usage_blob:
            if specs.get("has_integrated_graphics") in (True, "是", "true", "True"):
                score += 0.08
    elif component == "gpu":
        score += min(0.4, float(specs.get("gpu_performance_score") or 0) / 10000)
        score += min(0.25, float(specs.get("gaming_score") or 0) / 100)
        score += min(0.25, float(specs.get("ai_score") or 0) / 100)
        score += min(0.18, float(specs.get("vram_gb") or 0) / 24)
    elif component == "motherboard":
        score += min(0.15, float(specs.get("ram_slots") or 0) / 8)
        score += min(0.15, float(specs.get("m2_slots") or 0) / 4)
        if specs.get("wifi_builtin") in (True, "是", "true", "True"):
            score += 0.12
        if specs.get("front_usb_c_header") in (True, "是", "true", "True"):
            score += 0.08
    elif component == "ram":
        score += min(0.35, float(specs.get("capacity_gb") or 0) / 64)
        score += min(0.2, float(specs.get("speed_mhz") or 0) / 8000)
        if float(specs.get("module_count") or 0) >= 2:
            score += 0.08
    elif component == "ssd":
        score += min(0.35, float(specs.get("capacity_gb") or 0) / 4000)
        score += min(0.25, float(specs.get("ssd_performance_score") or 0) / 100)
        score += min(0.1, float(specs.get("endurance_score") or 0) / 100)
    elif component == "cooling":
        score += min(0.35, float(specs.get("cooling_capacity_w") or 0) / 400)
        score += min(0.12, float(specs.get("radiator_size_mm") or 0) / 360)
        noise = specs.get("noise_score")
        if isinstance(noise, (int, float)):
            score += min(0.12, float(noise) / 100)
    elif component == "psu":
        score += min(0.35, float(specs.get("wattage_w") or 0) / 1200)
        efficiency = str(specs.get("efficiency_rating") or "").upper()
        if "GOLD" in efficiency:
            score += 0.08
        if "PLATINUM" in efficiency:
            score += 0.12
        noise_tier = str(specs.get("noise_tier") or "").lower()
        if noise_tier in {"silent", "low_noise"}:
            score += 0.08
    elif component == "case":
        score += min(0.2, float(specs.get("max_gpu_length_mm") or 0) / 450)
        score += min(0.15, float(specs.get("max_cpu_cooler_height_mm") or 0) / 200)
        score += min(0.15, float(specs.get("airflow_score") or 0) / 100)
        style = str(specs.get("case_style") or "")
        appearance = _appearance_from_profile(profile)
        if appearance.get("case_style") and appearance.get("case_style") in style:
            score += 0.1
    return min(score, 1.0)


def _compatibility_penalty(
    category: str,
    product: ProductRecord,
    anchor_parts: dict[str, ProductRecord],
) -> float:
    penalty = 0.0
    specs = dict(product.specs or {})
    if not specs:
        return penalty

    if category == "主板":
        cpu = anchor_parts.get("处理器")
        cpu_socket = (cpu.specs or {}).get("socket") if cpu else None
        mb_socket = specs.get("socket")
        if cpu_socket and mb_socket and str(cpu_socket).upper() != str(mb_socket).upper():
            penalty -= 0.8
    elif category == "散热":
        cpu = anchor_parts.get("处理器")
        cpu_socket = (cpu.specs or {}).get("socket") if cpu else None
        supported = _spec_list(specs.get("supported_sockets"))
        cooling_capacity = specs.get("cooling_capacity_w")
        cpu_tdp = (cpu.specs or {}).get("tdp_w") if cpu else None
        if cpu_socket and supported and str(cpu_socket).upper() not in supported:
            penalty -= 0.8
        elif isinstance(cooling_capacity, (int, float)) and isinstance(cpu_tdp, (int, float)) and float(cooling_capacity) < float(cpu_tdp):
            penalty -= 0.6
    elif category == "内存":
        mb = anchor_parts.get("主板")
        mb_ddr = (mb.specs or {}).get("memory_type") if mb else None
        ram_ddr = specs.get("memory_type")
        if mb_ddr and ram_ddr and str(mb_ddr).upper() != str(ram_ddr).upper():
            penalty -= 0.75
    elif category == "显卡":
        case = anchor_parts.get("机箱")
        gpu_len = specs.get("gpu_length_mm")
        max_gpu = (case.specs or {}).get("max_gpu_length_mm") if case else None
        if isinstance(gpu_len, (int, float)) and isinstance(max_gpu, (int, float)) and float(gpu_len) > float(max_gpu):
            penalty -= 0.85
    elif category == "电源":
        cpu = anchor_parts.get("处理器")
        gpu = anchor_parts.get("显卡")
        case = anchor_parts.get("机箱")
        wattage = specs.get("wattage_w")
        if isinstance(wattage, (int, float)):
            need = 150
            cpu_tdp = (cpu.specs or {}).get("tdp_w") if cpu else None
            gpu_tbp = (gpu.specs or {}).get("tbp_w") if gpu else None
            gpu_rec = (gpu.specs or {}).get("recommended_psu_w") if gpu else None
            if isinstance(cpu_tdp, (int, float)):
                need += float(cpu_tdp)
            if isinstance(gpu_tbp, (int, float)):
                need += float(gpu_tbp)
            if isinstance(gpu_rec, (int, float)) and float(wattage) < float(gpu_rec):
                penalty -= 0.8
            elif need > 150 and float(wattage) < need:
                penalty -= 0.7
        supported = _spec_list((case.specs or {}).get("psu_form_factor_supported")) if case else []
        form_factor = specs.get("form_factor")
        if supported and form_factor and str(form_factor).upper() not in supported:
            penalty -= 0.75
    elif category == "机箱":
        mb = anchor_parts.get("主板")
        gpu = anchor_parts.get("显卡")
        cooler = anchor_parts.get("散热")
        max_gpu = specs.get("max_gpu_length_mm")
        max_cooler = specs.get("max_cpu_cooler_height_mm")
        gpu_len = (gpu.specs or {}).get("gpu_length_mm") if gpu else None
        cooler_height = (cooler.specs or {}).get("cooler_height_mm") if cooler else None
        supported_mb = _spec_list(specs.get("supported_motherboard_form_factors"))
        mb_form = (mb.specs or {}).get("form_factor") if mb else None
        if supported_mb and mb_form and str(mb_form).upper() not in supported_mb:
            penalty -= 0.8
        if isinstance(max_gpu, (int, float)) and isinstance(gpu_len, (int, float)) and float(gpu_len) > float(max_gpu):
            penalty -= 0.8
        if isinstance(max_cooler, (int, float)) and isinstance(cooler_height, (int, float)) and float(cooler_height) > float(max_cooler):
            penalty -= 0.7
    return penalty


def ideal_share_from_profile(category: str, profile: dict[str, Any], cats: list[str]) -> float:
    monitor = _need_monitor_from_profile(profile)
    if monitor:
        table = {
            "显示器": 0.20,
            "显卡": 0.36,
            "处理器": 0.15,
            "主板": 0.09,
            "内存": 0.07,
            "硬盘": 0.07,
            "机箱": 0.05,
            "电源": 0.06,
            "散热": 0.03,
            "风扇": 0.02,
        }
    else:
        table = {
            "显卡": 0.42,
            "处理器": 0.18,
            "主板": 0.09,
            "内存": 0.07,
            "硬盘": 0.07,
            "机箱": 0.06,
            "电源": 0.06,
            "散热": 0.04,
            "风扇": 0.03,
            "显示器": 0.0,
        }
    if category not in cats:
        return 0.0
    base_ratio = table.get(category, 0.08)
    capability_profile = get_capability_profile(profile)
    component = map_category_to_component(category)
    normalized_weights = normalize_component_weights(dict(capability_profile.get("component_weights") or {}))
    if component and component in normalized_weights:
        capability_ratio = normalized_weights[component]
        return (base_ratio * 0.65) + (capability_ratio * 0.35)
    return base_ratio


def score_product_from_profile(
    category: str,
    product: ProductRecord,
    profile: dict[str, Any],
    cats: list[str],
    anchor_parts: dict[str, ProductRecord] | None = None,
) -> float:
    weights = {"performance": 0.35, "price": 0.35, "appearance": 0.2, "other": 0.1}
    mid = _budget_mid_from_profile(profile)
    mx = _budget_max_from_profile(profile)
    capability_profile = get_capability_profile(profile)
    component = map_category_to_component(category)
    normalized_weights = normalize_component_weights(dict(capability_profile.get("component_weights") or {}))
    protected_components = set(capability_profile.get("protected_components") or [])
    cost_cut_components = set(capability_profile.get("cost_cut_components") or [])
    prefer_satisfy = [str(item).lower() for item in capability_profile.get("prefer_satisfy") or []]
    avoid = [str(item).lower() for item in capability_profile.get("avoid") or []]

    share = ideal_share_from_profile(category, profile, cats)
    ideal_price = (mid or mx or 8000) * share if share > 0 else None

    price_fit = 0.55
    if ideal_price and ideal_price > 0:
        gap = abs(float(product.price) - ideal_price) / ideal_price
        price_fit = max(0.05, 1.0 - min(1.0, gap))
    if component in cost_cut_components and ideal_price and float(product.price) > ideal_price * 1.15:
        price_fit *= 0.75

    perf = usage_bonus_from_profile(category, product.name, profile)
    if category == "显卡" and product.price <= 0:
        perf = 0.2 if _want_integrated_only_from_profile(profile) else 0.05
    structured_perf = _component_structured_score(component, product, profile)
    if component and component in normalized_weights:
        perf += structured_perf * (0.45 + normalized_weights[component])
    elif product.specs:
        perf += structured_perf * 0.25
    if component in protected_components:
        perf += structured_perf * 0.2

    app = appearance_bonus_from_profile(product.name, profile)
    hard_specs = _specified_hard_map_from_profile(profile)
    spec_boost = 0.0
    if category in hard_specs:
        spec_boost += 0.55 + fuzzy_bonus(product.name, str(hard_specs[category].get("user_text") or ""))

    searchable = " ".join([product.name, " ".join(product.tags or []), _spec_values_as_text(product)]).lower()
    preference_bonus = 0.0
    for item in prefer_satisfy:
        if item and item in searchable:
            preference_bonus += 0.06
    if component in protected_components:
        preference_bonus += 0.06
    avoid_penalty = 0.0
    for item in avoid:
        if item and item in searchable:
            avoid_penalty += 0.12
    compatibility_penalty = _compatibility_penalty(category, product, anchor_parts or {})

    score = (
        weights["performance"] * perf
        + weights["price"] * price_fit
        + weights["appearance"] * app
        + weights["other"] * min(0.35, len(product.tags) * 0.03)
        + spec_boost
        + preference_bonus
        + compatibility_penalty
        - avoid_penalty
        + min(0.15, len(product.name) * 0.001)
    )

    if category == "显卡" and _want_integrated_only_from_profile(profile) and (product.price <= 0 or "无需独立显卡" in product.name):
        score += 0.40
    return float(score)


def retrieve_candidates(parsed: ParsedRequirements, pool: list[ProductRecord]) -> SelectionResult:
    profile = normalize_requirement_profile(parsed)
    if profile:
        return PartsSelectionAgent().select({"requirement_profile": profile}, pool)

    cats, gpu_needed, want_fan = categories_for_build(parsed)
    hard_specs = specified_hard_map(parsed)

    by_cat: dict[str, list[ProductRecord]] = {}
    for p in pool:
        by_cat.setdefault(p.category, []).append(p)

    sorted_by_category: dict[str, list[ProductRecord]] = {}
    scores_by_category: dict[str, dict[str, float]] = {}
    top3_preview: dict[str, list[dict]] = {}

    for cat in cats:
        items = list(by_cat.get(cat, []))
        if cat == "显卡" and not gpu_needed:
            items = [p for p in items if p.price <= 0 or "无需独立显卡" in p.name or "核显办公" in p.name]
            if not items:
                items = [p for p in by_cat.get("显卡", []) if p.price <= 0]

        scored: list[tuple[float, ProductRecord]] = []
        for it in items:
            if cat in hard_specs and hard_specs[cat].constraint_level == "hard":
                b = fuzzy_bonus(it.name, hard_specs[cat].user_text)
                if b < 0.08 and hard_specs[cat].user_text.strip():
                    continue
            s = score_product(cat, it, parsed, cats)
            scored.append((s, it))
        if not scored:
            scored = [(score_product(cat, it, parsed, cats), it) for it in items]
        scored.sort(key=lambda x: x[0], reverse=True)
        ordered = [p for _, p in scored]
        sorted_by_category[cat] = ordered
        scores_by_category[cat] = {p.sku_id: s for s, p in scored}

        preview = []
        for p in ordered[:3]:
            preview.append(
                {
                    "sku_id": p.sku_id,
                    "name": p.name,
                    "price": p.price,
                    "score": round(scores_by_category[cat].get(p.sku_id, 0.0), 4),
                }
            )
        top3_preview[cat] = preview

    if not want_fan and "风扇" in sorted_by_category:
        sorted_by_category.pop("风扇", None)
        scores_by_category.pop("风扇", None)
        top3_preview.pop("风扇", None)

    return SelectionResult(
        sorted_by_category=sorted_by_category,
        scores_by_category=scores_by_category,
        top3_preview=top3_preview,
    )
