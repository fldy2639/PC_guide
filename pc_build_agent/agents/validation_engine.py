from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pc_build_agent.agents.hardware import (
    cooler_has_360,
    case_supports_360,
    extract_psu_watts,
    gpu_matches_rule,
    is_integrated_gpu_placeholder,
    is_k_series_cpu,
    load_rules,
    memory_ddr,
    motherboard_ddr,
)
from pc_build_agent.agents.selection import specified_hard_map
from pc_build_agent.models.schemas import BuildLine, ParsedRequirements, ProductRecord


@dataclass
class ValidationOutcome:
    status: str
    final_build: list[BuildLine]
    total_price: float
    budget_check: dict[str, Any]
    compatibility_check: dict[str, Any]
    risk_check: dict[str, Any]
    unmet_constraints: list[str]
    alternative_suggestions: list[str]
    debug: dict[str, Any] = field(default_factory=dict)


def _part_snapshot(part: ProductRecord | None) -> dict[str, Any] | None:
    if part is None:
        return None
    return {
        "sku_id": part.sku_id,
        "name": part.name,
        "price": part.price,
        "component_type": part.component_type,
        "specs": dict(part.specs or {}),
    }


def _parts_snapshot(parts: dict[str, ProductRecord]) -> dict[str, Any]:
    return {category: _part_snapshot(part) for category, part in parts.items()}


def _required_psu_watts(gpu: ProductRecord, power_rules: list[dict[str, Any]]) -> tuple[int, int]:
    if is_integrated_gpu_placeholder(gpu):
        return 300, 400
    name = gpu.name
    best_min = 450
    best_rec = 550
    matched = False
    ordered = sorted(power_rules, key=lambda r: len(r.get("gpu_pattern", "")), reverse=True)
    for rule in ordered:
        pat = rule.get("gpu_pattern", "")
        if not pat:
            continue
        if gpu_matches_rule(name, pat):
            best_min = int(rule.get("min_psu_watt", best_min))
            best_rec = int(rule.get("recommended_psu_watt", best_rec))
            matched = True
            break
    if not matched:
        return 550, 650
    return best_min, best_rec


def _cpu_mb_ok(cpu_name: str, mb_name: str, cpu_mb_rules: list[dict[str, Any]]) -> bool:
    for rule in cpu_mb_rules:
        pat = rule.get("cpu_pattern", "")
        allowed = rule.get("allowed_motherboard_patterns") or []
        if not pat:
            continue
        if re.search(pat, cpu_name, re.I):
            return any(chip in mb_name.upper() for chip in allowed)
    return True


def _ddr_ok(mb_name: str, ram_name: str, mem_rules: list[dict[str, Any]]) -> tuple[bool, str | None]:
    md = motherboard_ddr(mb_name)
    rd = memory_ddr(ram_name)
    if md and rd:
        return md == rd, f"内存类型与主板不一致（主板:{md}，内存:{rd}）"
    return True, None


def _spec_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.replace("，", "/").replace(",", "/").replace("|", "/")
        return [part.strip().upper() for part in text.split("/") if part.strip()]
    return []


def _spec_socket_ok(cpu: ProductRecord, mb: ProductRecord) -> bool | None:
    cpu_socket = (cpu.specs or {}).get("socket")
    mb_socket = (mb.specs or {}).get("socket")
    if cpu_socket and mb_socket:
        return str(cpu_socket).upper() == str(mb_socket).upper()
    return None


def _spec_memory_ok(mb: ProductRecord, ram: ProductRecord) -> tuple[bool, str | None] | None:
    mb_type = (mb.specs or {}).get("memory_type")
    ram_type = (ram.specs or {}).get("memory_type")
    if mb_type and ram_type:
        ok = str(mb_type).upper() == str(ram_type).upper()
        return ok, None if ok else f"内存类型与主板不一致（主板:{mb_type}，内存:{ram_type}）"
    return None


def _spec_psu_ok(cpu: ProductRecord | None, gpu: ProductRecord, psu: ProductRecord) -> tuple[bool, str | None, str | None] | None:
    wattage = (psu.specs or {}).get("wattage_w")
    if not isinstance(wattage, (int, float)):
        return None
    gpu_rec = (gpu.specs or {}).get("recommended_psu_w")
    if isinstance(gpu_rec, (int, float)):
        if float(wattage) < float(gpu_rec):
            return False, f"电源额定功率可能不足（当前约 {int(wattage)}W，建议不低于 {int(gpu_rec)}W）", None
        return True, None, None
    cpu_tdp = (cpu.specs or {}).get("tdp_w") if cpu else None
    gpu_tbp = (gpu.specs or {}).get("tbp_w")
    if isinstance(cpu_tdp, (int, float)) or isinstance(gpu_tbp, (int, float)):
        need = 150.0
        if isinstance(cpu_tdp, (int, float)):
            need += float(cpu_tdp)
        if isinstance(gpu_tbp, (int, float)):
            need += float(gpu_tbp)
        if float(wattage) < need:
            return False, f"电源额定功率可能不足（当前约 {int(wattage)}W，建议不低于 {int(need)}W）", None
        if float(wattage) < need + 100:
            return True, None, f"电源可用但余量一般（当前约 {int(wattage)}W，建议预留更多功率余量）"
        return True, None, None
    return None


def _spec_gpu_case_ok(gpu: ProductRecord, case: ProductRecord) -> tuple[bool, str | None] | None:
    gpu_len = (gpu.specs or {}).get("gpu_length_mm")
    max_len = (case.specs or {}).get("max_gpu_length_mm")
    if isinstance(gpu_len, (int, float)) and isinstance(max_len, (int, float)):
        ok = float(gpu_len) <= float(max_len)
        return ok, None if ok else "显卡长度与机箱显卡限长不匹配"
    return None


def _spec_cooler_cpu_ok(cpu: ProductRecord, cooler: ProductRecord) -> tuple[bool, str | None] | None:
    cpu_socket = (cpu.specs or {}).get("socket")
    supported = _spec_list((cooler.specs or {}).get("supported_sockets"))
    if cpu_socket and supported:
        if str(cpu_socket).upper() in supported:
            return True, None
        return False, "散热器支持的 CPU 插槽与处理器不匹配"
    cooling_capacity = (cooler.specs or {}).get("cooling_capacity_w")
    cpu_tdp = (cpu.specs or {}).get("tdp_w")
    if isinstance(cooling_capacity, (int, float)) and isinstance(cpu_tdp, (int, float)):
        ok = float(cooling_capacity) >= float(cpu_tdp)
        return ok, None if ok else "散热器压制能力可能不足"
    return None


def _spec_cooler_case_ok(cooler: ProductRecord, case: ProductRecord) -> tuple[bool, str | None] | None:
    cooling_type = str((cooler.specs or {}).get("cooling_type") or "")
    radiator_size = (cooler.specs or {}).get("radiator_size_mm")
    cooler_height = (cooler.specs or {}).get("cooler_height_mm")
    max_height = (case.specs or {}).get("max_cpu_cooler_height_mm")
    if "风冷" in cooling_type and isinstance(cooler_height, (int, float)) and isinstance(max_height, (int, float)):
        ok = float(cooler_height) <= float(max_height)
        return ok, None if ok else "风冷散热器高度与机箱 CPU 散热限高不匹配"
    if isinstance(radiator_size, (int, float)):
        text = f"{case.name} {' '.join(case.tags or [])} {_spec_list((case.specs or {}).get('radiator_support'))}"
        if str(int(radiator_size)) in text:
            return True, None
        return False, f"机箱可能不支持 {int(radiator_size)} 冷排"
    return None


def _spec_mb_case_ok(mb: ProductRecord, case: ProductRecord) -> tuple[bool, str | None] | None:
    form_factor = (mb.specs or {}).get("form_factor")
    supported = _spec_list((case.specs or {}).get("supported_motherboard_form_factors"))
    if form_factor and supported:
        form = str(form_factor).upper()
        ok = form in supported
        return ok, None if ok else "主板板型与机箱支持范围不匹配"
    return None


def _spec_psu_case_ok(psu: ProductRecord, case: ProductRecord) -> tuple[bool, str | None] | None:
    form_factor = (psu.specs or {}).get("form_factor")
    supported = _spec_list((case.specs or {}).get("psu_form_factor_supported"))
    if form_factor and supported:
        form = str(form_factor).upper()
        ok = form in supported
        return ok, None if ok else "电源尺寸与机箱支持范围不匹配"
    return None


def diagnose(parts: dict[str, ProductRecord], rules: dict[str, Any]) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []

    cpu = parts.get("处理器")
    mb = parts.get("主板")
    ram = parts.get("内存")
    gpu = parts.get("显卡")
    psu = parts.get("电源")
    cooler = parts.get("散热")
    case = parts.get("机箱")

    if cpu and mb:
        spec_ok = _spec_socket_ok(cpu, mb)
        if spec_ok is False:
            blocking.append("CPU 与主板插槽不匹配")
        elif spec_ok is None and not _cpu_mb_ok(cpu.name, mb.name, rules.get("cpu_motherboard_rules") or []):
            blocking.append("CPU 与主板芯片组/平台可能不匹配")

    if mb and ram:
        spec_result = _spec_memory_ok(mb, ram)
        if spec_result is not None:
            ok, msg = spec_result
            if not ok and msg:
                blocking.append(msg)
        else:
            ok, msg = _ddr_ok(mb.name, ram.name, rules.get("memory_rules") or [])
            if not ok and msg:
                blocking.append(msg)

    if gpu and psu:
        spec_psu = _spec_psu_ok(cpu, gpu, psu)
        if spec_psu is not None:
            ok, block_msg, warn_msg = spec_psu
            if not ok and block_msg:
                blocking.append(block_msg)
            elif warn_msg:
                warnings.append(warn_msg)
        else:
            min_w, rec_w = _required_psu_watts(gpu, rules.get("power_rules") or [])
            got = extract_psu_watts(psu.name)
            if got is None:
                warnings.append("无法在电源型号中解析额定功率，建议人工核对功耗余量。")
            elif got < min_w:
                blocking.append(f"电源额定功率可能不足（当前约 {got}W，建议不低于 {min_w}W）")
            elif got < rec_w:
                warnings.append(f"电源可用但余量一般（当前约 {got}W，更稳妥可选择约 {rec_w}W）")

    if gpu and case:
        spec_result = _spec_gpu_case_ok(gpu, case)
        if spec_result is not None:
            ok, msg = spec_result
            if not ok and msg:
                blocking.append(msg)

    if cpu and cooler:
        spec_result = _spec_cooler_cpu_ok(cpu, cooler)
        if spec_result is not None:
            ok, msg = spec_result
            if not ok and msg:
                blocking.append(msg)

    if cooler and case:
        spec_result = _spec_cooler_case_ok(cooler, case)
        if spec_result is not None:
            ok, msg = spec_result
            if not ok and msg:
                blocking.append(msg)
        elif cooler_has_360(cooler.name) and not case_supports_360(case.name, case.tags):
            blocking.append("360 一体式水冷与机箱冷排支持不匹配（机箱可能无法安装 360 冷排）")

    if mb and case:
        spec_result = _spec_mb_case_ok(mb, case)
        if spec_result is not None:
            ok, msg = spec_result
            if not ok and msg:
                blocking.append(msg)

    if psu and case:
        spec_result = _spec_psu_case_ok(psu, case)
        if spec_result is not None:
            ok, msg = spec_result
            if not ok and msg:
                blocking.append(msg)

    if cpu and cooler and is_k_series_cpu(cpu.name):
        cn = cooler.name
        if ("单塔" in cn or "下压" in cn) and not re.search(r"240|280|360|双塔", cn):
            warnings.append("KF/K 系列处理器功耗较高，当前散热器偏保守，长时间满载可能温度偏高。")

    return blocking, warnings


def _total_price(parts: dict[str, ProductRecord]) -> float:
    return float(sum(p.price for p in parts.values()))


def _sku_index(lst: list[ProductRecord], sku_id: str) -> int:
    for i, p in enumerate(lst):
        if p.sku_id == sku_id:
            return i
    return 0


def _candidate_pool(sorted_by_category: dict[str, list[ProductRecord]], category: str, limit: int) -> list[ProductRecord | None]:
    items = list(sorted_by_category.get(category) or [])[:limit]
    return items or [None]


def _first_compatible_build(
    sorted_by_category: dict[str, list[ProductRecord]],
    rules: dict[str, Any],
    limit: int = 8,
) -> dict[str, ProductRecord] | None:
    cpus = _candidate_pool(sorted_by_category, "处理器", limit)
    motherboards = _candidate_pool(sorted_by_category, "主板", limit)
    rams = _candidate_pool(sorted_by_category, "内存", limit)
    gpus = _candidate_pool(sorted_by_category, "显卡", limit)
    cases = _candidate_pool(sorted_by_category, "机箱", limit)
    coolers = _candidate_pool(sorted_by_category, "散热", limit)
    psus = _candidate_pool(sorted_by_category, "电源", limit)
    optional_categories = [
        category
        for category in ["硬盘", "风扇", "显示器"]
        if sorted_by_category.get(category)
    ]

    for cpu in cpus:
        for mb in motherboards:
            parts = {k: v for k, v in {"处理器": cpu, "主板": mb}.items() if v is not None}
            if diagnose(parts, rules)[0]:
                continue
            for ram in rams:
                parts = {k: v for k, v in {"处理器": cpu, "主板": mb, "内存": ram}.items() if v is not None}
                if diagnose(parts, rules)[0]:
                    continue
                for gpu in gpus:
                    parts = {k: v for k, v in {"处理器": cpu, "主板": mb, "内存": ram, "显卡": gpu}.items() if v is not None}
                    if diagnose(parts, rules)[0]:
                        continue
                    for case in cases:
                        parts = {k: v for k, v in {"处理器": cpu, "主板": mb, "内存": ram, "显卡": gpu, "机箱": case}.items() if v is not None}
                        if diagnose(parts, rules)[0]:
                            continue
                        for cooler in coolers:
                            parts = {
                                k: v
                                for k, v in {
                                    "处理器": cpu,
                                    "主板": mb,
                                    "内存": ram,
                                    "显卡": gpu,
                                    "机箱": case,
                                    "散热": cooler,
                                }.items()
                                if v is not None
                            }
                            if diagnose(parts, rules)[0]:
                                continue
                            for psu in psus:
                                parts = {
                                    k: v
                                    for k, v in {
                                        "处理器": cpu,
                                        "主板": mb,
                                        "内存": ram,
                                        "显卡": gpu,
                                        "机箱": case,
                                        "散热": cooler,
                                        "电源": psu,
                                    }.items()
                                    if v is not None
                                }
                                if diagnose(parts, rules)[0]:
                                    continue
                                for category in optional_categories:
                                    parts[category] = sorted_by_category[category][0]
                                return parts
    return None


def _pick_cheapest_psu_meeting(psus: list[ProductRecord], min_w: int) -> ProductRecord | None:
    candidates = []
    for p in psus:
        w = extract_psu_watts(p.name)
        if w is None:
            continue
        if w >= min_w:
            candidates.append((float(p.price), w, p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], -x[1]))
    return candidates[0][2]


def _pick_cheapest_ram_ddr(rams: list[ProductRecord], ddr: str) -> ProductRecord | None:
    ok = [p for p in rams if memory_ddr(p.name) == ddr]
    if not ok:
        return None
    ok.sort(key=lambda p: p.price)
    return ok[0]


def _pick_cheapest_mb_for_cpu(mbs: list[ProductRecord], cpu_name: str, rules: dict[str, Any]) -> ProductRecord | None:
    ok = [p for p in mbs if _cpu_mb_ok(cpu_name, p.name, rules.get("cpu_motherboard_rules") or [])]
    pool = ok if ok else list(mbs)
    pool.sort(key=lambda p: p.price)
    return pool[0]


def _pick_cheapest_mb_for_cpu_part(mbs: list[ProductRecord], cpu: ProductRecord, rules: dict[str, Any]) -> ProductRecord | None:
    cpu_socket = (cpu.specs or {}).get("socket")
    if cpu_socket:
        compatible = [
            p for p in mbs
            if (p.specs or {}).get("socket") and str((p.specs or {}).get("socket")).upper() == str(cpu_socket).upper()
        ]
        if compatible:
            compatible.sort(key=lambda p: p.price)
            return compatible[0]
    return _pick_cheapest_mb_for_cpu(mbs, cpu.name, rules)


def validate_and_select(
    parsed: ParsedRequirements,
    sorted_by_category: dict[str, list[ProductRecord]],
    rules: dict[str, Any] | None = None,
) -> ValidationOutcome:
    rules = rules or load_rules()
    budget_max = parsed.requirements.budget.max if parsed.requirements.budget else None
    budget_min = parsed.requirements.budget.min if parsed.requirements.budget else None

    hard = specified_hard_map(parsed)
    locked_cat = set(hard.keys())
    validation_debug = {
        "initial_parts": {},
        "diagnose_steps": [],
        "fix_steps": [],
        "budget_steps": [],
        "final_parts": {},
        "final_status": None,
        "final_issues": [],
    }

    idx: dict[str, int] = {cat: 0 for cat, items in sorted_by_category.items() if items}

    def parts_now() -> dict[str, ProductRecord]:
        return {c: sorted_by_category[c][idx[c]] for c in idx if sorted_by_category.get(c)}

    def apply_parts(parts: dict[str, ProductRecord]) -> None:
        for category, part in parts.items():
            if category in sorted_by_category:
                idx[category] = _sku_index(sorted_by_category[category], part.sku_id)

    # --- 兼容性修复（带索引推进）---
    iteration = 0
    for _ in range(600):
        iteration += 1
        parts = parts_now()
        blocking, warns = diagnose(parts, rules)
        if not validation_debug["initial_parts"]:
            validation_debug["initial_parts"] = _parts_snapshot(parts)
        validation_debug["diagnose_steps"].append(
            {
                "iteration": iteration,
                "issues": list(blocking),
                "warnings": list(warns),
                "parts": _parts_snapshot(parts),
            }
        )
        if not blocking:
            break

        progressed = False

        if any("内存类型" in b for b in blocking):
            mb = parts["主板"]
            ddr = motherboard_ddr(mb.name)
            ram_list = sorted_by_category["内存"]
            if ddr:
                pick = _pick_cheapest_ram_ddr(ram_list, ddr)
                if pick:
                    before_part = parts.get("内存")
                    idx["内存"] = _sku_index(ram_list, pick.sku_id)
                    validation_debug["fix_steps"].append(
                        {
                            "iteration": iteration,
                            "issue": next((item for item in blocking if "内存类型" in item), blocking[0]),
                            "action": "replace memory",
                            "before": _part_snapshot(before_part),
                            "after": _part_snapshot(pick),
                        }
                    )
                    progressed = True
            if not progressed:
                mb_list = sorted_by_category["主板"]
                ram = parts["内存"]
                rd = memory_ddr(ram.name)
                if rd:
                    cand_mbs = [p for p in mb_list if motherboard_ddr(p.name) == rd]
                    if cand_mbs:
                        cand_mbs.sort(key=lambda p: p.price)
                        pick_mb = cand_mbs[0]
                        before_part = parts.get("主板")
                        idx["主板"] = _sku_index(mb_list, pick_mb.sku_id)
                        validation_debug["fix_steps"].append(
                            {
                                "iteration": iteration,
                                "issue": next((item for item in blocking if "内存类型" in item), blocking[0]),
                                "action": "replace motherboard",
                                "before": _part_snapshot(before_part),
                                "after": _part_snapshot(pick_mb),
                            }
                        )
                        progressed = True

        elif any("CPU 与主板" in b or "平台" in b for b in blocking):
            if "主板" not in locked_cat:
                mb_list = sorted_by_category["主板"]
                pick_mb = _pick_cheapest_mb_for_cpu_part(mb_list, parts["处理器"], rules)
                if pick_mb:
                    before_part = parts.get("主板")
                    before_idx = idx["主板"]
                    next_idx = _sku_index(mb_list, pick_mb.sku_id)
                    idx["主板"] = next_idx
                    validation_debug["fix_steps"].append(
                        {
                            "iteration": iteration,
                            "issue": next((item for item in blocking if "CPU 与主板" in item or "平台" in item), blocking[0]),
                            "action": "replace motherboard",
                            "before": _part_snapshot(before_part),
                            "after": _part_snapshot(pick_mb),
                        }
                    )
                    progressed = next_idx != before_idx

        elif any("电源额定功率" in b for b in blocking):
            gpu = parts["显卡"]
            min_w, _ = _required_psu_watts(gpu, rules.get("power_rules") or [])
            psu_list = sorted_by_category["电源"]
            pick_psu = _pick_cheapest_psu_meeting(psu_list, min_w)
            if pick_psu and "电源" not in locked_cat:
                before_part = parts.get("电源")
                idx["电源"] = _sku_index(psu_list, pick_psu.sku_id)
                validation_debug["fix_steps"].append(
                    {
                        "iteration": iteration,
                        "issue": next((item for item in blocking if "电源额定功率" in item), blocking[0]),
                        "action": "replace psu",
                        "before": _part_snapshot(before_part),
                        "after": _part_snapshot(pick_psu),
                    }
                )
                progressed = True

        elif any("360" in b for b in blocking):
            if "机箱" not in locked_cat:
                case_list = sorted_by_category["机箱"]
                cooler_name = parts["散热"].name
                suitable = [p for p in case_list if case_supports_360(p.name, p.tags)]
                pool = suitable if suitable else case_list
                pool.sort(key=lambda p: p.price)
                pick_case = pool[0]
                before_part = parts.get("机箱")
                idx["机箱"] = _sku_index(case_list, pick_case.sku_id)
                validation_debug["fix_steps"].append(
                    {
                        "iteration": iteration,
                        "issue": next((item for item in blocking if "360" in item), blocking[0]),
                        "action": "replace case",
                        "before": _part_snapshot(before_part),
                        "after": _part_snapshot(pick_case),
                    }
                )
                progressed = True
            elif "散热" not in locked_cat:
                cool_list = sorted_by_category["散热"]
                safe = [p for p in cool_list if not cooler_has_360(p.name)]
                if safe:
                    safe.sort(key=lambda p: p.price)
                    pick_c = safe[0]
                    before_part = parts.get("散热")
                    idx["散热"] = _sku_index(cool_list, pick_c.sku_id)
                    validation_debug["fix_steps"].append(
                        {
                            "iteration": iteration,
                            "issue": next((item for item in blocking if "360" in item), blocking[0]),
                            "action": "replace cooling",
                            "before": _part_snapshot(before_part),
                            "after": _part_snapshot(pick_c),
                        }
                    )
                    progressed = True

        if not progressed:
            compatible_parts = _first_compatible_build(sorted_by_category, rules)
            if compatible_parts:
                apply_parts(compatible_parts)
                validation_debug["fix_steps"].append(
                    {
                        "iteration": iteration,
                        "issue": "compatibility_search",
                        "action": "replace build with first compatible candidate combination",
                        "after": _parts_snapshot(compatible_parts),
                    }
                )
                progressed = True

        if not progressed:
            break

    parts = parts_now()
    blocking, warns = diagnose(parts, rules)
    validation_debug["diagnose_steps"].append(
        {
            "iteration": iteration + 1,
            "issues": list(blocking),
            "warnings": list(warns),
            "parts": _parts_snapshot(parts),
        }
    )
    if blocking:
        validation_debug["final_parts"] = _parts_snapshot(parts)
        validation_debug["final_status"] = "failed_with_alternative"
        validation_debug["final_issues"] = list(blocking)
        return ValidationOutcome(
            status="failed_with_alternative",
            final_build=[],
            total_price=_total_price(parts),
            budget_check={"status": "unknown"},
            compatibility_check={"status": "fail", "warnings": blocking},
            risk_check={"status": "fail", "warnings": warns},
            unmet_constraints=["compatibility"],
            alternative_suggestions=[
                "尝试放宽指定机型约束或更换平台组合。",
                "降低显卡/处理器档位以减少主板与电源耦合约束。",
            ],
            debug=validation_debug,
        )

    # --- 预算降配：>15% 超预算必须持续降配；禁止把「明显超标」组合当作最终方案 ---
    downgrade_order = ["显示器", "显卡", "处理器", "内存", "硬盘", "散热", "机箱", "风扇", "主板", "电源"]
    display_order = ["处理器", "散热", "主板", "显卡", "内存", "硬盘", "机箱", "电源", "风扇", "显示器"]

    parts = parts_now()

    if budget_max is not None:
        mx = float(budget_max)

        budget_iteration = 0
        for _ in range(2500):
            budget_iteration += 1
            parts = parts_now()
            total = _total_price(parts)
            if total <= mx * 1.15:
                break

            moved = False
            for cat in downgrade_order:
                if cat not in sorted_by_category:
                    continue
                if cat not in idx:
                    continue
                if cat in locked_cat:
                    continue
                lst = sorted_by_category[cat]
                if idx[cat] + 1 >= len(lst):
                    continue

                before_cat = idx[cat]
                psu_before = idx.get("电源", 0)
                before_parts = parts_now()
                before_total = _total_price(before_parts)
                before_part = before_parts.get(cat)

                idx[cat] += 1
                trial = parts_now()
                b2, _ = diagnose(trial, rules)
                if b2:
                    idx[cat] = before_cat
                    continue

                gpu = trial.get("显卡")
                psu = trial.get("电源")
                if gpu and psu:
                    min_w, _ = _required_psu_watts(gpu, rules.get("power_rules") or [])
                    got = extract_psu_watts(psu.name)
                    if got is not None and got < min_w:
                        psu_list = sorted_by_category["电源"]
                        pick_psu = _pick_cheapest_psu_meeting(psu_list, min_w)
                        if pick_psu and "电源" not in locked_cat:
                            idx["电源"] = _sku_index(psu_list, pick_psu.sku_id)
                            trial2 = parts_now()
                            b3, _ = diagnose(trial2, rules)
                            if b3:
                                idx[cat] = before_cat
                                idx["电源"] = psu_before
                                continue
                        else:
                            idx[cat] = before_cat
                            idx["电源"] = psu_before
                            continue

                after_parts = parts_now()
                validation_debug["budget_steps"].append(
                    {
                        "iteration": budget_iteration,
                        "total_before": before_total,
                        "total_after": _total_price(after_parts),
                        "budget_max": budget_max,
                        "category": cat,
                        "before": _part_snapshot(before_part),
                        "after": _part_snapshot(after_parts.get(cat)),
                    }
                )
                moved = True
                break

            if not moved:
                break

        strict_budget_iteration = budget_iteration
        for _ in range(2500):
            strict_budget_iteration += 1
            parts = parts_now()
            total = _total_price(parts)
            if total <= mx:
                break

            moved = False
            for cat in downgrade_order:
                if cat not in sorted_by_category:
                    continue
                if cat not in idx:
                    continue
                if cat in locked_cat:
                    continue
                lst = sorted_by_category[cat]
                if idx[cat] + 1 >= len(lst):
                    continue

                before_cat = idx[cat]
                psu_before = idx.get("电源", 0)
                before_parts = parts_now()
                before_total = _total_price(before_parts)
                before_part = before_parts.get(cat)

                idx[cat] += 1
                trial = parts_now()
                b2, _ = diagnose(trial, rules)
                if b2:
                    idx[cat] = before_cat
                    continue

                gpu = trial.get("显卡")
                psu = trial.get("电源")
                if gpu and psu:
                    min_w, _ = _required_psu_watts(gpu, rules.get("power_rules") or [])
                    got = extract_psu_watts(psu.name)
                    if got is not None and got < min_w:
                        psu_list = sorted_by_category["电源"]
                        pick_psu = _pick_cheapest_psu_meeting(psu_list, min_w)
                        if pick_psu and "电源" not in locked_cat:
                            idx["电源"] = _sku_index(psu_list, pick_psu.sku_id)
                            trial2 = parts_now()
                            b3, _ = diagnose(trial2, rules)
                            if b3:
                                idx[cat] = before_cat
                                idx["电源"] = psu_before
                                continue
                        else:
                            idx[cat] = before_cat
                            idx["电源"] = psu_before
                            continue

                after_parts = parts_now()
                validation_debug["budget_steps"].append(
                    {
                        "iteration": strict_budget_iteration,
                        "total_before": before_total,
                        "total_after": _total_price(after_parts),
                        "budget_max": budget_max,
                        "category": cat,
                        "before": _part_snapshot(before_part),
                        "after": _part_snapshot(after_parts.get(cat)),
                    }
                )
                moved = True
                break

            if not moved:
                break

    parts = parts_now()
    blocking_final, warns = diagnose(parts, rules)
    if blocking_final:
        compatible_parts = _first_compatible_build(sorted_by_category, rules, limit=12)
        if compatible_parts:
            apply_parts(compatible_parts)
            parts = parts_now()
            blocking_final, warns = diagnose(parts, rules)
            validation_debug["fix_steps"].append(
                {
                    "iteration": iteration + 1,
                    "issue": "final_compatibility_search",
                    "action": "replace build with compatible candidate combination",
                    "after": _parts_snapshot(parts),
                }
            )
    total = _total_price(parts)
    validation_debug["final_parts"] = _parts_snapshot(parts)
    validation_debug["final_issues"] = list(blocking_final)

    if blocking_final:
        validation_debug["final_status"] = "failed_with_alternative"
        return ValidationOutcome(
            status="failed_with_alternative",
            final_build=[],
            total_price=total,
            budget_check={"status": "unknown"},
            compatibility_check={"status": "fail", "warnings": blocking_final},
            risk_check={"status": "fail", "warnings": warns},
            unmet_constraints=["compatibility"],
            alternative_suggestions=[
                "当前组合在预算/兼容性约束下难以闭环，请放宽指定机型或调整平台搭配。",
            ],
            debug=validation_debug,
        )

    budget_state = "within_budget"
    need_confirm = False
    if budget_max is not None:
        mx = float(budget_max)
        if total > mx * 1.15:
            validation_debug["final_status"] = "failed_with_alternative"
            return ValidationOutcome(
                status="failed_with_alternative",
                final_build=[],
                total_price=total,
                budget_check={"status": "over_budget", "target_max": budget_max, "over_ratio": (total - mx) / mx},
                compatibility_check={"status": "pass", "warnings": []},
                risk_check={"status": "fail", "warnings": warns},
                unmet_constraints=["price"],
                alternative_suggestions=[
                    "提高预算上限，或明确接受降低显卡/显示器等核心件档位。",
                    "临时去掉海景房/RGB/风扇等非性能投入，优先保证显卡与电源匹配。",
                ],
                debug=validation_debug,
            )
        if total > mx:
            budget_state = "slightly_over"
            need_confirm = True
            warns.append(
                f"当前总价约为预算上限的 {total/mx:.1%}，属于小幅超预算区间；如你希望严格不超前，可继续下调显卡或显示器档位。"
            )

    if budget_min is not None and total < float(budget_min) * 0.75:
        warns.append("当前总价明显低于预算下限，若不介意可提高 SSD/散热/机箱品质以获得更好体验。")

    build_lines = [
        BuildLine(category=c, sku_id=p.sku_id, name=p.name, price=float(p.price), jd_url=p.jd_url)
        for c, p in parts.items()
    ]

    status = "success"
    if need_confirm:
        status = "need_user_confirmation"
    validation_debug["final_status"] = status

    return ValidationOutcome(
        status=status,
        final_build=sorted(
            build_lines,
            key=lambda x: display_order.index(x.category) if x.category in display_order else 99,
        ),
        total_price=total,
        budget_check={"status": budget_state, "target_max": budget_max, "target_min": budget_min},
        compatibility_check={"status": "pass", "warnings": []},
        risk_check={"status": "pass_with_notes" if warns else "pass", "warnings": warns},
        unmet_constraints=[],
        alternative_suggestions=[],
        debug=validation_debug,
    )
