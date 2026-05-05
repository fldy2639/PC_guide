#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_PATH = ROOT / "pc_build_agent" / "data" / "products.json"
OUT_DIR = ROOT / "pc_build_agent" / "database" / "hardware_catalog" / "v1" / "data"

COMMON_KEYS = {
    "id",
    "sku_id",
    "category",
    "component_type",
    "brand",
    "model",
    "name",
    "price",
    "current_price",
    "jd_url",
    "tags",
}

CATEGORY_MAP = {
    "处理器": ("cpu.json", "cpu", "cpu", "处理器"),
    "显卡": ("gpu.json", "gpu", "gpu", "显卡"),
    "主板": ("motherboard.json", "motherboard", "motherboard", "主板"),
    "内存": ("ram.json", "memory", "ram", "内存"),
    "硬盘": ("ssd.json", "ssd", "ssd", "硬盘"),
    "散热": ("cooling.json", "cooling", "cooling", "散热"),
    "电源": ("psu.json", "psu", "psu", "电源"),
    "机箱": ("case.json", "case", "case", "机箱"),
}

NUMERIC_KEYS = {
    "current_price",
    "tdp_w",
    "tbp_w",
    "recommended_psu_w",
    "wattage_w",
    "gpu_length_mm",
    "max_gpu_length_mm",
    "max_cpu_cooler_height_mm",
    "cooler_height_mm",
    "radiator_size_mm",
    "cooling_capacity_w",
    "capacity_gb",
    "speed_mhz",
    "cpu_single_core_score",
    "cpu_multi_core_score",
    "gpu_performance_score",
    "ai_score",
    "gaming_score",
    "ssd_performance_score",
    "endurance_score",
    "airflow_score",
    "noise_score",
    "cores",
    "threads",
    "ram_slots",
    "m2_slots",
    "module_count",
    "vram_gb",
    "slot_width",
}


def _convert_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text == "是":
        return True
    if text == "否":
        return False
    if text == "":
        return value
    if any(sep in text for sep in ["/", "|"]) or text.upper() in {"ATX", "M-ATX", "ITX", "SFX", "SFX-L"}:
        return value
    try:
        if "." in text:
            number = float(text)
            return int(number) if number.is_integer() else number
        return int(text)
    except ValueError:
        return value


def normalize_spec_values(spec: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (spec or {}).items():
        if key in NUMERIC_KEYS:
            normalized[key] = _convert_value(value)
        elif isinstance(value, list):
            normalized[key] = [_convert_value(item) for item in value]
        else:
            normalized[key] = _convert_value(value)
    return normalized


def extract_spec_from_tags(tags: list[str]) -> tuple[dict[str, Any], list[str]]:
    clean_tags: list[str] = []
    extracted: dict[str, Any] = {}
    for tag in tags or []:
        if isinstance(tag, str) and tag.startswith("__spec:"):
            raw_spec = tag[len("__spec:") :].strip()
            if raw_spec:
                try:
                    data = json.loads(raw_spec)
                    if isinstance(data, dict):
                        extracted = data
                except Exception:
                    extracted = {}
            continue
        clean_tags.append(tag)
    return normalize_spec_values(extracted), clean_tags


def build_item(product: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    category = product.get("category")
    mapping = CATEGORY_MAP.get(str(category))
    if not mapping:
        return None

    filename, component_type, english_category, category_cn = mapping
    spec, clean_tags = extract_spec_from_tags(list(product.get("tags") or []))
    price = _convert_value(product.get("price"))
    current_price = spec.get("current_price")
    if not isinstance(current_price, (int, float)):
        current_price = price
    brand = str(spec.get("brand") or "")

    item: dict[str, Any] = {
        "id": str(product.get("sku_id") or ""),
        "sku_id": str(product.get("sku_id") or ""),
        "category": category_cn,
        "component_type": component_type,
        "brand": brand,
        "model": str(product.get("name") or ""),
        "name": str(product.get("name") or ""),
        "price": float(price or 0),
        "current_price": float(current_price or 0),
        "jd_url": product.get("jd_url"),
        "tags": clean_tags,
    }
    for key, value in spec.items():
        if key in {"current_price", "brand", "component_type", "品类中文"}:
            continue
        item[key] = value
    return filename, english_category, item


def main() -> None:
    raw = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
    buckets: dict[str, dict[str, Any]] = {}
    for _, _, english_category, category_cn in CATEGORY_MAP.values():
        buckets[english_category] = {
            "catalog_version": "v1",
            "category": english_category,
            "category_cn": category_cn,
            "items": [],
        }

    for product in raw:
        built = build_item(product)
        if built is None:
            continue
        _, english_category, item = built
        buckets[english_category]["items"].append(item)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reverse_map = {value[2]: value[0] for value in CATEGORY_MAP.values()}
    for english_category, payload in buckets.items():
        path = OUT_DIR / reverse_map[english_category]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{path.name}: {len(payload['items'])}")


if __name__ == "__main__":
    main()
