# PC Guide

面向中文装机对话场景的 PC 需求理解与配件推荐服务。

当前仓库已经具备一条可运行的端到端链路：

`用户自然语言 -> RequirementProfile/兼容层 -> 候选召回 -> 兼容性与预算校验 -> 最终清单输出`

它同时包含两层能力：

1. 第一层：需求理解
   - `PerformanceRequirementAgent`
   - `AppearanceRequirementAgent`
   - `PriceRequirementAgent`
   - `OtherRequirementAgent`
   - `RequirementOrchestrator`
2. 第二层：配件选择
   - `selection.py`
   - `validation_engine.py`
   - `output_render.py`

第一层负责理解需求，不直接决定具体硬件型号；第二层才负责候选排序、兼容性校验和预算收敛。

## 当前状态

- 默认 API 入口是 [pc_build_agent/main.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/main.py)。
- 默认业务编排入口是 [pc_build_agent/pipeline/orchestrator.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/pipeline/orchestrator.py)。
- `safe_parse()` 现在优先走新的 `RequirementOrchestrator -> RequirementProfile -> LegacyRequirementAdapter` 链路。
- 如果新链路异常，才会 fallback 到旧的 `parse_requirements + enrich_*` 兼容逻辑。
- 商品数据默认读取 `pc_build_agent/database/hardware_catalog/v1/data/`。
- `pc_build_agent/data/products.json` 仍保留，更多偏向历史兼容/脚本输入，不是当前默认主数据源。

## 仓库结构

```text
PC_guide-main/
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── Dockerfile.api
├── docker-compose.yml
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── config.js
│   └── Dockerfile
├── docs/
│   ├── deployment_runbook.md
│   ├── engineering_guide.md
│   ├── requirement_knowledge_architecture.md
│   └── hardware_database_selection_architecture.md
├── pc_build_agent/
│   ├── main.py
│   ├── config.py
│   ├── pipeline/
│   ├── agents/
│   ├── services/
│   ├── models/
│   ├── schemas/
│   ├── rules/
│   ├── data/
│   └── database/
├── scripts/
└── tests/
```

## 技术链路

### 1. API 链路

```text
POST /api/pc-build-agent/recommend
-> pipeline.orchestrator.recommend()
-> requirement_agent.safe_parse()
-> RequirementOrchestrator
-> selection.retrieve_candidates()
-> validation_engine.validate_and_select()
-> output_render.render_final_markdown()
```

### 2. 需求理解链路

```text
user_text
-> Performance / Appearance / Other / Price.extract_budget
-> apply_other_signals supplement
-> Price.analyze(...)
-> RequirementProfile
-> LegacyRequirementAdapter
-> ParsedRequirements
```

### 3. 规则优先级

项目遵循仓库内 AGENTS.md 的约束：

- 确定性规则优先于 LLM。
- Requirement understanding 不直接做 SKU 推荐。
- 第一层输出以 `RequirementProfile` 为单一事实源。
- LLM 只补充模糊语义，不覆盖已命中的硬约束。

## 运行前提

### Python

- 需要 `Python 3.10+`
- 推荐 `Python 3.11`

注意：仓库里大量使用了 `str | None` 这类 3.10+ 语法，`Python 3.8/3.9` 不能稳定运行。

### 外部依赖

- API 全流程默认依赖 DeepSeek 兼容接口。
- 如果未配置 `DEEPSEEK_API_KEY`，`/recommend` 的真实解析流程无法完成。
- 单元测试设计目标是不依赖真实 LLM，但需要先安装开发依赖。

## 快速开始

### 1. 安装依赖

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

如果本机没有 `python3.11`，至少请使用 `python3.10`。

### 2. 配置环境变量

```bash
cp .env.example .env
```

最少需要补上：

```bash
DEEPSEEK_API_KEY=your-real-key
```

### 3. 启动后端

```bash
python3 -m uvicorn pc_build_agent.main:app --host 0.0.0.0 --port 8000
```

### 4. 启动前端

```bash
python3 -m http.server 5173 --directory frontend
```

### 5. 打开页面

- 前端页面：[http://127.0.0.1:5173](http://127.0.0.1:5173)
- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 健康检查：[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## 端到端自检

### 1. 健康检查

```bash
curl http://127.0.0.1:8000/health
```

期望返回：

```json
{"status":"ok"}
```

### 2. 推荐接口冒烟

```bash
curl -X POST http://127.0.0.1:8000/api/pc-build-agent/recommend \
  -H 'Content-Type: application/json' \
  -d '{
    "user_query": "预算8000，只要主机，主要写代码，偶尔玩3A，白色机箱，安静一点",
    "debug_llm": false
  }'
```

如果环境变量正确，应该返回：

- `code = 0`
- `data.session_id`
- `data.requirement_summary`
- `data.candidates_preview`
- `data.recommendation_markdown`

如果缺少 API Key，通常会得到解析失败提示，这属于环境问题，不是接口路由问题。

### 3. 单元测试

```bash
python3 -m pytest -q
```

说明：

- `pytest` 不在运行时依赖中，已拆到 `requirements-dev.txt`。
- 如果你只想部署服务，不需要安装开发依赖。

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek/OpenAI 兼容网关密钥 | 空 |
| `DEEPSEEK_BASE_URL` | LLM API 地址 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 模型名 | `deepseek-chat` |
| `PC_GUIDE_DB_PATH` | SQLite 会话文件路径 | `./data/pc_guide_sessions.sqlite` |
| `PC_GUIDE_HARDWARE_CATALOG_PATH` | 当前默认商品目录 | `./pc_build_agent/database/hardware_catalog/v1/data` |
| `PC_GUIDE_RULES_PATH` | 第二层兼容校验规则 | `./pc_build_agent/data/rules.json` |
| `PC_GUIDE_DEBUG_LLM` | 是否返回 LLM 调试轨迹 | `false` |
| `PC_GUIDE_CORS_ORIGINS` | 允许访问 API 的前端 Origin 列表 | 本地常见端口白名单 |

补充说明：

- `PC_GUIDE_PRODUCTS_PATH` 仍存在于配置模型里，但当前默认 `ProductRepository` 读取的是 hardware catalog 目录。
- 如果你要切回单文件商品池，请在代码或初始化参数里显式传入路径。

## API 摘要

### `POST /api/pc-build-agent/recommend`

请求体示例：

```json
{
  "user_query": "预算 6000 到 8000，只要主机，主要玩 3A",
  "session_id": null,
  "version": "v1",
  "debug_llm": false
}
```

响应重点字段：

- `data.need_clarification`
- `data.clarification_question`
- `data.requirement_summary`
- `data.candidates_preview`
- `data.final_build`
- `data.total_price`
- `data.budget_check`
- `data.compatibility_check`
- `data.risk_check`
- `data.recommendation_markdown`

## 数据与规则

### 第一层需求理解规则

主目录：

- `pc_build_agent/database/requirement_knowledge/v1/`

由 `RequirementKnowledgeRepository` 统一加载，优先级高于：

- `pc_build_agent/rules/*.json`

### 第二层硬件数据

当前默认主目录：

- `pc_build_agent/database/hardware_catalog/v1/data/`

主要覆盖：

- CPU
- GPU
- 主板
- 内存
- SSD
- 散热
- 电源
- 机箱

### 第二层兼容校验规则

- `pc_build_agent/data/rules.json`

用于名称正则 fallback 和部分历史兼容。

## 上线部署

仓库已经补了最基础的容器化文件：

- [Dockerfile.api](/Users/xieshengyuan/Downloads/PC_guide-main/Dockerfile.api)
- [frontend/Dockerfile](/Users/xieshengyuan/Downloads/PC_guide-main/frontend/Dockerfile)
- [docker-compose.yml](/Users/xieshengyuan/Downloads/PC_guide-main/docker-compose.yml)

推荐先看：

- [docs/deployment_runbook.md](/Users/xieshengyuan/Downloads/PC_guide-main/docs/deployment_runbook.md)

最简命令：

```bash
docker compose up --build
```

默认暴露：

- 前端：`8080`
- API：`8000`

## 工程阅读建议

如果你要继续开发，建议按这个顺序读：

1. [docs/engineering_guide.md](/Users/xieshengyuan/Downloads/PC_guide-main/docs/engineering_guide.md)
2. [pc_build_agent/main.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/main.py)
3. [pc_build_agent/pipeline/orchestrator.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/pipeline/orchestrator.py)
4. [pc_build_agent/agents/requirement_agent.py](/Users/xieshengyuan/Downloads/PC_guide-main/pc_build_agent/agents/requirement_agent.py)
5. [docs/requirement_knowledge_architecture.md](/Users/xieshengyuan/Downloads/PC_guide-main/docs/requirement_knowledge_architecture.md)
6. [docs/hardware_database_selection_architecture.md](/Users/xieshengyuan/Downloads/PC_guide-main/docs/hardware_database_selection_architecture.md)

## 已知事实与边界

- 这份仓库目前是“可运行的工程原型”，不是完全产品化的线上系统。
- 当前没有鉴权、限流、结构化日志、APM、异步任务队列。
- 会话持久化使用 SQLite，适合单实例部署或开发环境，不适合高并发多副本共享写入。
- 前端是纯静态页，没有构建工具链，部署简单，但没有环境注入体系；生产环境一般通过改 `frontend/config.js` 或网关层注入 `window.PC_GUIDE_API_BASE`。

## 配套文档

- [docs/engineering_guide.md](/Users/xieshengyuan/Downloads/PC_guide-main/docs/engineering_guide.md)
- [docs/deployment_runbook.md](/Users/xieshengyuan/Downloads/PC_guide-main/docs/deployment_runbook.md)
- [docs/requirement_knowledge_architecture.md](/Users/xieshengyuan/Downloads/PC_guide-main/docs/requirement_knowledge_architecture.md)
- [docs/hardware_database_selection_architecture.md](/Users/xieshengyuan/Downloads/PC_guide-main/docs/hardware_database_selection_architecture.md)

## 免责声明

- 本项目当前更偏工程研发与架构验证。
- LLM 解析结果仅用于需求理解，不应被视作最终采购建议。
- 如果接入真实商品数据，请先完成数据来源合规、字段清洗和价格更新策略设计。
