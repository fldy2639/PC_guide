from __future__ import annotations

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
