# QAToolKit

这是一个长期维护型 QA Agent 工具箱。当前包含两条独立能力线：

- 接口测试 Agent：把公司 Qwen 大模型和 `api_tester_mcp` 串起来做 Swagger/OpenAPI 接口测试。
- 禅道统计 Agent：读取版本起测配置，统计禅道缺陷数据，并生成测试统计报告。

## 项目结构

```text
QAToolKit/
├── data/                         # 业务配置和本地样例数据
│   ├── iterations.json           # 版本迭代配置
│   └── sample_zentao_bugs.json   # 禅道缺陷样例数据
├── qatoolkit/                    # 根目录启动壳，支持 python -m qatoolkit
├── src/
│   ├── fastmcp/                  # 开发期兼容垫片，避免未安装 MCP SDK 时导入失败
│   └── qatoolkit/
│       ├── api_testing/          # 接口测试 Agent
│       │   ├── agent.py
│       │   ├── mcp_bridge.py
│       │   └── specs.py
│       ├── iteration_stats/      # 迭代/禅道统计 Agent
│       │   └── service.py
│       ├── mcp_servers/          # MCP Server 入口
│       │   └── zentao_stats.py
│       ├── shared/               # 公共能力
│       │   ├── config.py
│       │   ├── llm.py
│       │   └── paths.py
│       ├── cli.py                # 统一 CLI
│       └── __main__.py
└── artifacts/                    # 运行产物，已加入 .gitignore
```

原则很简单：`qatoolkit` 是工具箱顶层包；新增一个 Agent，就新增一个独立业务目录；跨 Agent 复用的东西才放到 `shared/`。接口测试只是 `api_testing/`，不能拿 `api_agent` 当全项目根包，那个名字一看就跑偏。

它现在做的事很直接：

- 支持任意 Swagger/OpenAPI URL
- 自动解析接口文档
- 用公司 Qwen 生成测试策略
- 通过 `api_tester_mcp` 生成场景、测试用例和报告
- 默认先跑 smoke，避免一上来把接口轰个稀碎

## 环境变量

复制 `.env.example` 后配置：

- `QWEN_BASE_URL`
- `QWEN_API_KEY`
- `QWEN_MODEL`
- `QWEN_TIMEOUT`
- `SWAGGER_UI_URL`
- `SPEC_URL`
- `API_TESTER_MCP_SOURCE`
- `OUTPUT_DIR`
- `SMOKE_MAX_ENDPOINTS`
- `DEFAULT_LANGUAGE`
- `DEFAULT_FRAMEWORK`

默认按 OpenAI-Compatible 方式调用公司 Qwen：

```text
POST {QWEN_BASE_URL}/chat/completions
```

如果你们公司的 Qwen 服务协议不是这个格式，我再帮你把客户端适配掉。

程序启动时会自动读取项目根目录的 `.env` 文件，并且不会覆盖当前 PowerShell 会话里已经存在的环境变量。

## 安装

```bash
pip install -e .
```

## 运行

先跑 Petstore：

```bash
qatoolkit run --swagger-ui-url https://petstore.swagger.io/
```

直接指定 OpenAPI JSON 也可以：

```bash
qatoolkit run --spec-url https://petstore.swagger.io/v2/swagger.json
```

切换到别的 Swagger 地址时，只要换参数就行：

```bash
qatoolkit run --swagger-ui-url https://example.com/swagger/
```

如果你的 Swagger 页面没有直接暴露 spec，CLI 会尝试常见路径，例如：

- `swagger.json`
- `v2/swagger.json`
- `openapi.json`

## 产物

运行后会生成：

- `artifacts/swagger-spec.json`
- `artifacts/run-summary.json`
- `artifacts/spec-summary.md`
- `artifacts/test-plan.json`
- `artifacts/smoke-results.json`
- `artifacts/output/reports/*.html`

## CLI

### `run`

执行完整流程：

- 拉取 spec
- 用 Qwen 产出测试计划
- 调 `api_tester_mcp` 生成场景和用例
- 执行 smoke 或 full

常用参数：

- `--swagger-ui-url`
- `--spec-url`
- `--mode smoke|full`
- `--language`
- `--framework`
- `--base-url`
- `--auth-bearer`
- `--auth-apikey`
- `--auth-basic`
- `--max-concurrent`

### `inspect`

只做文档分析和计划预览，不执行测试。

## 说明

这套结构里，适合交给 AI 的东西都走 Qwen：

- 文档理解
- 测试策略
- 测试重点排序
- 失败摘要

真正发请求、生成结果、出 HTML 报告的部分，交给 `api_tester_mcp`。
这样 token 省得更像样，也不容易让模型在执行层乱来。

## 禅道迭代统计

新增了一个版本迭代测试统计模块，用来回答类似“当前迭代测试情况怎么样？”这类问题。

当前已支持：

- 版本起测时间配置
- 缺陷提交总量和当日提交量
- 缺陷关闭总量和当日关闭量
- 遗留缺陷数量
- 研发解决和遗留分布
- 每日提交、关闭、日末遗留趋势
- 严重等级、提交人分布
- 关闭率、平均修复时长、风险提示
- HTML 统计报告
- 真实 ZenTao API 登录、拉取产品 Bug 列表、再加工统计

默认配置文件：

- `data/iterations.json`
- `data/sample_zentao_bugs.json`

注意：如果配置了 ZenTao 真实接口，统计会优先走 API 登录与拉取，不再依赖本地样例。只有在显式开启 `ZENTAO_ALLOW_SAMPLE_FALLBACK=1` 时，才会回退到 `data/sample_zentao_bugs.json` 做离线演示。

当前 ZenTao 接口约定如下：

- 登录接口：`POST /users/login`
- 产品 Bug 接口：`GET /products/8/bugs`
- 固定产品 ID：`8`
- 登录参数：`account=lichufeng`，`password=Tiexie520+`

推荐配置环境变量：

```text
ZENTAO_BASE_URL=http://api.idc.insight-aigc.com/api.php/v2
ZENTAO_ACCOUNT=lichufeng
ZENTAO_PASSWORD=Tiexie520+
ZENTAO_PRODUCT_ID=8
```

如果你们的鉴权方式需要把 token 放到别的 Header 里，代码里已经做了几种兼容尝试，后面如果接口文档再细一点，我再把那层收紧成你们的正式约定。

如果想把研发账号显示成中文名，可以配置 `ZENTAO_USER_MAP_FILE`。它可以是一个 JSON 列表，程序会尝试按账号拼音去匹配中文名，匹配成功就显示中文，匹配不到就保留原账号，避免把人认错。例如：

```json
[
  "赖彦彰",
  "石浩栋",
  "李建锦",
  "庞恒",
  "陈健豪",
  "田晓光",
  "王陈龙",
  "杨皓庆",
  "杜志蒙"
]
```

报告里的“研发处理分布”和“每日趋势”都是可展开的，点对应研发名或日期后，会直接展开看到遗留 Bug 明细。

示例 `V3.4` 起测日期为 `2026-05-16`。如果不指定 `--end-date`，默认查到今天会得到“起测日期晚于截止日期”的提示。演示时可以指定一个截止日期：

```bash
python -m qatoolkit iteration-stats --iteration V3.4 --end-date 2026-05-20
```

生成报告：

```bash
python -m qatoolkit iteration-report --iteration V3.4 --end-date 2026-05-20
```

报告会输出到带时间戳的 HTML 文件，不会覆盖历史结果，例如：

```text
artifacts/iteration_reports/V3.4_test_stats_2026-05-20_20260514_103533.html
```

### 禅道 MCP Server

MCP 工具入口：

```bash
python -m qatoolkit.mcp_servers.zentao_stats
```

如果要作为真正 MCP Server 启动，需要安装 MCP SDK：

```bash
pip install -e ".[mcp]"
```

当前暴露 3 个工具：

- `list_iterations`
- `get_iteration_test_stats`
- `generate_iteration_report`

### 接真实禅道 API

先配置环境变量：

```text
ZENTAO_BASE_URL=http://api.idc.insight-aigc.com/api.php/v2
ZENTAO_ACCOUNT=lichufeng
ZENTAO_PASSWORD=Tiexie520+
ZENTAO_PRODUCT_ID=8
ITERATIONS_FILE=data\iterations.json
```

现在代码默认流程是：

```text
POST {ZENTAO_BASE_URL}/users/login
GET  {ZENTAO_BASE_URL}/products/8/bugs
```

本地 `sample_zentao_bugs.json` 只保留给没有接 ZenTao 服务时的离线调试，不作为正式统计来源。
