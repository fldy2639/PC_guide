from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_PATH = ROOT / "pc_build_agent" / "database" / "requirement_knowledge" / "v1" / "capability_weight_rules.json"
CONFLICT_PATH = ROOT / "pc_build_agent" / "database" / "requirement_knowledge" / "v1" / "conflict_rules.json"


def test_capability_weight_rules_json_is_valid_and_has_profiles():
    data = json.loads(CAPABILITY_PATH.read_text(encoding="utf-8"))

    assert data["version"] == "v1"
    assert data["status"] == "runtime_enabled"
    assert data["runtime_scope"] == "first_layer_only"
    assert isinstance(data.get("profiles"), list)
    assert data["profiles"]

    allowed_components = {"cpu", "gpu", "ram", "ssd", "motherboard", "psu", "cooling", "case"}
    for profile in data["profiles"]:
        weights = profile.get("component_weights", {})
        assert isinstance(weights, dict)
        assert set(weights).issubset(allowed_components)
        for value in weights.values():
            assert isinstance(value, int)
            assert 1 <= value <= 5


def test_conflict_rules_json_is_valid_and_has_rules():
    data = json.loads(CONFLICT_PATH.read_text(encoding="utf-8"))

    assert data["version"] == "v1"
    assert data["status"] == "runtime_enabled"
    assert data["runtime_scope"] == "first_layer_only"
    assert isinstance(data.get("rules"), list)
    assert data["rules"]

    allowed_severity = {"low", "medium", "high"}
    for rule in data["rules"]:
        assert rule.get("severity") in allowed_severity
