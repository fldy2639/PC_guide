from __future__ import annotations

import pytest

from pc_build_agent.agents.validation_engine import diagnose, validate_and_select
from pc_build_agent.models.schemas import BudgetModel, ParsedRequirements, ProductRecord, RequirementsModel


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


def _parsed() -> ParsedRequirements:
    return ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(min=0, max=20000)),
        weights={"performance": 0.4, "price": 0.3, "appearance": 0.2, "other": 0.1},
        explanation="test",
    )


def _budget_parsed(max_budget: int) -> ParsedRequirements:
    return ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(min=0, max=max_budget)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation=f"budget {max_budget}",
    )


def _scalable_budget_catalog() -> dict[str, list[ProductRecord]]:
    return {
        "处理器": [
            _product("处理器", "cpu-base", "AM5 入门 CPU", 1000, {"socket": "AM5", "tdp_w": 65}),
            _product("处理器", "cpu-mid", "AM5 中端 CPU", 2000, {"socket": "AM5", "tdp_w": 105}),
            _product("处理器", "cpu-high", "AM5 高端 CPU", 3000, {"socket": "AM5", "tdp_w": 125}),
        ],
        "主板": [_product("主板", "mb", "AM5 DDR5 ATX 主板", 800, {"socket": "AM5", "memory_type": "DDR5", "form_factor": "ATX"})],
        "内存": [_product("内存", "ram", "DDR5 32G", 400, {"memory_type": "DDR5"})],
        "显卡": [
            _product("显卡", "gpu-base", "RTX 入门显卡", 2000, {"gpu_length_mm": 260, "tbp_w": 170, "recommended_psu_w": 650}),
            _product("显卡", "gpu-mid", "RTX 中端显卡", 4500, {"gpu_length_mm": 285, "tbp_w": 220, "recommended_psu_w": 650}),
            _product("显卡", "gpu-high", "RTX 高端显卡", 8500, {"gpu_length_mm": 305, "tbp_w": 300, "recommended_psu_w": 650}),
            _product("显卡", "gpu-ultra", "RTX 旗舰显卡", 9500, {"gpu_length_mm": 320, "tbp_w": 330, "recommended_psu_w": 650}),
        ],
        "硬盘": [_product("硬盘", "ssd", "1TB SSD", 400, {})],
        "电源": [_product("电源", "psu", "650W 电源", 400, {"wattage_w": 650, "form_factor": "ATX"})],
        "散热": [_product("散热", "cooler", "AM5 风冷", 200, {"supported_sockets": ["AM5"], "cooler_height_mm": 150, "cooling_capacity_w": 180})],
        "机箱": [
            _product(
                "机箱",
                "case",
                "ATX 机箱",
                300,
                {
                    "supported_motherboard_form_factors": ["ATX"],
                    "max_gpu_length_mm": 340,
                    "max_cpu_cooler_height_mm": 165,
                    "psu_form_factor_supported": ["ATX"],
                },
            )
        ],
    }


def test_diagnose_detects_structured_hard_incompatibilities():
    cpu = _product("处理器", "cpu", "AM5 CPU", 1500, {"socket": "AM5", "tdp_w": 120})
    mb = _product("主板", "mb", "LGA1700 主板", 1000, {"socket": "LGA1700", "memory_type": "DDR5", "form_factor": "ATX"})
    ram = _product("内存", "ram", "DDR4 16G", 300, {"memory_type": "DDR4"})
    gpu = _product("显卡", "gpu", "长显卡", 3000, {"gpu_length_mm": 360, "tbp_w": 320, "recommended_psu_w": 850})
    psu = _product("电源", "psu", "550W 电源", 300, {"wattage_w": 550, "form_factor": "ATX"})
    cooler = _product("散热", "cooler", "LGA only 风冷", 150, {"supported_sockets": ["LGA1700"], "cooler_height_mm": 170})
    case = _product(
        "机箱",
        "case",
        "小机箱",
        250,
        {
            "supported_motherboard_form_factors": ["M-ATX"],
            "max_gpu_length_mm": 300,
            "max_cpu_cooler_height_mm": 155,
            "psu_form_factor_supported": ["SFX"],
        },
    )

    blocking, _ = diagnose(
        {"处理器": cpu, "主板": mb, "内存": ram, "显卡": gpu, "电源": psu, "散热": cooler, "机箱": case},
        {"cpu_motherboard_rules": [], "memory_rules": [], "power_rules": []},
    )

    joined = " | ".join(blocking)
    assert "插槽" in joined or "平台" in joined
    assert "内存类型" in joined
    assert "显卡长度" in joined
    assert "电源额定功率" in joined
    assert "散热器支持的 CPU 插槽" in joined
    assert "主板板型" in joined
    assert "电源尺寸" in joined


def test_validate_and_select_rejects_invalid_structured_combo():
    parsed = _parsed()
    bad_cpu = _product("处理器", "cpu-bad", "AM5 CPU", 1500, {"socket": "AM5", "tdp_w": 120})
    bad_mb = _product("主板", "mb-bad", "LGA1700 主板", 1000, {"socket": "LGA1700", "memory_type": "DDR5", "form_factor": "ATX"})
    bad_ram = _product("内存", "ram-bad", "DDR4 16G", 300, {"memory_type": "DDR4"})
    bad_gpu = _product("显卡", "gpu-bad", "长显卡", 3000, {"gpu_length_mm": 360, "tbp_w": 320, "recommended_psu_w": 850})
    bad_psu = _product("电源", "psu-bad", "550W 电源", 300, {"wattage_w": 550, "form_factor": "ATX"})
    bad_cooler = _product("散热", "cool-bad", "LGA only 风冷", 150, {"supported_sockets": ["LGA1700"], "cooler_height_mm": 170})
    bad_case = _product(
        "机箱",
        "case-bad",
        "小机箱",
        250,
        {
            "supported_motherboard_form_factors": ["M-ATX"],
            "max_gpu_length_mm": 300,
            "max_cpu_cooler_height_mm": 155,
            "psu_form_factor_supported": ["SFX"],
        },
    )

    outcome = validate_and_select(
        parsed,
        {
            "处理器": [bad_cpu],
            "主板": [bad_mb],
            "内存": [bad_ram],
            "显卡": [bad_gpu],
            "电源": [bad_psu],
            "散热": [bad_cooler],
            "机箱": [bad_case],
        },
        rules={"cpu_motherboard_rules": [], "memory_rules": [], "power_rules": []},
    )

    assert outcome.status == "failed_with_alternative"
    assert outcome.final_build == []
    assert outcome.compatibility_check["status"] == "fail"


def test_validate_and_select_searches_for_compatible_candidate_combo():
    parsed = _parsed()
    cpu = _product("处理器", "cpu", "AM5 CPU", 1500, {"socket": "AM5", "tdp_w": 105})
    bad_mb = _product("主板", "mb-bad", "LGA1700 主板", 700, {"socket": "LGA1700", "memory_type": "DDR5", "form_factor": "ATX"})
    good_mb = _product("主板", "mb-good", "AM5 主板", 900, {"socket": "AM5", "memory_type": "DDR5", "form_factor": "ATX"})
    ram = _product("内存", "ram", "DDR5 32G", 450, {"memory_type": "DDR5"})
    gpu = _product("显卡", "gpu", "短显卡", 2800, {"gpu_length_mm": 280, "tbp_w": 220, "recommended_psu_w": 650})
    psu = _product("电源", "psu", "750W 电源", 500, {"wattage_w": 750, "form_factor": "ATX"})
    cooler = _product("散热", "cooler", "AM5 风冷", 180, {"supported_sockets": ["AM5"], "cooler_height_mm": 150})
    case = _product(
        "机箱",
        "case",
        "ATX 机箱",
        280,
        {
            "supported_motherboard_form_factors": ["ATX"],
            "max_gpu_length_mm": 340,
            "max_cpu_cooler_height_mm": 165,
            "psu_form_factor_supported": ["ATX"],
        },
    )

    outcome = validate_and_select(
        parsed,
        {
            "处理器": [cpu],
            "主板": [bad_mb, good_mb],
            "内存": [ram],
            "显卡": [gpu],
            "电源": [psu],
            "散热": [cooler],
            "机箱": [case],
        },
        rules={"cpu_motherboard_rules": [], "memory_rules": [], "power_rules": []},
    )

    assert outcome.status == "success"
    assert outcome.compatibility_check["status"] == "pass"
    assert any(line.sku_id == "mb-good" for line in outcome.final_build)


def test_diagnose_normalizes_case_form_factor_strings():
    mb = _product("主板", "mb", "M-ATX 主板", 700, {"form_factor": "Micro ATX"})
    case = _product(
        "机箱",
        "case",
        "海景房机箱",
        400,
        {"supported_motherboard_form_factors": "['ATX', 'Micro-ATX', 'Mini-ITX']"},
    )

    blocking, _ = diagnose({"主板": mb, "机箱": case}, {"cpu_motherboard_rules": [], "memory_rules": [], "power_rules": []})

    assert "主板板型与机箱支持范围不匹配" not in blocking


def test_validate_and_select_uses_remaining_budget_for_main_plan_and_adds_value_alternative():
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(min=0, max=10000)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="budget utilization",
    )

    outcome = validate_and_select(
        parsed,
        {
            "处理器": [
                _product("处理器", "cpu-base", "AM5 入门 CPU", 1000, {"socket": "AM5", "tdp_w": 65}),
                _product("处理器", "cpu-up", "AM5 高性能 CPU", 2000, {"socket": "AM5", "tdp_w": 105}),
            ],
            "主板": [_product("主板", "mb", "AM5 主板", 800, {"socket": "AM5", "memory_type": "DDR5", "form_factor": "ATX"})],
            "内存": [_product("内存", "ram", "DDR5 32G", 400, {"memory_type": "DDR5"})],
            "显卡": [
                _product("显卡", "gpu-base", "RTX 入门显卡", 2500, {"gpu_length_mm": 260, "tbp_w": 180, "recommended_psu_w": 650}),
                _product("显卡", "gpu-used", "二手拆机 RTX 性价比显卡", 3200, {"gpu_length_mm": 280, "tbp_w": 210, "recommended_psu_w": 650}),
                _product("显卡", "gpu-up", "RTX 高性能显卡", 4500, {"gpu_length_mm": 300, "tbp_w": 260, "recommended_psu_w": 750}),
            ],
            "硬盘": [_product("硬盘", "ssd", "1TB SSD", 400, {})],
            "电源": [
                _product("电源", "psu-base", "650W 电源", 400, {"wattage_w": 650, "form_factor": "ATX"}),
                _product("电源", "psu-up", "750W 电源", 550, {"wattage_w": 750, "form_factor": "ATX"}),
            ],
            "散热": [_product("散热", "cooler", "AM5 风冷", 200, {"supported_sockets": ["AM5"], "cooler_height_mm": 150, "cooling_capacity_w": 180})],
            "机箱": [
                _product(
                    "机箱",
                    "case",
                    "ATX 机箱",
                    300,
                    {
                        "supported_motherboard_form_factors": ["ATX"],
                        "max_gpu_length_mm": 340,
                        "max_cpu_cooler_height_mm": 165,
                        "psu_form_factor_supported": ["ATX"],
                    },
                )
            ],
        },
        rules={"cpu_motherboard_rules": [], "memory_rules": [], "power_rules": []},
    )

    assert outcome.status == "success"
    assert outcome.total_price >= 9000
    assert any(line.sku_id == "gpu-up" for line in outcome.final_build)
    assert any(line.sku_id == "cpu-up" for line in outcome.final_build)
    assert outcome.alternative_suggestions
    assert "性价比备选" in outcome.alternative_suggestions[0]
    assert "二手拆机" not in outcome.alternative_suggestions[0]


@pytest.mark.parametrize(
    ("max_budget", "expected_skus"),
    [
        (8000, {"gpu-mid"}),
        (12000, {"gpu-high"}),
        (15000, {"gpu-ultra", "cpu-high"}),
    ],
)
def test_validate_and_select_uses_budget_floor_across_common_budget_tiers(max_budget, expected_skus):  # noqa: ANN001
    outcome = validate_and_select(
        _budget_parsed(max_budget),
        _scalable_budget_catalog(),
        rules={"cpu_motherboard_rules": [], "memory_rules": [], "power_rules": []},
    )

    selected_skus = {line.sku_id for line in outcome.final_build}

    assert outcome.status == "success"
    assert outcome.compatibility_check["status"] == "pass"
    assert outcome.budget_check["status"] == "within_budget"
    assert outcome.total_price <= max_budget
    assert outcome.total_price >= max_budget * 0.90
    assert expected_skus <= selected_skus
