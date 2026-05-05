# Engineering Guide

这份文档的目标是帮助后续开发者快速找到“从哪里开始看、改哪里最安全”。

## 建议阅读顺序

1. [README.md](/Users/xieshengyuan/Downloads/PC_guide-main/README.md)
2. [pc_build_agent/main.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/main.py)
3. [pc_build_agent/pipeline/orchestrator.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/pipeline/orchestrator.py)
4. [pc_build_agent/agents/requirement_agent.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/agents/requirement_agent.py)
5. [pc_build_agent/agents/selection.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/agents/selection.py)
6. [pc_build_agent/agents/validation_engine.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/agents/validation_engine.py)

## 核心入口

### Web/API 入口

- `pc_build_agent.main:app`

### 业务总入口

- `pc_build_agent.pipeline.orchestrator.recommend`

### 第一层需求理解入口

- `pc_build_agent.agents.requirement_agent.safe_parse`

### 第二层候选排序入口

- `pc_build_agent.agents.selection.retrieve_candidates`

### 第二层最终校验入口

- `pc_build_agent.agents.validation_engine.validate_and_select`

## 改需求理解时，优先动哪里

### 新增关键词/规则

优先改：

- `pc_build_agent/database/requirement_knowledge/v1/*.json`

谨慎改：

- `pc_build_agent/rules/*.json`

原因：

- `database/requirement_knowledge/v1` 是当前主维护入口
- `rules/*.json` 主要用于 fallback

### 新增字段或输出结构

优先检查：

- `pc_build_agent/schemas/*_schema.py`
- `pc_build_agent/schemas/requirement_profile_schema.py`
- `pc_build_agent/agents/legacy_requirement_adapter.py`

如果第一层输出结构变了，通常这些地方要一起看。

## 改第二层选配时，优先动哪里

### 增加硬件字段

按顺序检查：

1. `pc_build_agent/database/hardware_catalog/v1/schemas/*.schema.json`
2. `pc_build_agent/database/hardware_catalog/v1/data/*.json`
3. `pc_build_agent/services/product_repository.py`

### 增加排序规则

优先改：

- `pc_build_agent/agents/selection.py`

### 增加强兼容校验

优先改：

- `pc_build_agent/agents/validation_engine.py`

## 测试建议

### 需求理解层

- `tests/test_performance_requirement_agent.py`
- `tests/test_appearance_requirement_agent.py`
- `tests/test_other_requirement_agent.py`
- `tests/test_price_requirement_agent.py`
- `tests/test_requirement_agent_aggregation.py`
- `tests/test_requirement_knowledge_repository.py`

### 第二层选配

- `tests/test_product_repository_specs.py`
- `tests/test_selection_specs.py`
- `tests/test_validation_engine_specs.py`

## 本仓库最重要的几个工程约束

- 第一层不要直接推荐具体硬件型号
- 确定性规则优先于 LLM
- `RequirementProfile` 是第一层统一真源
- `OtherRequirementAgent` 不是 price helper，它必须输出跨模块 signals
- `PriceRequirementAgent` 必须保持 extract/analyze 两阶段

## 接手开发时最常见的坑

### 1. Python 版本太低

仓库需要 `Python 3.10+`。

### 2. 只装了运行时依赖，没有装测试依赖

如果要跑测试，需要：

```bash
pip install -r requirements-dev.txt
```

### 3. 把 `products.json` 当成默认线上主数据源

当前默认主数据源其实是：

- `pc_build_agent/database/hardware_catalog/v1/data/`

### 4. 以为 API 不依赖 LLM

当前 `/recommend` 的真实全流程默认依赖 `DEEPSEEK_API_KEY`。

如果只是想做模块开发或单测，可以通过 stub/mocking 方式避开真实 LLM 调用。
