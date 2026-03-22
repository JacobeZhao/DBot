# DBot - Natural Language Database Tool

DBot 是一个自然语言驱动的数据库管理工具。用户通过聊天对话，即可完成 SQLite 数据库的增删改查和表结构管理，无需编写 SQL。

## 功能特性

- **自然语言交互** — 用中文或英文描述需求，LLM 自动转换为数据库操作
- **工具调用确认** — 危险操作（删除、修改结构）需用户确认后执行
- **多 LLM 支持** — 支持 DeepSeek、OpenAI 及任何 OpenAI 兼容 API
- **实时数据表** — 右侧面板展示表数据，支持搜索、分页、CSV 导出
- **可拖拽布局** — 聊天面板和数据面板之间可自由拖拽调整宽度
- **深色/浅色主题** — 一键切换，自动记忆偏好
- **聊天记录持久化** — 刷新页面不丢失对话历史

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python, FastAPI, SQLite |
| 前端 | React 18, Vite, Axios |
| LLM | DeepSeek / OpenAI 兼容 API（Function Calling） |

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- npm 或 pnpm

### 1. 安装后端依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env` 并填入 API 密钥：

```env
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
DB_PATH=./dataspeak.db
```

### 3. 启动后端

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --app-dir . --reload
```

后端运行在 `http://127.0.0.1:8000`，API 文档见 `/docs`。

### 4. 启动前端

```bash
cd frontend-react
npm install
npm run dev
```

前端开发服务器默认运行在 `http://localhost:3000`。

## 项目结构

```
DBot/
├── backend/
│   ├── main.py              # FastAPI 入口，所有 API 端点
│   ├── config.py            # 多 LLM 提供商配置管理
│   ├── database.py          # SQLite 初始化与连接
│   ├── state.py             # 数据类定义（会话、消息、工具调用等）
│   ├── handlers/
│   │   └── chat_handler.py  # 聊天工作流编排
│   ├── services/
│   │   └── deepseek_service.py  # LLM API 调用与工具解析
│   └── tools/
│       ├── registry.py      # 工具注册与确认逻辑
│       ├── init_tools.py    # 工具注册入口
│       ├── db_tools.py      # 数据 CRUD 工具
│       └── schema_tools.py  # 表结构 DDL 工具
├── frontend-react/          # React + Vite 前端
│   └── src/
│       ├── App.jsx          # 主布局（头部、拖拽分割、面板）
│       ├── context/
│       │   └── AppContext.jsx  # 全局状态管理
│       ├── components/
│       │   ├── ChatInterface.jsx   # 聊天面板
│       │   ├── DataTable.jsx       # 数据表面板
│       │   ├── MessageItem.jsx     # 消息渲染（Markdown 支持）
│       │   ├── ToolCallView.jsx    # 工具调用展示卡片
│       │   ├── ThinkingIndicator.jsx # 思考中动画
│       │   └── Toast.jsx           # 通知提示
│       └── services/
│           └── apiService.js       # API 请求封装
├── frontend/                # 旧版纯 HTML 前端（已弃用）
├── requirements.txt
├── .env                     # 环境变量（不提交）
└── .gitignore
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v2/chat` | 发送聊天消息 |
| POST | `/v2/confirm` | 确认/拒绝待执行操作 |
| GET | `/v2/tables` | 列出所有用户表 |
| GET | `/v2/tables/{name}` | 查询表数据 |
| POST | `/v2/tables` | 创建表 |
| DELETE | `/v2/tables/{name}` | 删除表 |
| GET | `/v2/config` | 获取配置 |
| PUT | `/v2/config` | 更新配置 |

## 工作流程

1. 用户在聊天面板输入自然语言指令
2. 后端将消息和工具定义发送给 LLM
3. LLM 返回工具调用请求（如 `insert_row`、`query_data`）
4. 安全操作自动执行；危险操作弹出确认对话框
5. 工具执行结果回传 LLM，生成最终自然语言回复
6. 数据表面板自动刷新，展示最新数据

## 许可证

MIT
