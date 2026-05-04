from __future__ import annotations

import json
from pathlib import Path

from pc_build_agent.config import settings
from pc_build_agent.models.schemas import ProductRecord


class ProductRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or settings.pc_guide_products_path)
        self._items: list[ProductRecord] | None = None

    def load(self) -> list[ProductRecord]:
        if self._items is None:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = [ProductRecord.model_validate(x) for x in raw]
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
