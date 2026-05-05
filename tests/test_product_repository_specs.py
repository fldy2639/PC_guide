from __future__ import annotations

import json

from pc_build_agent.models.schemas import ProductRecord
from pc_build_agent.services.product_repository import ProductRepository


def test_product_repository_loads_specs_from_real_products_json():
    repo = ProductRepository()
    items = repo.load()

    assert items
    assert any(item.specs for item in items)

    motherboard = next(item for item in items if item.category == "主板" and item.specs.get("socket"))
    assert motherboard.specs.get("socket")
    motherboard_with_memory = next(item for item in items if item.category == "主板" and item.specs.get("memory_type"))
    assert motherboard_with_memory.specs.get("memory_type")

    psu = next(item for item in items if item.category == "电源" and item.specs)
    assert isinstance(psu.specs.get("wattage_w"), (int, float))

    case = next(item for item in items if item.category == "机箱" and item.specs)
    assert case.specs.get("supported_motherboard_form_factors") is not None
    assert case.specs.get("case_style") is not None
    assert case.specs.get("color") is not None


def test_product_repository_keeps_old_records_compatible(tmp_path):
    path = tmp_path / "products.json"
    path.write_text(
        json.dumps(
            [
                {
                    "sku_id": "sku-old",
                    "category": "处理器",
                    "name": "老格式 CPU",
                    "price": 999,
                    "jd_url": None,
                    "tags": [],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repo = ProductRepository(path=path)
    items = repo.load()
    assert len(items) == 1
    assert items[0].specs == {}
    assert items[0].current_price == 999


def test_product_record_defaults_remain_backward_compatible():
    record = ProductRecord(sku_id="x", category="显卡", name="旧显卡", price=1234, tags=[])
    assert record.specs == {}
    assert record.current_price is None
