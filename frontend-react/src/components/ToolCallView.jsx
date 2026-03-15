import React from 'react'
import '../styles/ToolCallView.css'

const ToolCallView = ({ toolCall }) => {
  if (!toolCall) return null

  const getStatusIcon = (status) => {
    switch (status) {
      case 'pending':
        return '⏳'
      case 'executing':
        return '⚡'
      case 'completed':
        return '✓'
      case 'failed':
        return '✗'
      case 'cancelled':
        return '🚫'
      default:
        return '❓'
    }
  }

  const getStatusText = (status) => {
    switch (status) {
      case 'pending':
        return '等待确认'
      case 'executing':
        return '执行中'
      case 'completed':
        return '已完成'
      case 'failed':
        return '失败'
      case 'cancelled':
        return '已取消'
      default:
        return '未知状态'
    }
  }

  const getStatusClass = (status) => {
    switch (status) {
      case 'pending':
        return 'status-pending'
      case 'executing':
        return 'status-executing'
      case 'completed':
        return 'status-completed'
      case 'failed':
        return 'status-failed'
      case 'cancelled':
        return 'status-cancelled'
      default:
        return 'status-unknown'
    }
  }

  const formatArguments = (args) => {
    if (!args) return '无参数'

    try {
      return JSON.stringify(args, null, 2)
    } catch {
      return String(args)
    }
  }

  const formatResult = (result) => {
    if (!result) return '无结果'

    if (typeof result === 'object') {
      try {
        return JSON.stringify(result, null, 2)
      } catch {
        return String(result)
      }
    }

    return String(result)
  }

  return (
    <div className="tool-call-view">
      <div className="tool-call-header">
        <span className="tool-name">{toolCall.name}</span>
        <span className={`tool-status ${getStatusClass(toolCall.status)}`}>
          <span className="status-icon">{getStatusIcon(toolCall.status)}</span>
          <span className="status-text">{getStatusText(toolCall.status)}</span>
        </span>
      </div>

      <div className="tool-call-content">
        <div className="tool-section">
          <div className="section-title">参数:</div>
          <div className="section-content">
            <pre className="arguments-pre">{formatArguments(toolCall.arguments)}</pre>
          </div>
        </div>

        {toolCall.result && (
          <div className="tool-section">
            <div className="section-title">结果:</div>
            <div className="section-content">
              <pre className="result-pre">{formatResult(toolCall.result)}</pre>
            </div>
          </div>
        )}

        {toolCall.error && (
          <div className="tool-section error">
            <div className="section-title">错误:</div>
            <div className="section-content">
              <div className="error-message">{toolCall.error}</div>
            </div>
          </div>
        )}

        {toolCall.confidence && (
          <div className="tool-section">
            <div className="section-title">置信度:</div>
            <div className="section-content">
              <div className="confidence-bar">
                <div
                  className="confidence-fill"
                  style={{ width: `${toolCall.confidence * 100}%` }}
                />
                <span className="confidence-text">
                  {(toolCall.confidence * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="tool-call-footer">
        <span className="tool-id">ID: {toolCall.id?.slice(0, 8) || 'N/A'}</span>
        <span className="tool-timestamp">
          {toolCall.timestamp
            ? new Date(toolCall.timestamp).toLocaleTimeString()
            : ''}
        </span>
      </div>
    </div>
  )
}

export default ToolCallView