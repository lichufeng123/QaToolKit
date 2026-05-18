# QAToolKit

这是一个长期维护型 QA Agent 工具箱。当前包含三条独立能力线：

- 接口测试 Agent：把公司 Qwen 大模型和 `api_tester_mcp` 串起来做 Swagger/OpenAPI 接口测试。
- 禅道统计 Agent：读取版本起测配置，统计禅道缺陷数据，并生成测试统计报告。
- 测试用例导入 Agent：读取多 Sheet Excel 测试用例表，通过 ZenTao API 批量上传测试用例。

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
│       ├── testcase_import/      # Excel 测试用例导入 Agent
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

### Web 平台

现在已经有第一版 Web 入口，适合不想每次敲命令时使用：

```bash
python -m qatoolkit web
```

默认访问：

```text
http://127.0.0.1:8000/
```

也可以指定端口：

```bash
python -m qatoolkit web --host 127.0.0.1 --port 8010
```

Web 第一版包含：

- 接口测试任务创建
- Excel 测试用例导入 dry-run / 正式上传
- 迭代统计查询 / HTML 报告生成
- 系统配置中心：Qwen、ZenTao、api_tester_mcp、默认接口测试参数
- 任务列表、任务详情、执行日志、输出 JSON、报告链接
- 历史任务持久化、双击查看详情、删除任务记录
- 任务搜索、状态筛选、类型筛选
- 一键清理失败任务
- 日志和输出折叠查看

配置中心会把本机配置保存到：

```text
artifacts/config/settings.local.json
```

配置读取优先级：

```text
settings.local.json > .env > 代码默认值
```

敏感字段不会在页面回显明文。密码、token、API key 留空保存时会保留旧值；勾选清空时才会删除对应本地配置。

配置中心支持校验：

- `api_tester_mcp` 路径是否存在
- ZenTao 登录与产品 Bug 列表是否可访问
- Qwen OpenAI-Compatible `/chat/completions` 是否可用

所有 Web 任务会统一记录到：

```text
artifacts/tasks/
```

其中包含任务数据库、上传文件、任务输入输出和执行日志。关闭 Web 进程后再次启动，历史任务仍可在页面里追溯。这个目录属于运行产物，不会提交到 Git。

接口测试依赖 `api_tester_mcp`，可以在页面表单里填写路径，或在 `.env` 中配置：

```text
API_TESTER_MCP_SOURCE=E:\个人文件\MCP\api_tester_mcp-1.5.3
```

安装或更新依赖：

```bash
pip install -e .
```

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

## 测试

当前核心测试使用 Python 标准库 `unittest`，不需要额外测试框架：

```bash
python -m unittest discover -s tests
```

测试重点覆盖：

- 禅道迭代统计的日期过滤、关闭率、研发中文名映射
- Excel 用例导入的 Sheet 模块映射、步骤/预期对齐、删除线跳过
- Web 任务库的失败任务批量清理
- 本地配置优先级、敏感字段清理回退

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
- 登录参数通过 `.env` 或系统环境变量配置，不要把真实账号密码写进 README。

推荐配置环境变量：

```text
ZENTAO_BASE_URL=http://your-zentao-server/api.php/v2
ZENTAO_ACCOUNT=your-zentao-account
ZENTAO_PASSWORD=your-zentao-password
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

示例 `V3.4` 起测日期为 `2026-05-10`。如果不指定 `--end-date`，默认会统计到今天。演示时可以指定一个截止日期：

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
ZENTAO_BASE_URL=http://your-zentao-server/api.php/v2
ZENTAO_ACCOUNT=your-zentao-account
ZENTAO_PASSWORD=your-zentao-password
ZENTAO_PRODUCT_ID=8
ITERATIONS_FILE=data\iterations.json
```

现在代码默认流程是：

```text
POST {ZENTAO_BASE_URL}/users/login
GET  {ZENTAO_BASE_URL}/products/8/bugs
```

本地 `sample_zentao_bugs.json` 只保留给没有接 ZenTao 服务时的离线调试，不作为正式统计来源。

## Excel 测试用例批量上传

新增了一个 Excel 批量上传测试用例能力，用来把“当前版本汇总测试用例表”按 Sheet 逐个导入 ZenTao。

当前规则：

- 接口：`POST /testcases`
- 产品 ID：默认固定 `8`
- 鉴权：请求头 `token`
- 支持多 Sheet 工作簿逐 Sheet 上传
- 默认优先使用 Excel 里的“模块”列；如果没有，就回退用 Sheet 名匹配模块
- 模块名会按固定映射绑定：
  - `首页 -> 121`
  - `AI员工 -> 122`
  - `AI群组 -> 123`
  - `工作流 -> 124`
  - `公共支持服务 -> 125`
  - `个人中心 -> 126`
  - `赛点详情 -> 158`
  - `资产库 -> 159`
  - `需求池 -> 168`
  - `登录 -> 172`

支持的表头别名包括：

- `用例标题 / 标题 / 用例名称`
- `模块 / 所属模块`
- `优先级`
- `用例类型 / 类型`
- `前置条件`
- `步骤 / 测试步骤 / 操作步骤`
- `预期 / 预期结果`
- `相关需求`
- `所属项目`
- `所属执行`

执行上传：

```bash
python -m qatoolkit import-testcases --excel-file C:\Users\Insight\PycharmProjects\QAToolKit\data\V3.4测试用例汇总1.xlsx
```

只校验 Excel 解析和模块映射，不真正上传：

```bash
python -m qatoolkit import-testcases --excel-file C:\path\to\testcases.xlsx --dry-run
```

只传指定 Sheet：

```bash
python -m qatoolkit import-testcases --excel-file C:\path\to\testcases.xlsx --sheet 首页 --sheet 工作流
```

每次执行都会输出一份带时间戳的结果 JSON，不覆盖历史记录，例如：

```text
artifacts/testcase_imports/testcases_zentao_import_20260514_110000.json
```

导入结果 JSON 会记录每条用例的请求体、脱敏后的请求头、请求地址和接口返回体，方便回溯实际上传情况。
