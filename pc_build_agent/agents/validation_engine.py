from __future__ import annotations

import re
from dataclasses import dataclass
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
        if not _cpu_mb_ok(cpu.name, mb.name, rules.get("cpu_motherboard_rules") or []):
            blocking.append("CPU 与主板芯片组/平台可能不匹配")

    if mb and ram:
        ok, msg = _ddr_ok(mb.name, ram.name, rules.get("memory_rules") or [])
        if not ok and msg:
            blocking.append(msg)

    if gpu and psu:
        min_w, rec_w = _required_psu_watts(gpu, rules.get("power_rules") or [])
        got = extract_psu_watts(psu.name)
        if got is None:
            warnings.append("无法在电源型号中解析额定功率，建议人工核对功耗余量。")
        elif got < min_w:
            blocking.append(f"电源额定功率可能不足（当前约 {got}W，建议不低于 {min_w}W）")
        elif got < rec_w:
            warnings.append(f"电源可用但余量一般（当前约 {got}W，更稳妥可选择约 {rec_w}W）")

    if cooler and case:
        if cooler_has_360(cooler.name) and not case_supports_360(case.name, case.tags):
            blocking.append("360 一体式水冷与机箱冷排支持不匹配（机箱可能无法安装 360 冷排）")

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

    idx: dict[str, int] = {cat: 0 for cat in sorted_by_category}

    def parts_now() -> dict[str, ProductRecord]:
        return {c: sorted_by_category[c][idx[c]] for c in sorted_by_category}

    # --- 兼容性修复（带索引推进）---
    for _ in range(600):
        parts = parts_now()
        blocking, warns = diagnose(parts, rules)
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
                    idx["内存"] = _sku_index(ram_list, pick.sku_id)
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
                        idx["主板"] = _sku_index(mb_list, pick_mb.sku_id)
                        progressed = True

        elif any("CPU 与主板" in b or "平台" in b for b in blocking):
            if "主板" not in locked_cat:
                mb_list = sorted_by_category["主板"]
                cpu_name = parts["处理器"].name
                pick_mb = _pick_cheapest_mb_for_cpu(mb_list, cpu_name, rules)
                if pick_mb:
                    idx["主板"] = _sku_index(mb_list, pick_mb.sku_id)
                    progressed = True

        elif any("电源额定功率" in b for b in blocking):
            gpu = parts["显卡"]
            min_w, _ = _required_psu_watts(gpu, rules.get("power_rules") or [])
            psu_list = sorted_by_category["电源"]
            pick_psu = _pick_cheapest_psu_meeting(psu_list, min_w)
            if pick_psu and "电源" not in locked_cat:
                idx["电源"] = _sku_index(psu_list, pick_psu.sku_id)
                progressed = True

        elif any("360" in b for b in blocking):
            if "机箱" not in locked_cat:
                case_list = sorted_by_category["机箱"]
                cooler_name = parts["散热"].name
                suitable = [p for p in case_list if case_supports_360(p.name, p.tags)]
                pool = suitable if suitable else case_list
                pool.sort(key=lambda p: p.price)
                pick_case = pool[0]
                idx["机箱"] = _sku_index(case_list, pick_case.sku_id)
                progressed = True
            elif "散热" not in locked_cat:
                cool_list = sorted_by_category["散热"]
                safe = [p for p in cool_list if not cooler_has_360(p.name)]
                if safe:
                    safe.sort(key=lambda p: p.price)
                    pick_c = safe[0]
                    idx["散热"] = _sku_index(cool_list, pick_c.sku_id)
                    progressed = True

        if not progressed:
            break

    parts = parts_now()
    blocking, warns = diagnose(parts, rules)
    if blocking:
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
        )

    # --- 预算降配：>15% 超预算必须持续降配；禁止把「明显超标」组合当作最终方案 ---
    downgrade_order = ["显示器", "显卡", "处理器", "内存", "硬盘", "散热", "机箱", "风扇", "主板", "电源"]
    display_order = ["处理器", "散热", "主板", "显卡", "内存", "硬盘", "机箱", "电源", "风扇", "显示器"]

    parts = parts_now()

    if budget_max is not None:
        mx = float(budget_max)

        for _ in range(2500):
            parts = parts_now()
            total = _total_price(parts)
            if total <= mx * 1.15:
                break

            moved = False
            for cat in downgrade_order:
                if cat not in sorted_by_category:
                    continue
                if cat in locked_cat:
                    continue
                lst = sorted_by_category[cat]
                if idx[cat] + 1 >= len(lst):
                    continue

                before_cat = idx[cat]
                psu_before = idx.get("电源", 0)

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

                moved = True
                break

            if not moved:
                break

        for _ in range(2500):
            parts = parts_now()
            total = _total_price(parts)
            if total <= mx:
                break

            moved = False
            for cat in downgrade_order:
                if cat not in sorted_by_category:
                    continue
                if cat in locked_cat:
                    continue
                lst = sorted_by_category[cat]
                if idx[cat] + 1 >= len(lst):
                    continue

                before_cat = idx[cat]
                psu_before = idx.get("电源", 0)

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

                moved = True
                break

            if not moved:
                break

    parts = parts_now()
    blocking_final, warns = diagnose(parts, rules)
    total = _total_price(parts)

    if blocking_final:
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
        )

    budget_state = "within_budget"
    need_confirm = False
    if budget_max is not None:
        mx = float(budget_max)
        if total > mx * 1.15:
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
    )
