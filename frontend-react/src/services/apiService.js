import axios from 'axios'

// 创建axios实例
const api = axios.create({
  baseURL: '/api', // 通过Vite代理到后端
  timeout: 30000, // 30秒超时
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    // 可以在这里添加认证token等
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('API请求失败:', error)

    if (error.response) {
      // 服务器返回错误
      const { status, data } = error.response
      const errorMessage = data?.error || data?.message || `请求失败: ${status}`

      return {
        success: false,
        error: errorMessage,
        status_code: status,
      }
    } else if (error.request) {
      // 请求已发出但没有响应
      return {
        success: false,
        error: '网络错误，请检查网络连接',
      }
    } else {
      // 请求配置错误
      return {
        success: false,
        error: error.message,
      }
    }
  }
)

const apiService = {
  // 健康检查
  async healthCheck() {
    try {
      const response = await axios.get('http://127.0.0.1:8001/health')
      return response.data
    } catch (error) {
      console.error('健康检查失败:', error)
      throw error
    }
  },

  // 获取配置
  async getConfig() {
    return api.get('/config')
  },

  // 更新配置
  async updateConfig(key, value, description = '') {
    return api.put('/config', { key, value, description })
  },

  // 测试配置
  async testConfig(config) {
    return api.post('/config/test', config)
  },

  // 获取表列表
  async getTables() {
    return api.get('/tables')
  },

  // 获取表数据
  async getTableData(tableName, limit = 100) {
    return api.get(`/tables/${tableName}?limit=${limit}`)
  },

  // 创建表
  async createTable(tableData) {
    return api.post('/tables', tableData)
  },

  // 删除表
  async deleteTable(tableName) {
    return api.delete(`/tables/${tableName}`)
  },

  // 发送聊天消息
  async sendChatMessage(sessionId, message, autoExecute = false) {
    return api.post('/chat', {
      session_id: sessionId,
      message,
      auto_execute: autoExecute,
      stream: false,
    })
  },

  // 流式发送聊天消息
  async sendChatMessageStream(sessionId, message, autoExecute = false, onChunk) {
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          auto_execute: autoExecute,
          stream: true,
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data.trim()) {
              try {
                const parsed = JSON.parse(data)
                if (onChunk) onChunk(parsed)
              } catch (e) {
                console.error('解析SSE数据失败:', e)
              }
            }
          }
        }
      }
    } catch (error) {
      console.error('流式聊天失败:', error)
      throw error
    }
  },

  // 确认操作
  async confirmAction(sessionId, confirmationId, action, notes = '') {
    return api.post('/confirm', {
      session_id: sessionId,
      confirmation_id: confirmationId,
      action, // 'approve' 或 'reject'
      notes,
    })
  },

  // 获取会话信息
  async getSessionInfo(sessionId) {
    return api.get(`/sessions/${sessionId}`)
  },

  // 更新自动执行设置
  async updateAutoExecute(sessionId, enabled) {
    return api.put(`/sessions/${sessionId}/auto-execute`, { enabled })
  },

  // 工具执行
  async executeTool(toolName, parameters) {
    return api.post('/execute-tool', {
      tool_name: toolName,
      parameters,
    })
  },
}

export default apiService