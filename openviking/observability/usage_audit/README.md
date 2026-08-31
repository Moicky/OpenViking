# Usage/Audit 使用说明

Usage/Audit 是 OpenViking Server 给 Console 使用的产品统计与请求审计模块。它复用
OpenViking 已有的 observability 事件，不要求 Console 直接依赖 Prometheus，也不会在正常
API 请求链路里同步写统计库。

## 适用场景

当前模块主要服务 Console P0 页面：

- 总览页首屏：上下文数据量、今日 Token、今日检索、Agent 概览
- 记忆使用情况：自学习记忆的注入/读取次数排行，以及从未被使用的清理候选
- Token 趋势：按日期范围查询模型 Token 消耗
- 上下文提交热力图：按日期和小时段查询上下文写入活动
- 请求日志：分页查询请求明细、状态、耗时和成功率

这套数据是产品语义数据，不是运维指标。QPS、latency histogram、queue depth、cache
hit/miss 等仍然应该看 Prometheus metrics。

## 工作方式

数据流如下：

```text
业务请求 / 模型调用
        |
        v
Observability Event Bus
        |
        +--> Metrics subscriber
        |
        +--> Usage/Audit subscriber
                  |
                  v
            Usage/Audit worker
                  |
                  v
            Usage/Audit store
                  |
                  v
          /api/v1/console/* BFF
```

关键点：

- Usage/Audit 订阅共享事件总线，不重复散落 Console 专用打点。
- `server.observability.metrics.enabled=false` 不影响 Usage/Audit。
- 请求路径只做非阻塞事件投递；写库由后台 worker 批量完成。
- worker 使用 bounded queue；队列满时会丢弃统计事件并增加 `dropped_count`。
- 服务关闭时会尽量 flush 剩余事件；如果已有 batch 正在写入，会等待它完成，避免尾部审计丢失或重复写入。

## 配置

默认启用 Usage/Audit。最小配置可以不写任何字段。

完整配置示例：

```json
{
  "server": {
    "observability": {
      "usage_audit": {
        "enabled": true,
        "backend": "sqlite",
        "sqlite_path": "/path/to/usage_audit.sqlite3",
        "queue_size": 10000,
        "batch_size": 500,
        "flush_interval_seconds": 1.0,
        "shutdown_flush_timeout_seconds": 3.0,
        "usage_retention_days": 14,
        "memory_retention_days": 90,
        "audit_retention_days": 7,
        "audit_retention_per_account": 1000,
        "timezone": "local",
        "inventory_ttl_seconds": 10.0
      }
    }
  }
}
```

字段说明：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否启用 Usage/Audit |
| `backend` | `"sqlite"` | 当前仅支持 SQLite |
| `sqlite_path` | `null` | SQLite 文件路径；为空时使用当前 OpenViking workspace 下的 `_system/usage_audit/usage_audit.sqlite3` |
| `queue_size` | `10000` | 后台写入队列大小 |
| `batch_size` | `500` | 单次批量写入的最大事件数 |
| `flush_interval_seconds` | `1.0` | worker 定时 flush 间隔 |
| `shutdown_flush_timeout_seconds` | `3.0` | 服务关闭时 flush 等待时间 |
| `usage_retention_days` | `14` | 统计聚合数据保留天数，包含 Token、检索、上下文写入热力图、Agent 活跃；`0` 表示不按天裁剪 |
| `memory_retention_days` | `90` | 记忆访问数据保留天数；窗口比其他统计长，因为“哪些记忆可以清理”是按月判断的；`0` 表示不按天裁剪 |
| `audit_retention_days` | `7` | 请求审计日志保留天数；`0` 表示不按天裁剪 |
| `audit_retention_per_account` | `1000` | 每个 account 保留的最新请求审计条数；`0` 表示不按条数裁剪 |
| `timezone` | `"local"` | Console 请求未传 `timezone` 时的兜底查询时区；写入始终按 UTC 保存。`"local"` 表示 server 进程所在机器/容器的本地时区 |
| `inventory_ttl_seconds` | `10.0` | 上下文当前数据量查询缓存时间 |

本地版使用 SQLite 没问题。分布式生产环境如果多实例同时提供 Console，建议后续增加共享
store backend，而不是让多个实例各写各的本地 SQLite。

## 数据口径

### Token

来自模型调用事件：

| 事件 | 当前 Console 展示口径 |
| --- | --- |
| `vlm.call` | `prompt_tokens` 计入 `vlm_input`，`completion_tokens` 计入 `vlm_output` |
| `embedding.call` | `prompt_tokens` 计入 `embedding_input` |
| `rerank.call` | 已可落库，当前 Console summary/series 暂不展示 |

### 今日检索

来自 HTTP 请求完成事件 `http.request`：

| API route | operation |
| --- | --- |
| `POST /api/v1/search/find` | `find` |
| `POST /api/v1/search/search` | `search` |

`2xx` 和 `3xx` 记为 `success`，`4xx/5xx` 记为 `error`。Dashboard 今日检索只展示成功请求数。

### 上下文提交热力图

来自成功的公开写请求：

| API route | operation |
| --- | --- |
| `POST /api/v1/resources` | `add_resource` |
| `POST /api/v1/skills` | `add_skill` |
| `POST /api/v1/sessions/{session_id}/messages` | `session_add_message` |
| `POST /api/v1/sessions/{session_id}/commit` | `session_commit` |

只有 `2xx/3xx` 会进入上下文提交统计。

### 上下文数据量

Dashboard 首屏的上下文数据量是当前状态查询，不是历史事件累加：

- `files`：读取 `viking://resources` 的 `stat.count`
- `skills`：读取当前 Agent `skills` 根目录的 `stat.count`
- `memories`：读取当前 User 和当前 Agent 的 `memories` 根目录 `stat.count` 后求和

`stat.count` 是底层 `VikingFS.stat()` 暴露的目录计数字段。Usage/Audit 不自己拼
vector filter，也不从历史写入事件累计当前库存。

这部分会走 `inventory_ttl_seconds` 缓存，避免 Console 刷新频繁打到底层存储。业务根目录
不存在时按 0 处理，避免新环境或空租户反复刷 warning。

### 记忆使用情况

来自 `memory.access` 事件，按 `(account, user, UTC 日期, uri, source)` 聚合到
`memory_access_daily`：

| source | 来源 | 含义 |
| --- | --- | --- |
| `injected` | `assemble_context` 实际下发的条目（`/search` mode=`context`、`/recall`） | 服务端组装的上下文块中包含该记忆 |
| `found` | `POST /api/v1/search/find`、`POST /api/v1/search/search`（非 context 模式）返回的 `memories` / `skills` 命中 | 客户端自行组装上下文的插件只有这一条路径；Agent 主动 `find` 也计入 |
| `read` | `GET /api/v1/content/{read,abstract,overview}` | 调用方显式读取该记忆 |

`found` 是必要的：早于服务端上下文组装的 harness 插件（例如 `openviking-memory` 0.4.3）
只调用 `find` 然后在客户端拼装注入块，服务端无法从别处得知哪些记忆进了那个会话。
它的证据强度弱于 `injected`，因此三者分列存储、分别展示，而不是合并成一个计数。

只统计**自学习**内容：URI 位于 `.../memories/<category>/…` 或 `.../skills/…`。
已索引资源（`viking://resources/...`，以及资源根目录下自带的 `skills/`、`memories/`
子目录）一律不计入，否则一次仓库导入就会淹没自学习知识的使用信号。

`injected` 与去重 ledger 使用同一份 `served` 集合：当 digest 判定 `no_relevant`
把上下文块清空时，这一轮不会计入任何一条记忆。

### 请求审计

请求审计来自 `http.request`，保留字段：

- `request_id`
- `account_id`
- `user_id`
- `method`
- `route`
- `api_type`
- `status_code`
- `duration_ms`
- `error_code`（仅标准错误响应）
- `error_message`（仅标准错误响应）
- `error_details`（仅标准错误响应，可空）
- `created_at`

错误字段来自 OpenViking 已返回给调用方的标准错误结构，不读取或缓存 HTTP response
body。`error_details` 经过凭据脱敏和大小限制；它可能包含被拒绝的参数值，但不会额外保存
原始 request body、header、query string、stack trace 或 exception text。

以下 route 不进入审计：

- `/metrics`
- `/health`
- `/ready`
- `/docs`
- `/docs/oauth2-redirect`
- `/redoc`
- `/openapi.json`
- `/favicon.ico`
- `/favicon.png`
- `/apple-touch-icon.png`
- `/api/v1/console/*`

## Console BFF API

所有接口都在 OV Server 侧：

```text
/api/v1/console/*
```

Console 前端通过 Console server 的 allowlist proxy 访问：

```text
/console/api/v1/ov/console/dashboard/summary
/console/api/v1/ov/console/tokens
/console/api/v1/ov/console/context-commits
/console/api/v1/ov/console/audit
```

权限要求：

- `ROOT` 和 `ADMIN` 可以访问
- 普通 `USER` 返回 `403 PERMISSION_DENIED`

### Dashboard Summary

```text
GET /api/v1/console/dashboard/summary
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `timezone` | 否 | IANA 时区名（如 `Asia/Shanghai`）；省略时回退到 server 时区，用于确定"今日"的时区边界 |

返回示例：

```json
{
  "status": "ok",
  "result": {
    "context_counts": {
      "files": 12,
      "skills": 3,
      "memories": 8,
      "total": 23
    },
    "today_tokens": {
      "vlm_input": 1000,
      "vlm_output": 500,
      "embedding_input": 200,
      "total": 1700
    },
    "today_retrievals": {
      "find": 10,
      "search": 4,
      "total": 14
    }
  }
}
```

如果 Usage/Audit 被关闭或尚未初始化，返回：

```json
{
  "status": "ok",
  "result": {
    "enabled": false,
    "message": "Usage/Audit is disabled or not initialized."
  }
}
```

### Token Series

```text
GET /api/v1/console/tokens?start_date=2026-05-01&end_date=2026-05-12&bucket=day
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `start_date` | 是 | 开始日期，格式 `YYYY-MM-DD`（按 `timezone` 指定的时区解释） |
| `end_date` | 是 | 结束日期，格式 `YYYY-MM-DD`（按 `timezone` 指定的时区解释） |
| `bucket` | 否 | 当前仅支持 `day` |
| `timezone` | 否 | IANA 时区名（如 `Asia/Shanghai`）；省略时回退到 server 时区，返回的 `date` 分桶按该时区 |

返回中会补齐日期范围内没有数据的日期。

### Context Commits

```text
GET /api/v1/console/context-commits?start_date=2026-05-01&end_date=2026-05-12&bucket=4h
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `start_date` | 是 | 开始日期，格式 `YYYY-MM-DD`（按 `timezone` 指定的时区解释） |
| `end_date` | 是 | 结束日期，格式 `YYYY-MM-DD`（按 `timezone` 指定的时区解释） |
| `bucket` | 否 | `hour` 或 `4h`，默认 `hour` |
| `timezone` | 否 | IANA 时区名（如 `Asia/Shanghai`）；省略时回退到 server 时区，返回的 `date` / `hour` 分桶按该时区 |

返回中会补齐日期和小时段范围内没有数据的 bucket。

### Memory Usage

```text
GET /api/v1/console/memory-usage?days=30&limit=10
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `days` | 否 | 回溯天数，`0..365`，默认 `30`；`0` 表示全部保留期 |
| `limit` | 否 | `top` 与 `unused` 各自返回的条数，`1..100`，默认 `10` |

返回示例：

```json
{
  "status": "ok",
  "result": {
    "days": 30,
    "totals": {
      "inventory": 42,
      "used": 18,
      "unused": 24,
      "deleted_but_used": 0,
      "injections": 137,
      "found": 214,
      "reads": 9,
      "accesses": 360
    },
    "by_category": { "entities": 61, "events": 40 },
    "top": [
      {
        "uri": "viking://user/u1/memories/entities/foo.md",
        "category": "entities",
        "injected": 23,
        "found": 31,
        "read": 2,
        "total": 56,
        "active_days": 11,
        "first_date": "2026-08-04",
        "last_access_at": "2026-08-31T09:12:44+00:00"
      }
    ],
    "unused": [
      { "uri": "viking://user/u1/memories/events/old.md", "category": "events" }
    ]
  }
}
```

`unused` 来自向量库中当前存在的自学习条目减去窗口内有访问记录的 URI，因此它回答的是
“哪些记忆可以清理”。`deleted_but_used` 是有访问记录但当前库存里已不存在的条目数——它们
计入 totals，但不是清理候选。

### Audit Logs

```text
GET /api/v1/console/audit?page=1&page_size=20&status=success,error&api_type=search.find
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `page` | 否 | 页码，从 `1` 开始 |
| `page_size` | 否 | 每页条数，范围 `1..100` |
| `request_id` | 否 | 精确匹配 request id |
| `status` | 否 | 可重复传，也可逗号分隔 |
| `api_type` | 否 | 可重复传，也可逗号分隔 |

`status` 支持：

- `success` / `ok`：`2xx` 和 `3xx`
- `2xx`
- `3xx`
- `error` / `failed`：`4xx/5xx`
- `4xx`、`5xx` 等通配段
- 具体状态码，例如 `404`

返回字段：

```json
{
  "status": "ok",
  "result": {
    "total": 123,
    "success_rate": 0.98,
    "page": 1,
    "page_size": 20,
    "items": []
  }
}
```

`success_rate` 使用当前筛选条件下的 `2xx/3xx` 占比。

## 本地验证

启动 server 后，可以通过请求触发数据：

```bash
curl -X POST "http://127.0.0.1:1933/api/v1/search/find" \
  -H "Authorization: Bearer $OPENVIKING_API_KEY" \
  -H "X-OpenViking-Account: default" \
  -H "X-OpenViking-User: default" \
  -H "Content-Type: application/json" \
  -d '{"query":"hello","limit":3}'
```

查询 Console BFF：

```bash
curl "http://127.0.0.1:1933/api/v1/console/dashboard/summary" \
  -H "Authorization: Bearer $OPENVIKING_API_KEY" \
  -H "X-OpenViking-Account: default" \
  -H "X-OpenViking-User: default" \
```

如果使用 Console server，则访问 `/console/api/v1/ov/console/*` 代理路径。

## 测试

相关单测：

```bash
.venv/bin/python -m pytest \
  tests/observability/test_events.py \
  tests/observability/test_usage_audit_store.py \
  tests/observability/test_usage_audit_worker.py \
  tests/observability/test_console_router.py \
  tests/observability/test_memory_access.py \
  tests/observability/test_usage_audit_runtime.py \
  tests/observability/test_usage_audit_inventory.py \
  tests/misc/test_console_proxy.py
```

相关 lint：

```bash
.venv/bin/python -m ruff check \
  openviking/observability/events.py \
  openviking/observability/usage_audit \
  openviking/server/routers/console.py \
  tests/observability
```

## 常见问题

### Console 查询为什么返回 `enabled=false`？

通常是 `server.observability.usage_audit.enabled=false`，或者 Usage/Audit runtime 没有初始化成功。
先看 server 启动日志中是否有 `Usage/Audit store initialized with sqlite backend`。

### 为什么 Dashboard 今天没有 Token？

确认模型调用事件是否触发：

- VLM 需要产生 `vlm.call`
- Embedding 需要产生 `embedding.call`

统计数据写入时按 UTC 保存；Console 查询会优先使用请求里的 `timezone` 参数做读端分桶。
如果请求没有传 `timezone`，才会使用 `server.observability.usage_audit.timezone` 作为兜底。

### 为什么请求日志里没有 Console 自己的请求？

这是预期行为。`/api/v1/console/*` 和 `/console/*` 会被排除，避免 Console 页面刷新污染产品请求审计。

### 为什么普通用户访问 Console BFF 是 403？

Console BFF 查询的是账号级聚合和审计明细，当前只允许 `ROOT` / `ADMIN` 访问。

### SQLite 文件在哪里？

如果没有配置 `sqlite_path`，默认在 OpenViking workspace 下：

```text
<workspace>/_system/usage_audit/usage_audit.sqlite3
```

可以通过 `server.observability.usage_audit.sqlite_path` 显式指定。

### 生产多实例怎么部署？

当前实现只有 SQLite backend，更适合单机本地版。多实例生产环境需要共享 store backend，避免每个实例只持有自己的局部统计。后续扩展时应实现 `UsageAuditStore` 协议，而不是改 Console BFF。
