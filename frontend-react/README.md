# DBot Frontend (新版本)

基于React的DBot NL2CLI前端应用，支持DeepSeek函数调用和增强的确认机制。

## 功能特性

- **自然语言数据库操作**：通过聊天界面进行数据库查询、插入、更新、删除等操作
- **DeepSeek函数调用**：集成DeepSeek AI，支持OpenAI兼容的函数调用接口
- **智能确认机制**：弹窗确认 + 自动执行模式，支持置信度阈值配置
- **实时数据展示**：左侧数据库面板显示表列表和数据预览
- **完整的表管理**：创建、删除表，添加/删除/重命名字段
- **响应式设计**：适配桌面和移动设备
- **配置管理**：可配置LLM提供商、温度、自动执行设置等

## 技术栈

- **前端框架**：React 18.2
- **构建工具**：Vite 5.0
- **状态管理**：React Context + useReducer
- **HTTP客户端**：Axios
- **样式方案**：原生CSS + CSS模块
- **代理配置**：Vite开发服务器代理到后端API

## 项目结构

```
frontend-react/
├── src/
│   ├── components/          # React组件
│   │   ├── ChatInterface.jsx   # 聊天界面主组件
│   │   ├── MessageList.jsx     # 消息列表
│   │   ├── MessageItem.jsx     # 单条消息
│   │   ├── MessageInput.jsx    # 消息输入框
│   │   ├── ToolCallView.jsx    # 工具调用显示
│   │   ├── ConfirmationModal.jsx # 确认弹窗
│   │   ├── DatabasePanel.jsx   # 数据库面板
│   │   ├── DataTable.jsx       # 数据表格
│   │   └── SettingsPanel.jsx   # 设置面板
│   ├── context/            # 状态管理
│   │   └── AppContext.jsx     # 全局状态上下文
│   ├── services/           # API服务
│   │   └── apiService.js      # 后端API封装
│   ├── styles/            # 样式文件
│   │   ├── App.css           # 应用主样式
│   │   ├── index.css         # 全局样式
│   │   └── 组件相关样式文件...
│   ├── App.jsx            # 根组件
│   └── index.jsx          # 应用入口
├── public/               # 静态资源
├── index.html           # HTML模板
├── vite.config.js       # Vite配置
├── package.json         # 依赖配置
└── README.md           # 项目说明
```

## API接口

前端通过Vite代理访问后端API（`/api` → `http://127.0.0.1:8001/v2`）：

- `GET /api/health` - 健康检查
- `GET /api/config` - 获取配置
- `PUT /api/config` - 更新配置
- `GET /api/tables` - 获取表列表
- `GET /api/tables/{table}` - 获取表数据
- `POST /api/tables` - 创建表
- `DELETE /api/tables/{table}` - 删除表
- `POST /api/chat` - 发送聊天消息
- `POST /api/confirm` - 确认操作
- `GET /api/sessions/{id}` - 获取会话信息
- `PUT /api/sessions/{id}/auto-execute` - 更新自动执行设置

## 安装和运行

### 前置要求

- Node.js 18+ 和 npm/yarn
- 后端服务运行在 `http://127.0.0.1:8001`

### 安装依赖

```bash
cd frontend-react
npm install
# 或
yarn install
```

### 开发模式

```bash
npm run dev
# 或
yarn dev
```

应用将在 `http://localhost:3000` 启动，并通过代理连接到后端API。

### 生产构建

```bash
npm run build
# 或
yarn build
```

构建产物在 `dist/` 目录。

### 预览构建结果

```bash
npm run preview
# 或
yarn preview
```

## 状态管理

应用使用React Context进行状态管理，主要状态包括：

- **会话状态**：当前会话、消息历史
- **数据库状态**：表列表、当前表、表数据
- **确认状态**：待确认的操作
- **设置状态**：自动执行配置、LLM设置
- **配置状态**：后端配置同步

## 组件说明

### ChatInterface
聊天界面主组件，包含消息列表和输入框。处理消息发送和接收逻辑。

### ConfirmationModal
确认弹窗组件，显示待确认的操作详情，提供批准/拒绝功能。

### DatabasePanel
数据库面板，显示表列表和数据预览。支持表搜索、筛选和刷新。

### SettingsPanel
设置面板，配置自动执行、LLM参数等系统设置。

### ToolCallView
工具调用详情组件，显示AI调用的工具名称、参数、状态和结果。

## 开发指南

### 添加新组件

1. 在 `src/components/` 创建组件文件
2. 在 `src/styles/` 创建对应的样式文件
3. 在需要的地方导入和使用组件

### 添加新API接口

1. 在 `src/services/apiService.js` 中添加API方法
2. 在需要的地方调用API方法

### 样式编写

- 使用CSS模块或原生CSS
- 遵循现有命名约定（BEM风格）
- 添加响应式设计支持

### 状态更新

- 通过 `useApp()` hook访问全局状态
- 在 `AppContext.jsx` 中添加新的状态和操作方法

## 与后端集成

### 环境配置

确保后端服务在 `http://127.0.0.1:8001` 运行，并在 `.env` 文件中配置DeepSeek API密钥等。

### API响应格式

前端期望后端API返回以下格式的响应：

```json
{
  "success": true,
  "data": {...},
  "error": null
}
```

对于聊天接口，还需要支持工具调用和确认信息。

### 错误处理

- 网络错误：显示友好的错误消息
- API错误：根据HTTP状态码显示相应错误
- 验证错误：显示字段级错误信息

## 部署

### 构建部署

1. 运行 `npm run build` 生成生产构建
2. 将 `dist/` 目录的内容部署到Web服务器
3. 配置Web服务器代理到后端API

### 容器化部署（可选）

创建Dockerfile进行容器化部署：

```dockerfile
FROM node:18-alpine as build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

## 贡献指南

1. Fork项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建Pull Request

## 许可证

MIT License