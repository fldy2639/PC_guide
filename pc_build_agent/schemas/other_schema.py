from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RiskTolerance = Literal["low", "medium", "high", "unknown"]
PriorityLevel = Literal["low", "medium", "high", "unknown"]
UsageScene = Literal[
    "dormitory",
    "home",
    "office",
    "living_room",
    "rental_room",
    "unknown",
]
Placement = Literal[
    "desktop",
    "under_desk",
    "living_room",
    "portable",
    "unknown",
]
ConnectivityStrategy = Literal[
    "prefer_wifi_motherboard",
    "allow_pcie_wifi_card",
    "ethernet_only",
    "unknown",
]
SignalTarget = Literal["performance", "appearance", "price", "selection"]
SignalPriority = Literal["low", "medium", "high"]


class PurchaseScope(BaseModel):
    only_host: bool | None = None
    include_monitor: bool | None = None
    include_peripherals: bool | None = None
    include_os: bool | None = None
    include_assembly_service: bool | None = None
    include_delivery: bool | None = None


class ReusablePart(BaseModel):
    component: str
    description: str
    reuse_preference: Literal["preferred", "required", "optional", "unknown"] = "unknown"


class OwnedParts(BaseModel):
    has_monitor: bool | None = None
    has_keyboard_mouse: bool | None = None
    reusable_parts: list[ReusablePart] = Field(default_factory=list)
    parts_to_replace: list[str] = Field(default_factory=list)
    unknown_compatibility_parts: list[str] = Field(default_factory=list)


class Connectivity(BaseModel):
    need_wifi: bool | None = None
    need_bluetooth: bool | None = None
    need_ethernet: bool | None = None
    wifi_strength_priority: PriorityLevel = "unknown"
    connectivity_strategy: ConnectivityStrategy = "unknown"


class PurchaseRisk(BaseModel):
    accept_used_parts: bool | None = None
    accept_bulk_cpu: bool | None = None
    accept_mining_gpu: bool | None = None
    prefer_official_channel: bool | None = None
    risk_tolerance: RiskTolerance = "unknown"


class WarrantyService(BaseModel):
    need_warranty: bool | None = None
    prefer_full_machine_warranty: bool | None = None
    need_assembly_service: bool | None = None
    low_troubleshooting_tolerance: bool | None = None
    stability_priority: PriorityLevel = "unknown"


class UpgradePlan(BaseModel):
    upgrade_space_required: bool | None = None
    future_gpu_upgrade: bool | None = None
    future_ram_upgrade: bool | None = None
    future_storage_upgrade: bool | None = None
    future_cpu_upgrade: bool | None = None
    upgrade_priority: PriorityLevel = "unknown"


class UsageEnvironment(BaseModel):
    scene: UsageScene = "unknown"
    placement: Placement = "unknown"
    space_limited: bool | None = None
    noise_sensitive: bool | None = None
    portability_required: bool | None = None


class SpecialRequirements(BaseModel):
    front_type_c_required: bool | None = None
    usb_ports_priority: PriorityLevel = "unknown"
    multi_monitor_required: bool | None = None
    storage_capacity_requirement: str | None = None
    extra_hdd_required: bool | None = None
    special_interfaces: list[str] = Field(default_factory=list)


class ConstraintsForSelectionAgent(BaseModel):
    must_have_features: list[str] = Field(default_factory=list)
    prefer_features: list[str] = Field(default_factory=list)
    avoid_features: list[str] = Field(default_factory=list)
    budget_scope_modifiers: list[str] = Field(default_factory=list)
    compatibility_checks: list[str] = Field(default_factory=list)


class CrossModuleSignalItem(BaseModel):
    signal: str = ""
    target: SignalTarget = "price"
    target_effect: str = ""
    priority: SignalPriority = "medium"
    reason: str = ""


class CrossModuleSignals(BaseModel):
    performance_signals: list[CrossModuleSignalItem] = Field(default_factory=list)
    appearance_signals: list[CrossModuleSignalItem] = Field(default_factory=list)
    price_signals: list[CrossModuleSignalItem] = Field(default_factory=list)
    selection_signals: list[CrossModuleSignalItem] = Field(default_factory=list)


class OtherOutput(BaseModel):
    purchase_scope: PurchaseScope = Field(default_factory=PurchaseScope)
    owned_parts: OwnedParts = Field(default_factory=OwnedParts)
    connectivity: Connectivity = Field(default_factory=Connectivity)
    purchase_risk: PurchaseRisk = Field(default_factory=PurchaseRisk)
    warranty_service: WarrantyService = Field(default_factory=WarrantyService)
    upgrade_plan: UpgradePlan = Field(default_factory=UpgradePlan)
    usage_environment: UsageEnvironment = Field(default_factory=UsageEnvironment)
    special_requirements: SpecialRequirements = Field(default_factory=SpecialRequirements)
    constraints_for_selection_agent: ConstraintsForSelectionAgent = Field(
        default_factory=ConstraintsForSelectionAgent
    )
    cross_module_signals: CrossModuleSignals = Field(default_factory=CrossModuleSignals)
    missing_information: list[str] = Field(default_factory=list)


class OtherAgentOutput(BaseModel):
    other: OtherOutput
