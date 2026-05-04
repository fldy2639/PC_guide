from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pc_build_agent.config import settings
from pc_build_agent.models.schemas import ProductRecord


def extract_intel_model(name: str) -> str | None:
    m = re.search(r"(i\d-\d{4,5}[A-Z]*)", name, re.I)
    return m.group(1).upper().replace("İ", "I") if m else None


def extract_amd_model(name: str) -> str | None:
    m = re.search(r"(Ryzen\s*\d\s*\d{4}[A-Z]?|R\d\s*\d{4}F?|Ryzen\s*\d\s*\d{4}G)", name, re.I)
    return m.group(1).replace(" ", " ") if m else None


def motherboard_ddr(name: str) -> str | None:
    if "DDR5" in name.upper().replace("ddr5", "DDR5"):
        return "DDR5"
    if "DDR4" in name.upper():
        return "DDR4"
    return None


def memory_ddr(name: str) -> str | None:
    u = name.upper()
    if "DDR5" in u:
        return "DDR5"
    if "DDR4" in u:
        return "DDR4"
    return None


def extract_psu_watts(name: str) -> int | None:
    m = re.search(r"(\d{3,4})\s*W", name.upper())
    if not m:
        return None
    return int(m.group(1))


def is_integrated_gpu_placeholder(gpu: ProductRecord) -> bool:
    return gpu.price <= 0 or ("无需独立显卡" in gpu.name) or ("核显办公" in gpu.name)


def cooler_has_360(name: str) -> bool:
    return bool(re.search(r"360", name)) and ("水冷" in name or "一体" in name)


def case_supports_360(case_name: str, tags: list[str]) -> bool:
    if "360冷排" in tags:
        return True
    return ("360" in case_name) and ("海景房" in case_name or "支持" in case_name or "水冷" in case_name)


def is_k_series_cpu(name: str) -> bool:
    return bool(re.search(r"i\d-\d{4,5}KF|i\d-\d{4,5}K\b", name.upper()))


def load_rules(path: Path | None = None) -> dict[str, Any]:
    p = Path(path or settings.pc_guide_rules_path)
    return json.loads(p.read_text(encoding="utf-8"))


def gpu_matches_rule(gpu_name: str, pattern: str) -> bool:
    return bool(re.search(pattern, gpu_name, re.I))


def motherboard_chipsets_visible(mb_name: str) -> list[str]:
    hits = []
    for chip in ["Z790", "B760", "H610", "H670", "B660", "Z690", "X670", "B650", "A620", "X570", "B550", "A520"]:
        if chip in mb_name.upper():
            hits.append(chip)
    return hits
