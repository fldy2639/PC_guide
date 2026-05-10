from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_PATH = ROOT / "pc_build_agent" / "database" / "requirement_knowledge" / "v1" / "capability_weight_rules.json"
CONFLICT_PATH = ROOT / "pc_build_agent" / "database" / "requirement_knowledge" / "v1" / "conflict_rules.json"
SELECTION_MAPPING_PATH = ROOT / "pc_build_agent" / "database" / "mappings" / "selection_constraint_mapping.json"
CAPABILITY_FIELD_MAPPING_PATH = ROOT / "pc_build_agent" / "database" / "mappings" / "capability_to_hardware_fields.json"


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


def test_selection_constraint_mapping_json_is_valid_and_executable():
    data = json.loads(SELECTION_MAPPING_PATH.read_text(encoding="utf-8"))

    assert data["version"] == "v1"
    assert isinstance(data.get("rules"), dict)
    assert data["rules"]
    assert data.get("explicit_requirement_fields")
    assert data["unknown_policy"]["must_satisfy"] == "move_to_prefer_satisfy"

    required_keys = {"component", "field", "operator"}
    for rule in data["rules"].values():
        if rule.get("action") != "replace_with_constraints":
            continue
        constraints = rule.get("constraints") or []
        assert constraints
        for constraint in constraints:
            assert required_keys.issubset(constraint)


def test_capability_to_hardware_fields_mapping_is_not_empty():
    data = json.loads(CAPABILITY_FIELD_MAPPING_PATH.read_text(encoding="utf-8"))

    assert data["version"] == "v1"
    assert isinstance(data.get("mappings"), list)
    assert data["mappings"]
    for item in data["mappings"]:
        assert item.get("capability")
        assert item.get("components")
        assert item.get("fields")
