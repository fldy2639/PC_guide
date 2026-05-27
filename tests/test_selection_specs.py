from __future__ import annotations

from pc_build_agent.agents.selection import (
    PartsSelectionAgent,
    apply_hard_filters,
    filter_by_avoid,
    get_capability_profile,
    ideal_share_from_profile,
    prefer_satisfy_bonus,
    score_product_from_profile,
)
from pc_build_agent.agents.selection_constraint_translator import SelectionConstraintTranslator
from pc_build_agent.models.schemas import ParsedRequirements, ProductRecord, RequirementsModel
from pc_build_agent.schemas.requirement_profile_schema import SelectionContext


def _product(category: str, sku_id: str, name: str, price: float, specs: dict | None = None, tags: list[str] | None = None) -> ProductRecord:
    return ProductRecord(
        sku_id=sku_id,
        category=category,
        name=name,
        price=price,
        tags=tags or [],
        specs=specs or {},
        component_type=(specs or {}).get("component_type"),
        brand=(specs or {}).get("brand"),
        current_price=(specs or {}).get("current_price", price),
    )


def _profile(component_weights: dict[str, int], protected: list[str] | None = None, cost_cut: list[str] | None = None, secondary_usage: list[str] | None = None) -> dict:
    return {
        "performance": {"secondary_usage": secondary_usage or []},
        "appearance": {},
        "price": {},
        "other": {},
        "capability_profile": {
            "scenario_tags": list(secondary_usage or []),
            "capabilities": [],
            "component_weights": component_weights,
            "protected_components": protected or [],
            "cost_cut_components": cost_cut or [],
            "must_satisfy": [],
            "prefer_satisfy": [],
            "avoid": [],
        },
        "selection_context": {},
    }


def test_get_capability_profile_reads_from_legacy_parsed_requirements():
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(),
        capability_profile={"component_weights": {"gpu": 5}},
    )
    assert get_capability_profile(parsed)["component_weights"]["gpu"] == 5


def test_ideal_share_from_profile_protects_gpu_for_aaa_gaming():
    profile = _profile({"gpu": 5, "cpu": 4, "psu": 4, "cooling": 4}, protected=["gpu"], secondary_usage=["aaa_gaming"])
    gpu_ratio = ideal_share_from_profile("显卡", profile, ["显卡", "处理器", "电源"])
    cpu_ratio = ideal_share_from_profile("处理器", profile, ["显卡", "处理器", "电源"])
    assert gpu_ratio > cpu_ratio


def test_score_product_from_profile_uses_specs_for_ai_gpu():
    profile = _profile({"gpu": 5, "ram": 5, "psu": 4}, protected=["gpu"], secondary_usage=["local_llm_inference"])
    high_gpu = _product("显卡", "g1", "高显存显卡", 4999, {"vram_gb": 16, "ai_score": 90, "gpu_performance_score": 88, "tbp_w": 320})
    low_gpu = _product("显卡", "g2", "普通显卡", 4999, {"vram_gb": 8, "ai_score": 35, "gpu_performance_score": 55, "tbp_w": 180})

    assert score_product_from_profile("显卡", high_gpu, profile, ["显卡"]) > score_product_from_profile("显卡", low_gpu, profile, ["显卡"])


def test_office_profile_does_not_overboost_gpu_share():
    profile = _profile({"cpu": 4, "ram": 3, "ssd": 3, "gpu": 1}, secondary_usage=["general_office"])
    gpu_ratio = ideal_share_from_profile("显卡", profile, ["显卡", "处理器"])
    cpu_ratio = ideal_share_from_profile("处理器", profile, ["显卡", "处理器"])
    assert gpu_ratio < 0.35
    assert cpu_ratio > 0.2


def test_score_product_from_profile_keeps_old_logic_when_specs_missing():
    profile = _profile({"gpu": 5}, secondary_usage=["aaa_gaming"])
    no_specs = _product("显卡", "old", "RTX 测试显卡", 2999, {})
    score = score_product_from_profile("显卡", no_specs, profile, ["显卡"])
    assert isinstance(score, float)


def test_parts_selection_agent_uses_capability_profile_in_budget_protection():
    profile = _profile(
        {"gpu": 5, "cpu": 4, "psu": 4, "cooling": 4, "ram": 2, "ssd": 2, "motherboard": 2, "case": 1},
        protected=["gpu", "cpu", "psu", "cooling"],
        cost_cut=["case"],
        secondary_usage=["aaa_gaming"],
    )
    pool = [
        _product("处理器", "cpu-1", "高性能CPU", 1899, {"cpu_single_core_score": 2600, "cpu_multi_core_score": 18000, "tdp_w": 125}),
        _product("处理器", "cpu-2", "普通CPU", 1399, {"cpu_single_core_score": 1800, "cpu_multi_core_score": 12000, "tdp_w": 65}),
        _product("显卡", "gpu-1", "高性能显卡", 3499, {"gpu_performance_score": 92, "gaming_score": 95, "tbp_w": 320, "gpu_length_mm": 330}),
        _product("显卡", "gpu-2", "普通显卡", 2599, {"gpu_performance_score": 60, "gaming_score": 58, "tbp_w": 180, "gpu_length_mm": 260}),
        _product("电源", "psu-1", "850W 金牌", 699, {"wattage_w": 850, "efficiency_rating": "80Plus Gold", "form_factor": "ATX"}),
        _product("电源", "psu-2", "550W 铜牌", 299, {"wattage_w": 550, "efficiency_rating": "80Plus Bronze", "form_factor": "ATX"}),
        _product("散热", "cool-1", "高性能风冷", 299, {"supported_sockets": ["AM5"], "cooling_capacity_w": 220, "cooler_height_mm": 155}),
        _product("散热", "cool-2", "入门散热", 99, {"supported_sockets": ["AM5"], "cooling_capacity_w": 120, "cooler_height_mm": 150}),
        _product("主板", "mb-1", "AM5 主板", 999, {"socket": "AM5", "memory_type": "DDR5", "form_factor": "ATX"}),
        _product("内存", "ram-1", "32G DDR5", 499, {"memory_type": "DDR5", "capacity_gb": 32, "speed_mhz": 6000}),
        _product("硬盘", "ssd-1", "1TB SSD", 399, {"capacity_gb": 1000, "ssd_performance_score": 70}),
        _product("机箱", "case-1", "普通机箱", 199, {"supported_motherboard_form_factors": ["ATX"], "max_gpu_length_mm": 340, "max_cpu_cooler_height_mm": 160}),
    ]
    result = PartsSelectionAgent().select(profile, pool)
    psu_scores = result.scores_by_category["电源"]

    assert ideal_share_from_profile("显卡", profile, ["显卡", "处理器", "电源"]) > 0.34
    assert psu_scores["psu-1"] > psu_scores["psu-2"]


def test_must_satisfy_hard_filters_memory_capacity():
    profile = {
        "performance": {},
        "appearance": {},
        "price": {},
        "other": {},
        "capability_profile": {},
        "selection_context": {
            "must_satisfy": [{"component": "memory", "field": "capacity_gb", "operator": ">=", "value": 32}],
            "prefer_satisfy": [],
            "avoid": [],
        },
        "specified_parts": [],
    }
    pool = [
        _product("内存", "ram-16", "16G DDR5", 199, {"memory_type": "DDR5", "capacity_gb": 16}),
        _product("内存", "ram-32", "32G DDR5", 399, {"memory_type": "DDR5", "capacity_gb": 32}),
        _product("处理器", "cpu-1", "测试CPU", 999, {"component_type": "cpu"}),
    ]
    result = PartsSelectionAgent().select({"requirement_profile": profile}, pool)
    memory_items = result.sorted_by_category["内存"]
    assert memory_items
    assert all((item.specs.get("capacity_gb") or 0) >= 32 for item in memory_items)


def test_motherboard_wifi_must_satisfy_filters_non_wifi_candidates():
    profile = {
        "selection_context": {
            "must_satisfy": [{"component": "motherboard", "field": "wifi_builtin", "operator": "==", "value": True}],
            "prefer_satisfy": [],
            "avoid": [],
        },
        "specified_parts": [],
    }
    pool = [
        _product("主板", "mb-wifi", "带WiFi主板", 999, {"socket": "AM5", "wifi_builtin": True}),
        _product("主板", "mb-nowifi", "普通主板", 799, {"socket": "AM5", "wifi_builtin": False}),
    ]
    result = PartsSelectionAgent().select({"requirement_profile": profile}, pool)
    assert result.sorted_by_category["主板"]
    assert all(item.specs.get("wifi_builtin") is True for item in result.sorted_by_category["主板"])


def test_avoid_excludes_water_cooling_products():
    profile = {
        "selection_context": {
            "must_satisfy": [],
            "prefer_satisfy": [],
            "avoid": [{"component": "cooling", "field": "cooling_type", "operator": "contains", "value": "水冷"}],
        },
        "specified_parts": [],
    }
    pool = [
        _product("散热", "cool-liquid", "360水冷", 399, {"cooling_type": "水冷"}),
        _product("散热", "cool-air", "双塔风冷", 199, {"cooling_type": "风冷"}),
    ]
    result = PartsSelectionAgent().select({"requirement_profile": profile}, pool)
    assert result.sorted_by_category["散热"]
    assert all("水冷" not in str(item.specs.get("cooling_type") or "") for item in result.sorted_by_category["散热"])


def test_specified_parts_locks_gpu_candidates_to_rtx():
    profile = {
        "selection_context": {"must_satisfy": [], "prefer_satisfy": [], "avoid": []},
        "specified_parts": [{"component": "gpu", "keyword": "RTX"}],
    }
    pool = [
        _product("显卡", "gpu-rtx", "RTX 4070 Super", 4499, {"vram_gb": 12}),
        _product("显卡", "gpu-rx", "RX 7800 XT", 3599, {"vram_gb": 16}),
    ]
    result = PartsSelectionAgent().select({"requirement_profile": profile}, pool)
    assert result.sorted_by_category["显卡"]
    assert all("rtx" in item.name.lower() for item in result.sorted_by_category["显卡"])


def test_constraint_translator_preserves_unknown_component_spec_phrases():
    context = SelectionContext()
    profile = {"original_user_text": "必须使用银河幻影 X99 处理器和星河极光 Z9 显卡"}

    compiled = SelectionConstraintTranslator().compile_context(context, profile=profile)

    assert {"component": "cpu", "keyword": "银河幻影 X99 处理器"} in compiled.must_satisfy
    assert {"component": "gpu", "keyword": "星河极光 Z9 显卡"} in compiled.must_satisfy


def test_intel_nvidia_constraints_filter_out_arc_gpu():
    profile = {
        "selection_context": {
            "must_satisfy": [
                {"component": "gpu", "field": "name", "operator": "contains_any", "value": ["NVIDIA", "英伟达", "GeForce", "RTX", "GTX"]},
                {"component": "cpu", "field": "brand", "operator": "contains", "value": "英特尔"},
            ],
            "prefer_satisfy": [],
            "avoid": [{"component": "gpu", "field": "name", "operator": "contains_any", "value": ["Intel Arc", "Arc ", "锐炫", "B580", "B570", "A770", "A750", "RX", "RADEON"]}],
        },
        "specified_parts": [],
    }
    pool = [
        _product("显卡", "gpu-rtx", "NVIDIA GeForce RTX 4070 Super", 4499, {"vram_gb": 12}),
        _product("显卡", "gpu-arc", "蓝戟 Intel Arc B580 Photon 12G", 1999, {"vram_gb": 12}),
        _product("显卡", "gpu-rx", "AMD RADEON RX 9070 XT", 5799, {"vram_gb": 16}),
        _product("处理器", "cpu-intel", "英特尔 i9-14900KF", 3369, {"brand": "英特尔"}),
        _product("处理器", "cpu-amd", "AMD 锐龙9 9950X", 3619, {"brand": "AMD"}),
    ]

    result = PartsSelectionAgent().select({"requirement_profile": profile}, pool)

    assert [item.sku_id for item in result.sorted_by_category["显卡"]] == ["gpu-rtx"]
    assert [item.sku_id for item in result.sorted_by_category["处理器"]] == ["cpu-intel"]


def test_prefer_satisfy_bonus_only_boosts_not_filters():
    constraint = [{"component": "case", "field": "case_style", "operator": "contains", "value": "海景房"}]
    panoramic = _product("机箱", "case-pan", "海景房机箱", 299, {"case_style": "海景房"})
    plain = _product("机箱", "case-plain", "普通机箱", 199, {"case_style": "普通"})
    assert prefer_satisfy_bonus(panoramic, constraint) > prefer_satisfy_bonus(plain, constraint)


def test_impossible_hard_constraint_does_not_fallback_to_raw_candidates():
    profile = {
        "selection_context": {
            "must_satisfy": [{"component": "gpu", "field": "vram_gb", "operator": ">=", "value": 999}],
            "prefer_satisfy": [],
            "avoid": [],
        },
        "specified_parts": [],
    }
    pool = [
        _product("显卡", "gpu-1", "RTX 4070 Super", 4499, {"vram_gb": 12}),
        _product("显卡", "gpu-2", "RX 7800 XT", 3599, {"vram_gb": 16}),
    ]
    result = PartsSelectionAgent().select({"requirement_profile": profile}, pool)
    assert result.sorted_by_category["显卡"] == []
    assert result.filter_warnings
    assert "显卡" in result.filter_warnings
