import React, { createContext, useContext, useState, useCallback } from 'react'
import apiService from '../services/apiService'

const AppContext = createContext()

export const useApp = () => {
  const context = useContext(AppContext)
  if (!context) {
    throw new Error('useApp must be used within AppProvider')
  }
  return context
}

export const AppProvider = ({ children }) => {
  // 会话状态
  const [sessions, setSessions] = useState([])
  const [currentSessionId, setCurrentSessionId] = useState(null)
  const [isLoadingSessions, setIsLoadingSessions] = useState(false)

  // 表和数据状态
  const [tables, setTables] = useState([])
  const [currentTable, setCurrentTable] = useState(null)
  const [tableData, setTableData] = useState(null)
  const [isLoadingTables, setIsLoadingTables] = useState(false)
  const [isLoadingData, setIsLoadingData] = useState(false)

  // 聊天状态
  const [messages, setMessages] = useState([])
  const [isLoadingChat, setIsLoadingChat] = useState(false)

  // 确认状态
  const [pendingConfirmation, setPendingConfirmation] = useState(null)
  const [isProcessingConfirmation, setIsProcessingConfirmation] = useState(false)

  // 设置状态
  const [autoExecuteEnabled, setAutoExecuteEnabled] = useState(false)
  const [autoExecuteThreshold, setAutoExecuteThreshold] = useState(0.8)
  const [autoExecuteAllowedOperations, setAutoExecuteAllowedOperations] = useState([
    'query_data',
    'get_schema',
    'list_tables',
  ])
  const [autoExecuteExcludeTables, setAutoExecuteExcludeTables] = useState([
    '_app_config',
    '_table_metadata',
  ])
  const [llmProvider, setLlmProvider] = useState('deepseek')
  const [temperature, setTemperature] = useState(0.0)

  // 配置状态
  const [config, setConfig] = useState({})

  const currentSession = sessions.find((s) => s.id === currentSessionId) || sessions[0]

  // 加载会话
  const loadSessions = useCallback(async () => {
    setIsLoadingSessions(true)
    try {
      // TODO: 从API加载会话
      const mockSessions = [
        {
          id: 'default',
          name: '默认会话',
          messages: [],
          created_at: new Date().toISOString(),
        },
      ]
      setSessions(mockSessions)
      if (!currentSessionId) {
        setCurrentSessionId('default')
      }
    } catch (error) {
      console.error('加载会话失败:', error)
    } finally {
      setIsLoadingSessions(false)
    }
  }, [currentSessionId])

  // 加载表
  const loadTables = useCallback(async () => {
    setIsLoadingTables(true)
    try {
      const result = await apiService.getTables()
      if (result.success) {
        setTables(result.tables)
      }
    } catch (error) {
      console.error('加载表失败:', error)
    } finally {
      setIsLoadingTables(false)
    }
  }, [])

  // 加载表数据
  const loadTableData = useCallback(async (tableName, limit = 50) => {
    setIsLoadingData(true)
    try {
      const result = await apiService.getTableData(tableName, limit)
      if (result.success) {
        setTableData(result)
      }
    } catch (error) {
      console.error('加载表数据失败:', error)
    } finally {
      setIsLoadingData(false)
    }
  }, [])

  // 发送消息
  const sendMessage = useCallback(async (message) => {
    if (!currentSessionId) return

    setIsLoadingChat(true)

    // 添加用户消息
    const userMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
    }

    setMessages((prev) => [...prev, userMessage])

    try {
      const response = await apiService.sendChatMessage(
        currentSessionId,
        message,
        autoExecuteEnabled
      )

      if (response.success) {
        // 添加助手消息
        const assistantMessage = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: response.response_text,
          timestamp: new Date().toISOString(),
          tool_calls: response.tool_calls,
          confirmation: response.needs_confirmation
            ? {
                id: response.confirmation_id,
                message: response.confirmation_message,
              }
            : undefined,
          execution_result: response.execution_result,
        }

        setMessages((prev) => [...prev, assistantMessage])

        // 如果需要确认，设置待确认状态
        if (response.needs_confirmation) {
          setPendingConfirmation({
            id: response.confirmation_id,
            toolCall: response.tool_calls?.[0],
            message: response.confirmation_message,
            sessionId: currentSessionId,
            requiresConfirmation: true,
            confidence: response.confidence,
          })
        }
      } else {
        // 添加错误消息
        const errorMessage = {
          id: (Date.now() + 1).toString(),
          role: 'system',
          content: '处理消息时发生错误',
          error: response.error,
          timestamp: new Date().toISOString(),
        }

        setMessages((prev) => [...prev, errorMessage])
      }
    } catch (error) {
      console.error('发送消息失败:', error)

      const errorMessage = {
        id: (Date.now() + 1).toString(),
        role: 'system',
        content: '发送消息失败',
        error: error.message,
        timestamp: new Date().toISOString(),
      }

      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoadingChat(false)
    }
  }, [currentSessionId, autoExecuteEnabled])

  // 批准确认
  const approveConfirmation = useCallback(async (confirmationId, notes = '') => {
    if (!currentSessionId || !confirmationId) return

    setIsProcessingConfirmation(true)
    try {
      const response = await apiService.confirmAction(
        currentSessionId,
        confirmationId,
        'approve',
        notes
      )

      if (response.success) {
        // 更新消息状态
        setMessages((prev) =>
          prev.map((msg) => {
            if (msg.confirmation?.id === confirmationId) {
              return {
                ...msg,
                execution_result: response.execution_result,
                confirmation: undefined,
              }
            }
            return msg
          })
        )
      }

      setPendingConfirmation(null)
    } catch (error) {
      console.error('批准确认失败:', error)
    } finally {
      setIsProcessingConfirmation(false)
    }
  }, [currentSessionId])

  // 拒绝确认
  const rejectConfirmation = useCallback(async (confirmationId, notes = '') => {
    if (!currentSessionId || !confirmationId) return

    setIsProcessingConfirmation(true)
    try {
      const response = await apiService.confirmAction(
        currentSessionId,
        confirmationId,
        'reject',
        notes
      )

      if (response.success) {
        // 更新消息状态
        setMessages((prev) =>
          prev.map((msg) => {
            if (msg.confirmation?.id === confirmationId) {
              return {
                ...msg,
                execution_result: response.execution_result,
                confirmation: undefined,
              }
            }
            return msg
          })
        )
      }

      setPendingConfirmation(null)
    } catch (error) {
      console.error('拒绝确认失败:', error)
    } finally {
      setIsProcessingConfirmation(false)
    }
  }, [currentSessionId])

  // 关闭确认弹窗
  const closeConfirmation = useCallback(() => {
    setPendingConfirmation(null)
  }, [])

  // 更新配置
  const updateConfig = useCallback(async (key, value) => {
    try {
      await apiService.updateConfig(key, value)
      // 重新加载配置
      const configResult = await apiService.getConfig()
      if (configResult) {
        setConfig(configResult)
      }
    } catch (error) {
      console.error('更新配置失败:', error)
    }
  }, [])

  // 加载配置
  const loadConfig = useCallback(async () => {
    try {
      const configResult = await apiService.getConfig()
      if (configResult) {
        setConfig(configResult)

        // 更新本地设置
        if (configResult.auto_execute_enabled !== undefined) {
          setAutoExecuteEnabled(configResult.auto_execute_enabled)
        }
        if (configResult.auto_execute_threshold !== undefined) {
          setAutoExecuteThreshold(configResult.auto_execute_threshold)
        }
        if (configResult.auto_execute_allowed_operations) {
          setAutoExecuteAllowedOperations(configResult.auto_execute_allowed_operations)
        }
        if (configResult.auto_execute_exclude_tables) {
          setAutoExecuteExcludeTables(configResult.auto_execute_exclude_tables)
        }
        if (configResult.default_llm_provider) {
          setLlmProvider(configResult.default_llm_provider)
        }
        if (configResult.temperature !== undefined) {
          setTemperature(configResult.temperature)
        }
      }
    } catch (error) {
      console.error('加载配置失败:', error)
    }
  }, [])

  // 初始化
  React.useEffect(() => {
    loadSessions()
    loadTables()
    loadConfig()
  }, [loadSessions, loadTables, loadConfig])

  const value = {
    // 会话
    sessions,
    currentSession,
    currentSessionId,
    setCurrentSessionId,
    isLoadingSessions,
    loadSessions,

    // 表和数据
    tables,
    currentTable,
    setCurrentTable,
    tableData,
    isLoadingTables,
    isLoadingData,
    loadTables,
    loadTableData,

    // 聊天
    messages,
    isLoadingChat,
    sendMessage,

    // 确认
    pendingConfirmation,
    isProcessingConfirmation,
    approveConfirmation,
    rejectConfirmation,
    closeConfirmation,

    // 设置
    autoExecuteEnabled,
    setAutoExecuteEnabled,
    autoExecuteThreshold,
    setAutoExecuteThreshold,
    autoExecuteAllowedOperations,
    setAutoExecuteAllowedOperations,
    autoExecuteExcludeTables,
    setAutoExecuteExcludeTables,
    llmProvider,
    setLlmProvider,
    temperature,
    setTemperature,

    // 配置
    config,
    updateConfig,
    loadConfig,
  }

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}