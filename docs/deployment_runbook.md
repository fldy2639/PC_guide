# Deployment Runbook

这份 runbook 只解决一件事：把当前仓库以最少假设部署起来，并明确哪些地方已经适合上线、哪些地方还只是工程原型。

## 部署前确认

上线前请先确认以下条件：

1. Python 版本为 `3.10+`
2. 已准备 `DEEPSEEK_API_KEY`
3. 已确认前端访问 API 的域名，并配置到 `PC_GUIDE_CORS_ORIGINS`
4. 已确认 SQLite 文件是否允许持久化到本地磁盘

## 当前推荐部署形态

### 方案 A：单机两进程

适合：

- 内部演示
- 开发环境
- 单机试运行

组成：

- 一个 FastAPI 进程
- 一个静态文件服务进程

### 方案 B：Docker Compose

适合：

- 本地联调
- 测试环境
- 小规模单机部署

仓库已提供：

- [Dockerfile.api](/Users/xieshengyuan/Downloads/PC_guide-main/Dockerfile.api)
- [frontend/Dockerfile](/Users/xieshengyuan/Downloads/PC_guide-main/frontend/Dockerfile)
- [docker-compose.yml](/Users/xieshengyuan/Downloads/PC_guide-main/docker-compose.yml)

## 方案 A：手动部署

### 1. 安装依赖

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

至少需要配置：

```bash
DEEPSEEK_API_KEY=your-real-key
PC_GUIDE_CORS_ORIGINS=https://your-frontend-domain
```

### 3. 启动后端

```bash
python3 -m uvicorn pc_build_agent.main:app --host 0.0.0.0 --port 8000
```

### 4. 启动前端

```bash
python3 -m http.server 5173 --directory frontend
```

### 5. 调整前端 API 地址

默认前端读取：

- `frontend/config.js`

默认值是：

- `http://127.0.0.1:8000`

如果你用了正式域名，请改为对应 API 地址，或者在页面更早的位置注入：

```html
<script>
  window.PC_GUIDE_API_BASE = "https://api.example.com";
</script>
```

## 方案 B：Docker Compose

### 1. 准备环境变量

```bash
cp .env.example .env
```

至少补：

```bash
DEEPSEEK_API_KEY=your-real-key
```

### 2. 构建并启动

```bash
docker compose up --build
```

默认端口：

- 前端：`8080`
- API：`8000`

### 3. 验证

```bash
curl http://127.0.0.1:8000/health
```

前端访问：

- [http://127.0.0.1:8080](http://127.0.0.1:8080)

## 生产环境注意事项

### 已经适合放到线上原型环境的部分

- FastAPI API 结构
- CORS 配置方式
- 第一层规则 + 第二层规则分层
- 静态前端独立部署

### 还建议在正式生产前补齐的部分

- 鉴权
- 限流
- 结构化日志
- 错误告警
- 配置分环境管理
- 非 SQLite 的持久化方案
- LLM 调用超时/重试/熔断策略

## SQLite 说明

当前会话默认存放在：

- `./data/pc_guide_sessions.sqlite`

适合：

- 本地开发
- 单机部署

不适合：

- 多副本共享写
- 高并发生产集群

如果后面要做多实例部署，建议把 session store 抽到外部数据库。

## 最小上线检查清单

- `/health` 返回正常
- `/docs` 可访问
- 前端能成功发起 `recommend`
- `DEEPSEEK_API_KEY` 已配置
- `PC_GUIDE_CORS_ORIGINS` 已包含前端域名
- SQLite 路径可写
- `frontend/config.js` 指向正确 API 地址
