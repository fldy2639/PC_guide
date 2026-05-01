from __future__ import annotations

import re
from dataclasses import dataclass

from pc_build_agent.models.schemas import ParsedRequirements, ProductRecord, SpecifiedPartModel


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
    base = ["处理器", "散热", "主板", "内存", "硬盘", "机箱", "电源"]
    gpu_needed = not _want_integrated_only(parsed)

    for sp in parsed.requirements.specified_parts:
        if _normalize_spec_category(sp.category) == "显卡":
            gpu_needed = True

    disp = parsed.requirements.display
    need_monitor = bool(disp and disp.need_monitor)

    want_fan = _need_fan_category(parsed)

    cats = list(base)
    cats.append("显卡")
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


def retrieve_candidates(parsed: ParsedRequirements, pool: list[ProductRecord]) -> SelectionResult:
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
