from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pc_build_agent.prompts.other_prompts import OTHER_EXTRACTION_PROMPT
from pc_build_agent.schemas.other_schema import OtherAgentOutput, OtherOutput
from pc_build_agent.services.requirement_knowledge_repository import RequirementKnowledgeRepository


class OtherRequirementAgent:
    PRIORITY_ORDER = {"low": 1, "medium": 2, "high": 3}

    def __init__(
        self,
        rule_path: str | Path | None = None,
        llm: Any | None = None,
        knowledge_repo: RequirementKnowledgeRepository | None = None,
    ):
        self.rule_path = Path(rule_path) if rule_path is not None else None
        if self.rule_path is not None:
            self.rules = self.load_rules(self.rule_path)
        else:
            repo = knowledge_repo or RequirementKnowledgeRepository()
            self.rules = self.load_rule_items(repo.get_rules("other"))
        self.llm = llm

    def load_rules(self, rule_path: Path) -> list[dict[str, Any]]:
        with rule_path.open("r", encoding="utf-8") as f:
            return self.load_rule_items(json.load(f))

    @staticmethod
    def load_rule_items(raw: Any) -> list[dict[str, Any]]:
        return list(raw or [])

    @staticmethod
    def normalize_text(text: str) -> str:
        return text.strip().lower()

    def analyze(self, user_text: str) -> dict[str, Any]:
        normalized_text = self.normalize_text(user_text)
        rule_matches = self.match_rules(normalized_text)

        llm_extraction = None
        if self.llm is not None:
            llm_extraction = self.extract_with_llm(user_text)

        merged = self.merge_rule_and_llm_results(rule_matches=rule_matches, llm_extraction=llm_extraction)
        output = OtherOutput(**merged)
        return self._model_to_dict(OtherAgentOutput(other=output))

    def match_rules(self, normalized_text: str) -> list[dict[str, Any]]:
        matched_rules: list[dict[str, Any]] = []
        for rule in self.rules:
            hit_keywords = []
            for keyword in rule.get("keywords", []):
                if keyword.lower() in normalized_text:
                    hit_keywords.append(keyword)
            if not hit_keywords:
                continue
            matched_rules.append(
                {
                    "rule_id": rule["rule_id"],
                    "dimension": rule["dimension"],
                    "hit_keywords": hit_keywords,
                    "effects": rule.get("effects", {}),
                    "description": rule.get("description", ""),
                }
            )
        return matched_rules

    def extract_with_llm(self, user_text: str) -> dict[str, Any] | None:
        if not self.llm:
            return None
        if hasattr(self.llm, "api_key") and not getattr(self.llm, "api_key"):
            return None
        if hasattr(self.llm, "chat_json"):
            prompt = OTHER_EXTRACTION_PROMPT.replace("{user_text}", user_text)
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ]
            try:
                return self.llm.chat_json(messages, step="other_extraction")
            except Exception:
                return None
        return None

    def merge_rule_and_llm_results(
        self,
        rule_matches: list[dict[str, Any]],
        llm_extraction: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = self._model_to_dict(OtherOutput())

        for match in rule_matches:
            effects = match.get("effects", {})
            for key, value in effects.items():
                if key not in merged:
                    continue
                merged[key] = self._deep_merge(merged[key], value)

        if llm_extraction:
            self.apply_llm_supplement(merged, llm_extraction)

        return self._normalize_merged_output(merged)

    def apply_llm_supplement(self, merged: dict[str, Any], llm_extraction: dict[str, Any]) -> None:
        for key, value in llm_extraction.items():
            if key not in merged:
                continue
            merged[key] = self._fill_unknown_only(merged[key], value)

    def _deep_merge(self, current: Any, incoming: Any) -> Any:
        if isinstance(current, dict) and isinstance(incoming, dict):
            merged = dict(current)
            for key, value in incoming.items():
                if key in merged:
                    merged[key] = self._merge_special_field(key, merged[key], value)
                else:
                    merged[key] = value
            return merged

        if isinstance(current, list) and isinstance(incoming, list):
            return self._merge_lists(current, incoming)

        if self._is_unknown_value(current) and not self._is_unknown_value(incoming):
            return incoming

        return current

    def _merge_special_field(self, key: str, current: Any, incoming: Any) -> Any:
        if key == "cross_module_signals" and isinstance(current, dict) and isinstance(incoming, dict):
            return self._merge_cross_module_signals(current, incoming)
        if key in {
            "must_have_features",
            "prefer_features",
            "avoid_features",
            "budget_scope_modifiers",
            "compatibility_checks",
        } and isinstance(current, list) and isinstance(incoming, list):
            return self._merge_lists(current, incoming)
        return self._deep_merge(current, incoming)

    def _fill_unknown_only(self, current: Any, incoming: Any) -> Any:
        if incoming is None:
            return current

        if isinstance(current, dict) and isinstance(incoming, dict):
            updated = dict(current)
            for key, value in incoming.items():
                if key not in updated:
                    updated[key] = value
                    continue
                updated[key] = self._fill_unknown_only(updated[key], value)
            return updated

        if isinstance(current, list) and isinstance(incoming, list):
            if not current:
                return list(incoming)
            return current

        if self._is_unknown_value(current) and not self._is_unknown_value(incoming):
            return incoming

        return current

    @staticmethod
    def _is_unknown_value(value: Any) -> bool:
        return value is None or value == "unknown"

    def _merge_lists(self, current: list[Any], incoming: list[Any]) -> list[Any]:
        merged = list(current)
        for item in incoming:
            if item not in merged:
                merged.append(item)
        return merged

    def _merge_cross_module_signals(self, current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(current)
        signal_keys = [
            "performance_signals",
            "appearance_signals",
            "price_signals",
            "selection_signals",
        ]
        for key in signal_keys:
            current_items = list(merged.get(key) or [])
            incoming_items = list(incoming.get(key) or [])
            merged[key] = self.dedupe_signal_items(current_items + incoming_items)
        for key, value in incoming.items():
            if key not in signal_keys and key not in merged:
                merged[key] = value
        return merged

    def dedupe_signal_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
        for item in items:
            key = (
                item.get("signal"),
                item.get("target"),
                item.get("target_effect"),
            )
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                continue

            old_priority = self.PRIORITY_ORDER.get(existing.get("priority", "medium"), 2)
            new_priority = self.PRIORITY_ORDER.get(item.get("priority", "medium"), 2)
            if new_priority > old_priority:
                by_key[key] = item

        return list(by_key.values())

    def _normalize_merged_output(self, merged: dict[str, Any]) -> dict[str, Any]:
        normalized = self._dedupe_lists(merged)
        cross_module_signals = dict(normalized.get("cross_module_signals") or {})
        for key in [
            "performance_signals",
            "appearance_signals",
            "price_signals",
            "selection_signals",
        ]:
            cross_module_signals[key] = self.dedupe_signal_items(list(cross_module_signals.get(key) or []))
        normalized["cross_module_signals"] = cross_module_signals
        return normalized

    def _dedupe_lists(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._dedupe_lists(item) for key, item in value.items()}
        if isinstance(value, list):
            deduped: list[Any] = []
            for item in value:
                normalized_item = self._dedupe_lists(item)
                if normalized_item not in deduped:
                    deduped.append(normalized_item)
            return deduped
        return value

    @staticmethod
    def _model_to_dict(model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()
