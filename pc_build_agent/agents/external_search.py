from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pc_build_agent.agents.flexible_text_signals import core_keyword, extract_component_specs, profile_text
from pc_build_agent.agents.selection import SelectionResult, categories_for_build_from_profile, normalize_requirement_profile
from pc_build_agent.agents.validation_engine import ValidationOutcome
from pc_build_agent.models.schemas import BuildLine, ParsedRequirements
from pc_build_agent.services.deepseek_client import DeepSeekClient


@dataclass
class SearchPlanItem:
    category: str
    keyword: str
    estimated_price: float


class ExternalSearchBuildAgent:
    """Creates a search-link fallback when the local hardware catalog cannot close a build."""

    ALLOWED_CATEGORIES = {"处理器", "显卡", "主板", "内存", "硬盘", "机箱", "散热", "电源", "风扇", "显示器"}
    COMPONENT_TO_CATEGORY = {
        "cpu": "处理器",
        "processor": "处理器",
        "gpu": "显卡",
        "graphics_card": "显卡",
        "motherboard": "主板",
        "memory": "内存",
        "ram": "内存",
        "ssd": "硬盘",
        "storage": "硬盘",
        "case": "机箱",
        "cooling": "散热",
        "cooler": "散热",
        "psu": "电源",
        "power_supply": "电源",
        "fan": "风扇",
        "monitor": "显示器",
    }
    CATEGORY_SHARES = {
        "处理器": 0.18,
        "显卡": 0.40,
        "主板": 0.09,
        "内存": 0.07,
        "硬盘": 0.07,
        "机箱": 0.06,
        "散热": 0.04,
        "电源": 0.06,
        "风扇": 0.02,
        "显示器": 0.20,
    }

    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client

    def search(self, parsed: ParsedRequirements, selection_result: SelectionResult | None = None) -> ValidationOutcome:
        profile = normalize_requirement_profile(parsed)
        categories, _, _ = categories_for_build_from_profile(profile)
        budget = self._budget_anchor(parsed)
        plan_items = self._llm_plan(parsed, profile) or self._deterministic_plan(parsed, profile)
        plan_items = self._apply_specified_keywords(plan_items, parsed, profile, categories)
        plan_items = self._normalize_plan_items(plan_items, categories, budget)
        if not plan_items:
            plan_items = self._deterministic_plan(parsed, profile)
            plan_items = self._apply_specified_keywords(plan_items, parsed, profile, categories)
            plan_items = self._normalize_plan_items(plan_items, categories, budget)
        build = [
            BuildLine(
                category=item.category,
                sku_id=f"external-search-{self._slug(item.category)}",
                name=f"外部搜索建议：{item.keyword}",
                price=float(item.estimated_price),
                jd_url=self._jd_search_url(item.keyword),
                source="external_search",
            )
            for item in plan_items
        ]
        total = float(sum(item.price for item in build))
        target_max = parsed.requirements.budget.max if parsed.requirements.budget else None
        warnings = [
            "本地商品库没有形成可用闭环，已切换为京东搜索链接兜底。",
            "外部搜索方案只提供可采购方向和参考预算，最终价格、库存与兼容性需要在商详页人工确认。",
        ]
        if selection_result and selection_result.debug:
            empty_categories = [
                category
                for category, debug in (selection_result.debug.get("by_category") or {}).items()
                if debug.get("final_candidate_count") == 0
            ]
            if empty_categories:
                warnings.append("本地无候选品类：" + "、".join(empty_categories))
        if target_max is not None and total > float(target_max) * 1.25:
            warnings.append("搜索兜底估算已明显超过预算，建议优先调整指定型号或提高预算。")

        return ValidationOutcome(
            status="external_search_fallback",
            final_build=build,
            total_price=total,
            budget_check={
                "status": "external_search_estimate",
                "target_max": target_max,
                "note": "搜索兜底总价为预算拆分估算，不代表实时成交价。",
            },
            compatibility_check={
                "status": "needs_manual_check",
                "warnings": warnings[:2],
            },
            risk_check={
                "status": "search_fallback",
                "warnings": warnings,
            },
            unmet_constraints=[],
            alternative_suggestions=[
                "优先打开每个京东搜索入口，按销量、评价和自营/旗舰店过滤后核对具体型号。",
                "确认 CPU 插槽、主板内存代际、显卡长度、机箱限长和电源功率后再下单。",
            ],
            debug={
                "fallback": "external_search",
                "requirement_profile": profile,
                "plan_items": [item.__dict__ for item in plan_items],
                "source": "external_search",
            },
        )

    def _deterministic_plan(self, parsed: ParsedRequirements, profile: dict[str, Any]) -> list[SearchPlanItem]:
        categories, gpu_needed, _ = categories_for_build_from_profile(profile)
        budget = self._budget_anchor(parsed)
        usage_blob = self._usage_blob(profile)
        appearance_blob = self._appearance_blob(profile)
        keywords = self._keyword_table(budget, usage_blob, appearance_blob, gpu_needed)
        shares = self._normalized_shares(categories)

        plan: list[SearchPlanItem] = []
        for category in categories:
            keyword = keywords.get(category)
            if not keyword:
                continue
            price = max(1.0, round(budget * shares.get(category, 0.08)))
            plan.append(SearchPlanItem(category=category, keyword=keyword, estimated_price=price))
        return plan

    def _normalize_plan_items(
        self,
        plan_items: list[SearchPlanItem],
        categories: list[str],
        budget: float,
    ) -> list[SearchPlanItem]:
        allowed = [category for category in categories if category in self.ALLOWED_CATEGORIES]
        allowed_set = set(allowed)
        normalized: list[SearchPlanItem] = []
        seen: set[str] = set()
        for item in plan_items:
            if item.category not in allowed_set:
                continue
            if item.category in seen:
                continue
            keyword = str(item.keyword or "").strip()
            if not keyword:
                continue
            normalized.append(
                SearchPlanItem(
                    category=item.category,
                    keyword=keyword,
                    estimated_price=max(float(item.estimated_price or 0), 1.0),
                )
            )
            seen.add(item.category)

        total = sum(item.estimated_price for item in normalized)
        if not normalized or budget <= 0:
            return normalized
        if total >= budget * 0.35:
            return normalized

        shares = self._normalized_shares([item.category for item in normalized])
        return [
            SearchPlanItem(
                category=item.category,
                keyword=item.keyword,
                estimated_price=max(1.0, round(budget * shares.get(item.category, 0.08))),
            )
            for item in normalized
        ]

    def _apply_specified_keywords(
        self,
        plan_items: list[SearchPlanItem],
        parsed: ParsedRequirements,
        profile: dict[str, Any],
        categories: list[str],
    ) -> list[SearchPlanItem]:
        specified = self._specified_keywords_by_category(parsed, profile)
        if not specified:
            return plan_items

        plan_items = self._remove_cross_category_spec_leaks(plan_items, specified, parsed, profile)
        by_category = {item.category: item for item in plan_items}
        shares = self._normalized_shares(categories)
        budget = self._budget_anchor(parsed)
        for category, keyword in specified.items():
            if category not in categories or category not in self.ALLOWED_CATEGORIES:
                continue
            if category in by_category:
                current = by_category[category]
                by_category[category] = SearchPlanItem(
                    category=category,
                    keyword=keyword,
                    estimated_price=current.estimated_price,
                )
            else:
                by_category[category] = SearchPlanItem(
                    category=category,
                    keyword=keyword,
                    estimated_price=max(1.0, round(budget * shares.get(category, 0.08))),
                )
        return [by_category[category] for category in categories if category in by_category]

    def _remove_cross_category_spec_leaks(
        self,
        plan_items: list[SearchPlanItem],
        specified: dict[str, str],
        parsed: ParsedRequirements,
        profile: dict[str, Any],
    ) -> list[SearchPlanItem]:
        _, gpu_needed, _ = categories_for_build_from_profile(profile)
        replacements = self._keyword_table(
            self._budget_anchor(parsed),
            self._usage_blob(profile),
            self._appearance_blob(profile),
            gpu_needed,
        )
        cleaned: list[SearchPlanItem] = []
        for item in plan_items:
            if item.category in specified:
                cleaned.append(item)
                continue
            if self._keyword_reuses_other_category_spec(item.keyword, item.category, specified):
                replacement = replacements.get(item.category)
                if replacement:
                    cleaned.append(
                        SearchPlanItem(
                            category=item.category,
                            keyword=replacement,
                            estimated_price=item.estimated_price,
                        )
                    )
                    continue
            cleaned.append(item)
        return cleaned

    def _keyword_reuses_other_category_spec(
        self,
        keyword: str,
        category: str,
        specified: dict[str, str],
    ) -> bool:
        normalized_keyword = core_keyword(keyword)
        if not normalized_keyword:
            return False
        for specified_category, specified_text in specified.items():
            if specified_category == category:
                continue
            core = core_keyword(specified_text)
            if len(core) >= 4 and core in normalized_keyword:
                return True
        return False

    def _specified_keywords_by_category(self, parsed: ParsedRequirements, profile: dict[str, Any]) -> dict[str, str]:
        keywords: dict[str, str] = {}

        for item in getattr(parsed.requirements, "specified_parts", []) or []:
            category = str(getattr(item, "category", "") or "").strip()
            text = str(getattr(item, "user_text", "") or "").strip()
            if category and text:
                keywords[category] = text

        for item in profile.get("specified_parts") or []:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "").strip()
            if not category:
                component = str(item.get("component") or item.get("component_type") or "").strip().lower()
                category = self.COMPONENT_TO_CATEGORY.get(component, "")
            keyword = str(item.get("user_text") or item.get("keyword") or "").strip()
            if not keyword and item.get("keywords"):
                keyword = " ".join(str(part) for part in item.get("keywords") or [] if str(part).strip())
            if category and keyword:
                keywords[category] = keyword

        for category, keyword in extract_component_specs(profile_text(profile)).items():
            keywords.setdefault(category, keyword)

        return keywords

    def _llm_plan(self, parsed: ParsedRequirements, profile: dict[str, Any]) -> list[SearchPlanItem]:
        if not self.client or not getattr(self.client, "api_key", ""):
            return []
        categories, _, _ = categories_for_build_from_profile(profile)
        prompt = {
            "requirement_profile": profile,
            "budget": parsed.requirements.budget.model_dump() if parsed.requirements.budget else {},
            "required_categories": categories,
            "hard_specified_parts": self._specified_keywords_by_category(parsed, profile),
            "instruction": (
                "请给出一个 PC 装机外部搜索兜底方案。不要编造具体商品链接，只输出每个品类的京东搜索关键词和估算价格。"
                "必须保留 hard_specified_parts 中对应品类的用户指定词；不要把某个指定配件关键词挪用到其他品类。"
                "JSON 格式：{\"items\":[{\"category\":\"处理器\",\"keyword\":\"...\",\"estimated_price\":1234}]}"
            ),
        }
        try:
            raw = self.client.chat_json(
                [
                    {"role": "system", "content": "你是装机导购搜索规划助手，只输出 JSON。"},
                    {"role": "user", "content": str(prompt)},
                ],
                temperature=0.2,
                step="external_search_plan",
            )
        except Exception:
            return []

        items = []
        for item in raw.get("items") or []:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "").strip()
            keyword = str(item.get("keyword") or "").strip()
            if not category or not keyword:
                continue
            try:
                price = float(item.get("estimated_price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            items.append(SearchPlanItem(category=category, keyword=keyword, estimated_price=max(price, 1.0)))
        return items

    def _keyword_table(self, budget: float, usage_blob: str, appearance_blob: str, gpu_needed: bool) -> dict[str, str]:
        text = f"{usage_blob} {appearance_blob}".lower()
        is_ai = any(token in text for token in ["ai", "本地模型", "大模型", "深度学习", "渲染"])
        is_creator = any(token in text for token in ["剪辑", "视频", "3d", "建模", "渲染"])
        is_gaming = any(token in text for token in ["游戏", "3a", "电竞", "4k", "2k", "黑神话"])
        is_office = any(token in text for token in ["办公", "学习", "编程", "代码"])
        white = "white" in text or "白" in appearance_blob
        panoramic = "海景房" in appearance_blob or "panoramic" in text

        if not gpu_needed or (is_office and not is_gaming and budget <= 5000):
            cpu = "AMD Ryzen 5 8600G 盒装"
            gpu = "无需独立显卡 核显办公"
        elif budget >= 14000 and (is_ai or is_creator):
            cpu = "Intel i7 i9 处理器 盒装"
            gpu = "NVIDIA RTX 4070 Ti SUPER 16G 显卡"
        elif budget >= 9000 and (is_gaming or is_creator or is_ai):
            cpu = "AMD Ryzen 5 7500F 盒装"
            gpu = "RTX 4070 SUPER 显卡"
        elif budget >= 6500 and is_gaming:
            cpu = "AMD Ryzen 5 7500F 盒装"
            gpu = "RTX 4060 Ti 16G 显卡"
        else:
            cpu = "Intel i5 12400F 处理器"
            gpu = "RTX 4060 显卡"

        case_keyword = "白色海景房 机箱" if white and panoramic else "白色机箱" if white else "ATX 机箱 风道"
        return {
            "处理器": cpu,
            "显卡": gpu,
            "主板": "B650 主板 WiFi DDR5" if "ryzen" in cpu.lower() or "amd" in cpu.lower() else "B760 主板 WiFi DDR5",
            "内存": "DDR5 32G 内存 套条" if budget >= 6500 else "DDR4 16G 内存 套条",
            "硬盘": "2TB NVMe SSD 固态硬盘" if budget >= 8000 or is_creator or is_ai else "1TB NVMe SSD 固态硬盘",
            "机箱": case_keyword,
            "散热": "360 水冷 散热器" if budget >= 12000 else "双塔 风冷 散热器",
            "电源": "850W 金牌 全模组 电源" if budget >= 12000 or is_ai else "650W 金牌 电源",
            "风扇": "ARGB 机箱风扇 套装" if "rgb" in text or panoramic else "静音 机箱风扇",
            "显示器": "27英寸 2K 144Hz 显示器" if is_gaming else "27英寸 4K 显示器",
        }

    def _normalized_shares(self, categories: list[str]) -> dict[str, float]:
        raw = {category: self.CATEGORY_SHARES.get(category, 0.08) for category in categories}
        total = sum(raw.values()) or 1.0
        return {category: value / total for category, value in raw.items()}

    def _budget_anchor(self, parsed: ParsedRequirements) -> float:
        budget = parsed.requirements.budget
        if budget and budget.min is not None and budget.max is not None:
            return (float(budget.min) + float(budget.max)) / 2
        if budget and budget.max is not None:
            return float(budget.max)
        if budget and budget.min is not None:
            return float(budget.min)
        return 8000.0

    def _usage_blob(self, profile: dict[str, Any]) -> str:
        performance = dict(profile.get("performance") or {})
        parts = [str(item) for item in profile.get("usage") or []]
        for key in ["primary_usage", "secondary_usage", "matched_keywords", "performance_focus"]:
            parts.extend(str(item) for item in performance.get(key) or [])
        return " ".join(parts)

    def _appearance_blob(self, profile: dict[str, Any]) -> str:
        appearance = dict(profile.get("appearance") or {})
        return " ".join(str(value) for value in appearance.values() if value not in (None, "", [], {}))

    def _jd_search_url(self, keyword: str) -> str:
        return f"https://search.jd.com/Search?keyword={quote(keyword)}&enc=utf-8"

    def _slug(self, value: str) -> str:
        return quote(value, safe="").lower()


def should_use_external_search(selection_result: SelectionResult, outcome: ValidationOutcome) -> bool:
    required_categories = {"处理器", "显卡", "主板", "内存", "硬盘", "机箱", "散热", "电源", "显示器"}
    debug = selection_result.debug or {}
    by_category = debug.get("by_category") or {}
    if any(
        category in required_categories and (item or {}).get("final_candidate_count") == 0
        for category, item in by_category.items()
    ):
        return True
    if outcome.final_build:
        return False
    if not by_category:
        return True

    return False
