# 星海优选 · 智能客服 + 商城 Agent 系统

一个可直接运行的全栈电商 demo：**商城前台（商品 / 购物车 / 下单）+ 智能客服（多轮对话 / 工具调用 / 私有知识库 / 退款风控 / 人工审核）+ 运营后台（商品 / 订单 / 审核 / 知识库）**。
三者共用一套用户与订单数据——商城下的单，客服能直接查；后台发的货，客服能直接报物流。

- 商城前台：http://127.0.0.1:8000/shop
- 客服端：http://127.0.0.1:8000
- 运营后台：http://127.0.0.1:8000/admin

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 买家（黄金会员） | `user01` | `user123` |
| 买家（白银会员） | `user02` | `user123` |
| 客服主管 | `admin` | `admin123` |

> 仓库地址：https://github.com/myzhgjb/smart-cs-agent ｜ 以下截图均为本机实际运行抓取（1440×1000），非设计稿。

---

## 界面预览

> 截图均为本机实际运行抓取（1440×1000），非设计稿。图片走 jsDelivr CDN，若加载失败可直接查看仓库 `docs/screenshots/` 目录。

**客服端** · 意图识别 → 知识检索 / 工具调用 → 流式回答，右侧实时展示处理链路

![智能客服对话](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/01-chat.png)

**商城前台** · 分类、搜索、排序与商品卡片，价格库存与客服共用一份数据

![商城前台](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/02-shop.png)

**商品详情** · 卖点、参数、标签、库存与评分，可直接加购或问客服

![商品详情](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/03-product.png)

**购物车** · 改数量、移除、实时小计，服务端持久化

![购物车](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/04-cart.png)

**我的订单** · 状态、明细、物流单号，一键「咨询客服 / 申请退货」

![我的订单](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/05-orders.png)

**人工审核** · 风控触发规则、订单与退款对照、一键通过或驳回

![人工审核](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/06-admin-audit.png)

**商品管理** · 新增、编辑、上下架，改价改库存即时生效

![商品管理](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/07-admin-products.png)

**订单管理** · 状态筛选、订单号/买家搜索、一键发货生成运单号

![订单管理](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/08-admin-orders.png)

**私有知识库** · 上传 PDF/DOCX/MD/TXT，自动切分入库，可检索自测

![私有知识库](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/09-admin-kb.png)

**会话回放** · 全量会话、意图标签、知识引用与系统通知

![会话回放](https://gcore.jsdelivr.net/gh/myzhgjb/smart-cs-agent@main/docs/screenshots/10-admin-replay.png)

---

## 一、项目来源与改造说明

**上游项目**：[WangWeiqiang-UCAS/E-commerce-Smart-Agent](https://github.com/WangWeiqiang-UCAS/E-commerce-Smart-Agent)（167 star，FastAPI + LangGraph + PostgreSQL/pgvector + Redis + Celery + Gradio）。

本项目在其基础上做了两件事：**① 把依赖重写为单机可运行**（去掉 PG/Redis/Celery/Gradio）；**② 补齐电商闭环**（商城前台、商品与购物车、订单后台、商品咨询工具）。上游 README 保留在 `README.upstream.md`，git 历史完整保留。

原项目强依赖 Docker、PostgreSQL(pgvector)、Redis 与通义千问 Embedding，在本机（Windows / 无 Docker / 无 MySQL / 无 Redis / DeepSeek 无 Embedding 接口）无法启动。因此在**保留业务模型与 Agent 设计**的前提下做了工程化改造：

| 模块 | 上游实现 | 本项目实现 | 原因 |
| --- | --- | --- | --- |
| 关系库 | PostgreSQL + SQLModel | SQLite + SQLModel | 单机零依赖，随项目文件迁移 |
| 向量检索 | pgvector + 通义 Embedding | 本地 BM25（jieba 分词） | 无 Embedding 接口、数据不出本机 |
| 会话编排 | LangGraph + Redis Checkpointer | 显式编排 + 会话表持久化 | 去掉 Redis，链路可观测、易调试 |
| 异步任务 | Celery + Redis | FastAPI 进程内异步 + WebSocket | 单机部署不需要消息队列 |
| 前端 | Gradio 内嵌页面 | 原生 SPA（客服端 + 管理台） | 前后端分离，界面可控 |
| 大模型 | 通义千问 | DeepSeek（OpenAI 兼容协议） | 使用本机已有 Key |
| 认证 | passlib + bcrypt | hashlib PBKDF2 + JWT | 规避 bcrypt 在 Py3.13 的兼容问题 |

上游 README 保留在 `README.upstream.md`，git 历史完整保留。

---

## 二、系统架构

```
                    ┌──────────────────────────────────────────┐
  浏览器             │  FastAPI (app/main.py)                    │
┌───────────┐       │                                          │
│ 商城前台   │◄─────►│  /api/v1/mall/*        商品 / 购物车 / 下单 │
│ 客服端 SPA │◄─────►│  /api/v1/chat/stream   SSE 流式对话        │
│ 管理台 SPA │◄─────►│  /api/v1/admin/*       审核 / 回放 / 知识库 │
└───────────┘  WS   │                       商品 / 订单管理      │
                    │  /api/v1/ws            审核结果实时推送     │
                    │                                          │
                    │  ┌──────────────── 对话引擎 ────────────┐  │
                    │  │ 意图路由（规则 + 大模型兜底）          │  │
                    │  │   ├─ ORDER      → 订单工具            │  │
                    │  │   ├─ LOGISTICS  → 物流工具            │  │
                    │  │   ├─ INVOICE    → 发票工具            │  │
                    │  │   ├─ REFUND     → 退款业务 + 风控      │  │
                    │  │   ├─ POLICY     → 知识库检索           │  │
                    │  │   └─ HUMAN      → 转人工登记           │  │
                    │  │ 生成节点：检索片段 + 业务数据 → 流式回答 │  │
                    │  └──────────────────────────────────────┘  │
                    │        │                    │             │
                    │   SQLite(app.db)       BM25 内存索引        │
                    │  用户/商品/购物车/订单                   │
                    └────────┼──────────────────────────────────┘
                             │
                      DeepSeek API（仅推理，不写回业务数据）
```

**关键设计：确定性业务逻辑与生成逻辑分离。** 金额、时效、资格、风控阈值全部由 SQL + 规则判定，大模型只负责组织语言，避免"编造订单状态/退款金额"。

---

## 三、目录结构

```
智能客服系统/
├── app/
│   ├── main.py              FastAPI 入口（lifespan 建表 / 种子 / 索引）
│   ├── models.py            11 张表：用户、商品、购物车、订单、发票、退款、审核、知识、会话
│   ├── seed.py              演示数据（3 用户 / 7 订单 / 2 发票）
│   ├── seed_products.py     13 个商品（4 个分类）
│   ├── core/
│   │   ├── config.py        pydantic-settings 配置
│   │   ├── db.py            SQLite + aiosqlite 异步会话
│   │   └── security.py      PBKDF2 密码 + JWT
│   ├── agent/
│   │   ├── engine.py        意图路由 → 工具 → 检索 → 流式生成
│   │   ├── tools.py         订单 / 物流 / 发票 / 退款 / 商品工具
│   │   ├── llm.py           DeepSeek 客户端（普通 + 流式）
│   │   └── prompts.py       路由与回答 Prompt（强约束不编造）
│   ├── rag/
│   │   ├── bm25.py          中文分词 + BM25 + IDF 覆盖率
│   │   └── ingest.py        PDF/DOCX/MD/TXT 解析、切分、入库、建索引
│   ├── services/
│   │   ├── refund.py        资格校验、风险分级、审核决策
│   │   └── notify.py        WebSocket 连接池
│   ├── api/                 auth / chat / admin / ws
│   └── frontend/            index.html(客服) · shop.html(商城) · admin.html(后台)
│                            app.js · shop.js · admin.js · styles.css · shop.css
├── docs/screenshots/         README 截图（本机实拍）
├── data/
│   ├── app.db               SQLite（首次启动自动生成）
│   ├── knowledge/           内置私有知识文档（5 篇，29 个片段）
│   └── uploads/             管理台上传的原始文档
├── requirements.txt
├── start.bat / start.sh
└── .env                     DeepSeek Key 与 JWT 密钥（已在 .gitignore 中）
```

---

## 四、快速启动

### 1. 首次安装

```bash
cd C:\code\智能客服系统
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple
```

> 本机 PyPI 官方源不可达，必须走国内镜像（清华源对 pip 26 返回 403，推荐腾讯云镜像）。

### 2. 配置

复制 `.env.example` 为 `.env`，填入 DeepSeek Key：

```ini
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
SECRET_KEY=用 openssl rand -hex 32 生成
```

### 3. 启动

```bash
start.bat            # Windows 双击即可
# 或
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

首次启动会自动：建表 → 写入演示用户/订单/发票 → 解析 `data/knowledge/*.md` → 建立 BM25 索引。

### 4. 重置数据

删除 `data/app.db` 后重启即可重新初始化（知识文档不丢失）。

---

## 五、功能清单

**商城前台**
- 分类筛选、关键词搜索、销量/价格排序
- 商品卡片与详情弹层（卖点、参数、标签、库存、评分）
- 购物车抽屉：改数量、移除、实时小计（服务端持久化）
- 结算填写地址 → 生成待付款订单 → 模拟支付
- 我的订单：状态、明细、物流单号；一键「咨询客服」「申请退货」

**客服端**
- SSE 流式回复，逐 token 渲染，带意图标签与处理链路追踪
- 订单卡片、物流时间轴卡片、退款申请卡片、发票卡片
- 知识库引用：展示命中的文档标题、分类、片段与相关度
- 多轮会话：左侧会话列表，历史消息可回看（含卡片快照）
- 快捷问题、上下文联想、转人工

**运营后台**
- 概览：待审工单、今日咨询、知识片段、累计退款金额
- 商品管理：新增 / 编辑 / 上下架，价格库存即时生效到商城与客服
- 订单管理：按状态筛选、订单号/买家搜索、一键发货（生成运单号）、确认签收
- 审核工单：风险等级、触发规则、用户诉求原文、订单/退款对照，一键通过/驳回（备注回写用户会话）
- 会话回放：全量会话列表，逐条查看意图、引用与系统通知
- 知识库：上传 PDF/DOCX/MD/TXT → 自动解析切分入库 → 重建索引 → 检索自测
- WebSocket 实时提醒：新工单、用户转人工

**三端联动**
1. 商城下单 → 客服查「我的订单」能查到这笔单（金额、商品、地址一致）
2. 后台点「发货」→ 客服查物流能读到承运商、运单号与时间轴
3. 订单签收 → 客服可直接走退货流程，触发风控转人工

**业务规则**
- 7 天无理由（质量问题 15 天），超期拦截
- 内衣/贴身/定制/生鲜/已激活数码拆封后不支持无理由退货
- 重复退款申请拦截
- 退款金额 ≥ 500 转人工，≥ 2000 标记高风险
- 低风险（< 500）自动通过

---

## 六、私有知识库说明

- 文档落在本机 `data/knowledge/`（内置）与 `data/uploads/`（后台上传），**不经过任何第三方向量库**。
- 检索为本地 BM25：jieba 分词 → 倒排索引 → BM25 打分 → 按查询词 IDF 覆盖率过滤（阈值 0.15）→ 同文档最多 2 段 → Top 4。
- 只有命中的片段会拼进 Prompt；命中为空时直接返回"未查到"，不调用大模型编造。
- 管理台「检索自测」可实时查看召回片段与分数，便于调阈值、补文档。

---

## 七、主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | 登录，返回 JWT |
| GET | `/api/v1/auth/me` | 当前用户 |
| POST | `/api/v1/chat/stream` | SSE 流式对话（intent / sources / card / token / done） |
| GET | `/api/v1/mall/products` | 商品列表（分类 / 搜索 / 排序） |
| GET/POST/PATCH/DELETE | `/api/v1/mall/cart` | 购物车读写 |
| POST | `/api/v1/mall/checkout` | 结算下单（写 orders 表并扣库存） |
| POST | `/api/v1/mall/orders/{sn}/pay` | 模拟支付 |
| GET | `/api/v1/mall/orders` | 我的订单 |
| GET | `/api/v1/chat/threads` | 我的会话列表 |
| GET | `/api/v1/chat/threads/{id}/messages` | 会话消息 |
| GET | `/api/v1/admin/stats` | 概览统计 |
| GET | `/api/v1/admin/audits?status=pending` | 审核工单 |
| POST | `/api/v1/admin/audits/{id}/decide` | 通过 / 驳回 |
| GET | `/api/v1/admin/threads` | 全部会话 |
| GET | `/api/v1/admin/kb/docs` | 知识文档列表 |
| POST | `/api/v1/admin/kb/upload` | 上传文档并入库 |
| GET | `/api/v1/admin/kb/search?q=` | 检索自测 |
| GET/POST/PATCH/DELETE | `/api/v1/admin/products` | 商品管理 |
| GET | `/api/v1/admin/orders` | 订单管理 |
| POST | `/api/v1/admin/orders/{id}/ship` | 发货（生成运单号） |
| WS | `/api/v1/ws?token=` | 审核结果 / 新工单 / 转人工推送 |

交互式文档：http://127.0.0.1:8000/docs

---

## 八、面试可讲的技术点

1. **意图识别双通道**：高频句式用关键词规则命中（0 延迟、可解释），长尾交给 LLM 输出 JSON（带 `order_sn` 槽位），规则兜底避免模型抖动。
2. **确定性业务与大模型解耦**：退款资格、风控等级、金额全部走 SQL + 规则，LLM 只做语言组织；Prompt 明确禁止编造订单状态。
3. **RAG 的工程取舍**：没有 Embedding 服务时，用 BM25 + 中文分词 + IDF 覆盖率阈值，以「命中覆盖率」而非「相似度分数」做拒答判断，避免阈值随语料漂移。
4. **HITL 闭环**：风控命中 → 落审核单 → WebSocket 推管理台 → 管理员决策 → 结果推回用户会话并落库，用户刷新仍可见。
5. **多轮上下文**：会话表按 `thread_id` 持久化，取最近 6 条拼上下文；用 `awaiting` 标记"等订单号"状态，解决指代与省略。
6. **商城与客服共用订单表**：结算直接写 `orders`，客服工具层只读同一张表，避免"两个系统两套数据"的典型割裂；库存扣减与订单创建在同一事务内完成。
7. **SSE 而非 WebSocket 做对话流**：单向 token 流用 SSE 更简单，天然支持断线重连；WebSocket 只承担需要双向的低频通知。
