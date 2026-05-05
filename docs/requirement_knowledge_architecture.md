# Requirement Knowledge Architecture

## 目标

第一层需求理解的目标不是选具体硬件，而是把用户自然语言稳定转换为 `RequirementProfile`，供第二层配件选择消费。

这一层关注：

- 性能诉求
- 外观诉求
- 预算诉求
- 其他隐藏约束

这一层不负责：

- 直接推荐 CPU/GPU/主板等具体型号
- 查询商品库
- 最终兼容性闭环

## 当前运行链路

当前代码中的主链路是：

```text
user_text
-> requirement_agent.safe_parse()
-> RequirementOrchestrator.analyze()
-> PerformanceRequirementAgent.analyze()
-> AppearanceRequirementAgent.analyze()
-> OtherRequirementAgent.analyze()
-> PriceRequirementAgent.extract_budget()
-> apply_other_signals supplement
-> PriceRequirementAgent.analyze(...)
-> RequirementProfile
-> LegacyRequirementAdapter.from_requirement_profile()
-> ParsedRequirements
```

说明：

- `RequirementProfile` 是第一层标准输出。
- `ParsedRequirements` 仍然存在，是为了兼容当前第二层与 API 输出。
- 如果新链路发生异常，`safe_parse()` 才会 fallback 到旧的 `parse_requirements + enrich_*` 路径。

## 模块职责

### `PerformanceRequirementAgent`

负责：

- 识别 primary / secondary usage
- 抽取性能目标
- 计算组件关注权重
- 输出 `constraints_for_selection_agent`

规则来源：

- 优先 `database/requirement_knowledge/v1/scenario_capability_rules.json`
- fallback `rules/performance_rules.json`

### `AppearanceRequirementAgent`

负责：

- 机箱尺寸、风格、颜色、RGB、静音等偏好
- 外观冲突提示
- 面向第二层的外观约束

规则来源：

- 优先 `database/requirement_knowledge/v1/appearance_requirement_rules.json`
- fallback `rules/appearance_rules.json`

### `OtherRequirementAgent`

负责：

- 显示器/外设/系统范围
- WiFi/蓝牙
- 二手接受度
- 质保与升级空间
- 环境类限制
- 跨模块 signals

规则来源：

- 优先 `database/requirement_knowledge/v1/other_requirement_rules.json`
- fallback `rules/other_rules.json`

### `PriceRequirementAgent`

严格按两阶段工作：

1. `extract_budget(user_text)`
   - 只解析预算语言
   - 不依赖 performance/appearance/other
2. `analyze(...)`
   - 基于预算、性能、外观、其他约束生成完整价格策略
   - 输出 `selection_context_for_parts_agent`

规则来源：

- 优先 `database/requirement_knowledge/v1/budget_strategy_rules.json`
- fallback `rules/price_rules.json`

## Repository 角色

[pc_build_agent/services/requirement_knowledge_repository.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/services/requirement_knowledge_repository.py)

职责只有一件事：统一加载第一层规则数据。

它负责：

- stable 规则路径选择
- legacy fallback
- 读取 capability profiles
- 读取 conflict rules

它不负责：

- 关键词命中
- 正则解析
- LLM 调用
- 结果合并
- RequirementProfile 生成

## 当前规则源优先级

| domain | stable | fallback |
| --- | --- | --- |
| `performance` | `scenario_capability_rules.json` | `performance_rules.json` |
| `appearance` | `appearance_requirement_rules.json` | `appearance_rules.json` |
| `other` | `other_requirement_rules.json` | `other_rules.json` |
| `price` | `budget_strategy_rules.json` | `price_rules.json` |

## capability / conflict 文件状态

这两个文件现在已经是运行时启用状态，不再只是参考文档：

- `capability_weight_rules.json`
- `conflict_rules.json`

当前状态：

- `status = runtime_enabled`
- `runtime_scope = first_layer_only`

作用：

- `capability_weight_rules.json` 会补充典型场景的组件权重画像
- `conflict_rules.json` 会在第一层生成轻量冲突提示，并写入 `selection_context.cross_module_signals`

它们仍然不直接参与 SKU 选择。

## RequirementProfile 的定位

`RequirementProfile` 是第一层唯一真源，内部整合：

- `performance`
- `appearance`
- `price`
- `other`
- `capability_profile`
- `selection_context`
- `missing_information`

兼容层 `ParsedRequirements`、`requirements.*` 只是为了：

- 兼容旧 API 输出
- 兼容现有第二层调用

后续如果继续重构，优先维护 `RequirementProfile`，而不是同时维护两套独立真源。

## apply_other_signals 约束

跨模块补充只允许 supplement，不允许 overturn。

可以做：

- 填充未知字段
- 追加约束
- 追加 warning
- 轻微提高优先级

不可以做：

- 推翻明确命中的 primary usage
- 覆盖明确的 appearance style
- 把明确需求改成反义

## 开发建议

如果你要继续迭代第一层，建议按这个顺序改：

1. 先改 `database/requirement_knowledge/v1/*.json`
2. 再补对应 agent 的 deterministic merge 逻辑
3. 最后补测试

优先补测试的目录：

- `tests/test_performance_requirement_agent.py`
- `tests/test_other_requirement_agent.py`
- `tests/test_price_requirement_agent.py`
- `tests/test_requirement_agent_aggregation.py`
- `tests/test_requirement_knowledge_repository.py`

## 不建议的改法

- 不要在第一层直接返回具体 SKU
- 不要让 LLM 覆盖规则命中的硬约束
- 不要把 `RequirementProfile` 和 legacy requirements 当两套并列真源长期维护
