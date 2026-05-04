from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


CaseSize = Literal[
    "itx_compact",
    "compact_m_atx",
    "standard_atx",
    "large_atx",
    "unknown",
]

CaseStyle = Literal[
    "panoramic",
    "dual_chamber",
    "minimalist",
    "gaming",
    "traditional_tower",
    "airflow_mesh",
    "open_frame",
    "unknown",
]

Color = Literal[
    "white",
    "black",
    "silver_or_gray",
    "pink",
    "mixed",
    "no_preference",
    "unknown",
]

Material = Literal[
    "tempered_glass",
    "metal",
    "aluminum",
    "mesh",
    "matte",
    "avoid_plastic",
    "unknown",
]

RGB = Literal[
    "argb",
    "rgb",
    "single_color",
    "low_rgb",
    "no_rgb",
    "indifferent",
    "unknown",
]

Noise = Literal[
    "silent",
    "low_noise",
    "normal",
    "airflow_first",
    "indifferent",
    "unknown",
]

AppearancePriority = Literal[
    "high",
    "medium",
    "low",
    "unknown",
]


class AppearanceOutput(BaseModel):
    matched_keywords: list[str] = Field(default_factory=list)
    case_size: CaseSize = "unknown"
    preferred_form_factor: list[str] = Field(default_factory=list)
    case_style: CaseStyle = "unknown"
    color: Color = "unknown"
    material: Material = "unknown"
    rgb: RGB = "unknown"
    noise: Noise = "unknown"
    appearance_priority: AppearancePriority = "unknown"
    compatibility_constraints: list[str] = Field(default_factory=list)
    conflicts_or_warnings: list[str] = Field(default_factory=list)
    constraints_for_selection_agent: dict[str, Any] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)


class AppearanceAgentOutput(BaseModel):
    appearance: AppearanceOutput
