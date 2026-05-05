from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RequirementKnowledgeRepository:
    DOMAIN_FILE_MAP = {
        "performance": {
            "stable": "scenario_capability_rules.json",
            "legacy": "performance_rules.json",
        },
        "appearance": {
            "stable": "appearance_requirement_rules.json",
            "legacy": "appearance_rules.json",
        },
        "other": {
            "stable": "other_requirement_rules.json",
            "legacy": "other_rules.json",
        },
        "price": {
            "stable": "budget_strategy_rules.json",
            "legacy": "price_rules.json",
        },
    }

    def __init__(
        self,
        stable_root: str | Path | None = None,
        legacy_root: str | Path | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        self.stable_root = Path(stable_root or root / "database" / "requirement_knowledge" / "v1")
        self.legacy_root = Path(legacy_root or root / "rules")

    def get_rules(self, domain: str) -> Any:
        source = self.get_source(domain)
        path = Path(source)
        data = self._safe_load_json(path)

        if domain in {"performance", "appearance", "other"}:
            return self._extract_rule_list(data)

        if domain == "price":
            return data if isinstance(data, dict) else {}

        return data

    def get_source(self, domain: str) -> str:
        files = self.DOMAIN_FILE_MAP.get(domain)
        if not files:
            raise ValueError(f"Unsupported requirement knowledge domain: {domain}")

        stable_path = self.stable_root / files["stable"]
        legacy_path = self.legacy_root / files["legacy"]
        stable_data = self._safe_load_json(stable_path)

        if domain in {"performance", "appearance", "other"}:
            stable_rules = self._extract_rule_list(stable_data)
            if stable_rules:
                return str(stable_path)
            return str(legacy_path)

        if domain == "price":
            if isinstance(stable_data, dict) and "performance_profiles" in stable_data:
                return str(stable_path)
            return str(legacy_path)

        return str(legacy_path)

    def get_capability_weight_profiles(self) -> list[dict[str, Any]]:
        path = self.stable_root / "capability_weight_rules.json"
        data = self._safe_load_json(path)
        if not isinstance(data, dict):
            return []
        if data.get("status") not in {"runtime_enabled", "reference_only"}:
            return []
        profiles = data.get("profiles")
        if not isinstance(profiles, list):
            return []
        return profiles

    def get_conflict_rules(self) -> list[dict[str, Any]]:
        path = self.stable_root / "conflict_rules.json"
        data = self._safe_load_json(path)
        if not isinstance(data, dict):
            return []
        if data.get("status") not in {"runtime_enabled", "reference_only"}:
            return []
        rules = data.get("rules")
        if not isinstance(rules, list):
            return []
        return rules

    @staticmethod
    def _safe_load_json(path: Path) -> Any:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _extract_rule_list(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("rules"), list):
            return data["rules"]
        return []
