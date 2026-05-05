# Hardware Database And Selection Architecture

## 目标

第二层的职责是把第一层给出的 `RequirementProfile` 转成可执行的候选排序与兼容性校验流程。

它负责：

- 读取硬件目录
- 计算候选得分
- 应用硬约束/偏好约束
- 做兼容性、预算和风险检查
- 输出最终装机清单

它不负责：

- 理解用户自然语言
- 用 LLM 选 SKU
- 让第一层直接访问商品库

## 当前主数据源

当前默认主数据源是：

- `pc_build_agent/database/hardware_catalog/v1/data/`

由 [pc_build_agent/services/product_repository.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/services/product_repository.py) 读取。

`ProductRepository` 的默认路径来自：

- `PC_GUIDE_HARDWARE_CATALOG_PATH`

默认类别文件包括：

- `cpu.json`
- `gpu.json`
- `motherboard.json`
- `ram.json`
- `ssd.json`
- `cooling.json`
- `psu.json`
- `case.json`

## legacy 数据的定位

`pc_build_agent/data/products.json` 仍然保留，但它不是当前默认主数据源。

它更适合下面这些场景：

- 历史兼容
- 脚本生成/迁移输入
- 单文件商品池实验

如果你想显式切回单文件模式，可以在实例化 `ProductRepository(path=...)` 时手动指定文件路径。

## ProductRepository 职责

`ProductRepository` 负责：

- 读取单文件或多文件目录
- 归一化数值字段
- 构造 `ProductRecord`
- 把通用字段之外的内容收进 `ProductRecord.specs`

它不负责：

- 排序
- 预算分配
- 兼容性结论
- 推荐文案生成

## ProductRecord 结构

关键字段：

- `sku_id`
- `category`
- `name`
- `price`
- `current_price`
- `brand`
- `component_type`
- `jd_url`
- `tags`
- `specs`

其中 `specs` 是第二层结构化判断的核心输入。

## selection.py 的角色

[pc_build_agent/agents/selection.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/agents/selection.py)

负责：

- 读取 `RequirementProfile` / legacy 兼容结构
- 结合 `capability_profile` 给各类硬件打分
- 应用 `must_satisfy`
- 应用 `prefer_satisfy`
- 应用 `avoid`
- 处理 `specified_parts`
- 输出每个品类的排序结果和预览

当前设计要点：

- `capability_profile.component_weights` 会影响各类件的理想预算占比
- `selection_context.must_satisfy` 是硬过滤
- `selection_context.prefer_satisfy` 只加分，不淘汰
- `selection_context.avoid` 会抑制或排除不符合候选

## validation_engine.py 的角色

[pc_build_agent/agents/validation_engine.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/agents/validation_engine.py)

负责最终闭环：

- 组合候选件
- 检查硬兼容
- 计算总价
- 做预算判断
- 识别风险
- 必要时返回备选提示

当前优先使用 `specs` 做结构化校验，覆盖：

- CPU socket vs 主板 socket
- 主板 memory_type vs 内存 memory_type
- GPU 功耗需求 vs PSU wattage
- GPU 长度 vs 机箱限长
- 散热 socket/压制能力 vs CPU
- 散热高度/冷排尺寸 vs 机箱
- 主板板型 vs 机箱支持
- 电源规格 vs 机箱支持

如果 `specs` 缺失，才会 fallback 到：

- 名称解析
- `pc_build_agent/data/rules.json`

## 第二层和第一层的边界

第一层输出：

- `RequirementProfile`
- `capability_profile`
- `selection_context`

第二层消费：

- `selection.py`
- `validation_engine.py`

不应该出现：

- 第一层直接查商品库
- 第一层直接选择具体 SKU
- 第二层反向修改第一层原始意图

## 当前测试覆盖

建议阅读：

- [tests/test_product_repository_specs.py](/Users/xieshengyuan/Downloads/PC_guide-main/tests/test_product_repository_specs.py)
- [tests/test_selection_specs.py](/Users/xieshengyuan/Downloads/PC_guide-main/tests/test_selection_specs.py)
- [tests/test_validation_engine_specs.py](/Users/xieshengyuan/Downloads/PC_guide-main/tests/test_validation_engine_specs.py)

它们已经覆盖了：

- Repository 读取结构化 specs
- capability profile 对排序的影响
- must/prefer/avoid 约束
- 结构化硬兼容失败路径

## 开发建议

如果你要新增第二层能力，优先顺序建议是：

1. 先扩展 `hardware_catalog/v1/schemas` 和对应数据文件
2. 再补 `ProductRepository` 归一化逻辑
3. 再补 `selection.py` 的打分/过滤逻辑
4. 最后补 `validation_engine.py` 的硬校验

这样更容易保持“数据字段 -> 排序 -> 校验”这一条链是可追踪、可测试的。
