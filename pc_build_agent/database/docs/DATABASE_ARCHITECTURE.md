# PC_guide 数据库架构（两层）

本文说明 `pc_build_agent/database/` 下**第一层需求理解知识库**、**第二层硬件配件目录**、**映射层**的职责与对齐方式，并标明与**当前仓库代码**的关系（见文末「与现有代码的对照」）。

---

## 第一层：需求理解知识库

- **路径**：`pc_build_agent/database/requirement_knowledge/v1/`
- **性质**：规则与能力映射数据。表达「用户需求 → 能力需求 → 参数权重 → 策略约束」等抽象信息。
- **不包含**：具体硬件型号、电商 SKU、价格点位表。

### 文件清单

| 文件 | 用途 |
|------|------|
| `scenario_capability_rules.json` | 场景 / 用途 → 能力需求 |
| `capability_weight_rules.json` | 能力需求 → 八大件相关权重等 |
| `appearance_requirement_rules.json` | 外观表达 → 结构化外观字段与预算侧影响 |
| `budget_strategy_rules.json` | 预算压力 → 八大件保护 / 压缩等策略 |
| `conflict_rules.json` | 需求冲突与降级 / 消解策略 |

当前各 JSON 为**可加载的初始占位**（如 `rules` / `profiles` 为空数组），具体规则由后续步骤填入。

---

## 第二层：硬件配件数据库（八大件）

- **路径**：`pc_build_agent/database/hardware_catalog/v1/`
- **性质**：真实八大件的结构化目录数据：CPU、GPU、motherboard、RAM、SSD、cooling、PSU、case。

### 子目录

| 路径 | 用途 |
|------|------|
| `data/` | 各品类 JSON，`items[]` 为记录列表（当前为空占位） |
| `templates/` | 单行导入模板，便于对齐 schema |
| `schemas/` | JSON Schema，校验 `items[]` 中单条记录 |

---

## 两层之间如何对齐

1. **第一层**的运行时代码产出 **`RequirementProfile`**（见 `pc_build_agent/schemas/requirement_profile_schema.py`），描述能力、约束、预算上下文等，而不是具体型号。
2. **映射层**（`pc_build_agent/database/mappings/`）提供约定：
   - `capability_to_hardware_fields.json`：能力 / 策略轴 → 应关注的 **catalog 字段**（当前为空数组占位，待填）。
   - `requirement_profile_to_catalog_contract.json`：`RequirementProfile` 与 `hardware_catalog` 路径、原则及 data/schema 索引。
3. **第一层不应**在实现上直接读取 `hardware_catalog/v1/data/`；跨层数据依赖应通过 **RequirementProfile** 与映射契约表达，避免需求理解模块与配件表硬耦合。

---

## RequirementProfile 是两层之间的业务接口

- 从需求理解进入选件 / 目录查询时，**结构化业务契约**应为 **`RequirementProfile`**（及现有的 `RequirementProfileOutput` 包装）。
- 映射 JSON 是对该契约消费方式的**说明与索引**，不替代 Pydantic 模型；实现以代码中的 schema 为准。

---

## PartsSelectionAgent 的数据源（目标与现状）

- **目标架构**（与本目录设计一致）：**PartsSelectionAgent 只消费 `RequirementProfile` 与 `hardware_catalog`**（并结合 `mappings/` 解析字段）。
- **现状**：见下文「与现有代码的对照」；代码尚未切换时，仍以现有实现为准。

---

## 与现有代码的对照（请你判断如何演进）

以下**不是**本目录结构错误，而是「文档目标」与「当前实现」之间的差异，便于你决定后续接线方式。

1. **第一层规则加载位置**  
   - **现状**：`PerformanceRequirementAgent`、`AppearanceRequirementAgent`、`PriceRequirementAgent`、`OtherRequirementAgent` 等从 **`pc_build_agent/rules/*.json`** 加载规则。  
   - **新建**：`database/requirement_knowledge/v1/*.json` **尚未被任何 Python 代码 import / 读取**。  
   - **含义**：两套 JSON 并存；若要统一为「数据库 v1」，需要后续增加加载逻辑或迁移规则内容，并处理与 `rules/` 的优先级或废弃策略。

2. **PartsSelectionAgent 的入参**  
   - **现状**：`PartsSelectionAgent.select(self, requirement_profile, pool: list[ProductRecord])` 使用 **`ProductRecord` 列表** 作为候选池；商品路径由 **`pc_build_agent/config.py`** 中的 `pc_guide_products_path` 指向 **`pc_build_agent/data/products.json`**（与 `hardware_catalog` 无关）。  
   - **文档目标**：仅消费 **RequirementProfile + hardware_catalog**。  
   - **含义**：要把选件完全迁到 `hardware_catalog`，需要新增从 `data/*.json` 构建候选、兼容/替换 `ProductRecord` 流水线等步骤；在此之前，本仓库行为仍以现有 `selection.py` + `products.json` 为准。

3. **Legacy 需求结构**  
   - **现状**：`normalize_requirement_profile` 仍支持从 **`ParsedRequirements.requirements`** 组装 profile 形状（见 `selection.py` 内注释 TODO）。  
   - **含义**：与 `AGENTS.md` 中「以 RequirementProfile 为单一真源」的长期目标一致时，可逐步收紧入口，仅保留 `requirement_profile` 路径。

---

## 版本与编码

- 目录名 `v1` 表示可并行增加 `v2` 做不兼容演进。
- 所有 JSON 规则与数据文件应使用 **UTF-8** 编码。
