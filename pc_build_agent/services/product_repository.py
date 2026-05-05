from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pc_build_agent.config import settings
from pc_build_agent.models.schemas import ProductRecord


CATALOG_FILES = [
    "cpu.json",
    "gpu.json",
    "motherboard.json",
    "ram.json",
    "ssd.json",
    "cooling.json",
    "psu.json",
    "case.json",
]

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

NUMERIC_SPEC_FIELDS = {
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


def _to_number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
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
        if key in NUMERIC_SPEC_FIELDS:
            normalized[key] = _to_number(value)
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "是":
                normalized[key] = True
                continue
            if stripped == "否":
                normalized[key] = False
                continue
        if isinstance(value, list):
            normalized[key] = [_to_number(item) for item in value]
        else:
            normalized[key] = value
    return normalized


class ProductRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or settings.pc_guide_hardware_catalog_path)
        self._items: list[ProductRecord] | None = None

    def _load_catalog_file(self, path: Path) -> list[dict[str, Any]]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            items = raw.get("items") or []
            return items if isinstance(items, list) else []
        if isinstance(raw, list):
            return raw
        return []

    def _build_product_record(self, item: dict[str, Any]) -> ProductRecord:
        normalized_item = normalize_spec_values(dict(item))
        specs = {key: value for key, value in normalized_item.items() if key not in COMMON_KEYS}
        current_price = normalized_item.get("current_price")
        if not isinstance(current_price, (int, float)):
            current_price = normalized_item.get("price")
        payload = {
            "sku_id": str(normalized_item.get("sku_id") or normalized_item.get("id") or ""),
            "category": str(normalized_item.get("category") or ""),
            "name": str(normalized_item.get("name") or normalized_item.get("model") or ""),
            "price": float(normalized_item.get("price") or normalized_item.get("current_price") or 0),
            "jd_url": normalized_item.get("jd_url"),
            "tags": list(normalized_item.get("tags") or []),
            "specs": specs,
            "component_type": normalized_item.get("component_type"),
            "brand": normalized_item.get("brand"),
            "current_price": current_price,
        }
        if hasattr(ProductRecord, "model_validate"):
            return ProductRecord.model_validate(payload)
        return ProductRecord.parse_obj(payload)

    def load(self) -> list[ProductRecord]:
        if self._items is None:
            items: list[ProductRecord] = []
            if self.path.is_file():
                for item in self._load_catalog_file(self.path):
                    items.append(self._build_product_record(item))
            else:
                for filename in CATALOG_FILES:
                    file_path = self.path / filename
                    if not file_path.exists():
                        continue
                    for item in self._load_catalog_file(file_path):
                        items.append(self._build_product_record(item))
            self._items = items
        return self._items

    def by_category(self, category: str) -> list[ProductRecord]:
        return [p for p in self.load() if p.category == category]

    def all_categories(self) -> list[str]:
        seen: list[str] = []
        for p in self.load():
            if p.category not in seen:
                seen.append(p.category)
        return seen


def get_product_repository() -> ProductRepository:
    return ProductRepository()
