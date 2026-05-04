# AGENTS.md

## Project Role

This repository implements a personal computer build recommendation agent.

The current focus is requirement understanding, including:

- performance requirement understanding
- appearance requirement understanding
- price requirement understanding
- other hidden constraints

## Development Rules

- The user uses Codex for development.
- Do not generate Cursor-specific instructions unless explicitly requested.
- Keep requirement understanding modules separated:
  - PerformanceRequirementAgent handles performance only.
  - AppearanceRequirementAgent handles appearance only.
  - PriceRequirementAgent handles price only.
- Do not mix hardware product recommendation into requirement understanding modules.
- Requirement understanding modules should output structured JSON for downstream selection agents.
- Rules should be stored in JSON rule libraries when possible.
- LLM prompts should only supplement ambiguous semantic understanding.
- Deterministic rules must have priority over LLM results.
- Do not let LLM directly decide final hardware models.
- Do not introduce unnecessary dependencies.

## Python Conventions

- Use Pydantic schemas for structured outputs.
- Keep agents testable without real LLM calls.
- Use pytest for unit tests.
- Keep rule matching deterministic and easy to debug.
- Rule files should be UTF-8 encoded JSON.

## Done Means

A task is complete only when:

- The relevant agent class is implemented.
- The rule JSON file is present and loadable.
- The schema validates output.
- Unit tests cover representative inputs.
- No unrelated module is modified.

## Project Architecture

This repository implements a personal computer build recommendation agent.

The system has two layers:

1. Requirement understanding layer
   - PerformanceRequirementAgent
   - AppearanceRequirementAgent
   - PriceRequirementAgent
   - OtherRequirementAgent
   - RequirementOrchestrator

2. Parts selection layer
   - PartsSelectionAgent
   - compatibility checking
   - budget-constrained optimization
   - final PC build list generation

## Logical Parallelism

In the requirement understanding layer, "parallel parsing" means logical parallelism, not mandatory runtime concurrency.

PerformanceRequirementAgent, AppearanceRequirementAgent, OtherRequirementAgent, and PriceRequirementAgent.extract_budget should all perform first-stage parsing directly from user_text.

They may be executed sequentially in code, but their first-stage parsing must be semantically independent.

Correct:

performance = performance_agent.analyze(user_text)
appearance = appearance_agent.analyze(user_text)
other = other_agent.analyze(user_text)
budget_extraction = price_agent.extract_budget(user_text)

Incorrect:

appearance = appearance_agent.analyze(user_text, performance)
other = other_agent.analyze(user_text, price)

Cross-module refinement happens only after first-stage parsing.

## Cross-module Design

OtherRequirementAgent is not a price-only helper.

OtherRequirementAgent must produce cross_module_signals for:
- performance
- appearance
- price
- selection

Other signals must be consumed as follows:
- PerformanceRequirementAgent uses performance_signals to supplement display output, storage, network and similar requirements.
- AppearanceRequirementAgent uses appearance_signals to supplement case size, noise and placement-related preferences.
- PriceRequirementAgent uses price_signals to adjust budget pressure and component budget strategy.
- PartsSelectionAgent receives selection_signals and constraints_for_selection_agent directly.

## RequirementProfile Contract

RequirementProfile is the single source of truth for requirement understanding output.

ParsedRequirements, RequirementsModel, and requirements.* are legacy compatibility layers only.

Do not maintain RequirementProfile and legacy requirements as two independent truth sources.

The correct flow is:

user_text
-> RequirementOrchestrator
-> RequirementProfile
-> LegacyRequirementAdapter, if compatibility is needed
-> PartsSelectionAgent consumes RequirementProfile

## PriceRequirementAgent

PriceRequirementAgent must have two stages:

1. extract_budget(user_text)
   - Parses budget language only.
   - Does not consume performance, appearance or other outputs.
   - Does not generate full component budget strategy.

2. analyze(user_text, performance_result, appearance_result, other_result, budget_extraction=None)
   - Generates full price strategy.
   - Consumes refined performance, refined appearance and other.
   - Produces selection_context_for_parts_agent.

## apply_other_signals Rule

apply_other_signals can only supplement.

It may:
- fill unknown / None fields
- append constraints
- append warnings
- append missing information
- add extra constraints
- slightly increase priority

It must not:
- override explicit user-matched performance usage
- override explicit user-matched appearance style
- remove primary usage
- convert a clearly matched requirement into the opposite

## PartsSelectionAgent Input

PartsSelectionAgent should consume only RequirementProfile.

Do not pass performance_result, appearance_result, price_result, other_result, and legacy requirements separately.

## Development Rules

- Do not generate Cursor-specific instructions.
- Do not implement concrete hardware product recommendation in requirement understanding modules.
- Do not select specific CPU, GPU, motherboard, case, PSU, RAM, SSD or cooling models in requirement understanding modules.
- Rule libraries must be deterministic and stored as JSON when possible.
- LLM prompts may only supplement ambiguous fields.
- Deterministic rules have priority over LLM output.
- LLM must not overwrite rule-matched hard constraints.
- Modules must work without a real LLM.
- Unit tests must cover cross-module signal propagation.
