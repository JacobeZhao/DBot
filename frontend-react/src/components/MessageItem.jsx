import React from 'react'
import '../styles/MessageItem.css'

const MessageItem = ({ message }) => {
  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'
  const isSystem = message.role === 'system'

  const getRoleLabel = () => {
    if (isUser) return '用户'
    if (isAssistant) return '助手'
    if (isSystem) return '系统'
    return '未知'
  }

  const getRoleClass = () => {
    if (isUser) return 'user-message'
    if (isAssistant) return 'assistant-message'
    if (isSystem) return 'system-message'
    return ''
  }

  const formatContent = (content) => {
    if (!content) return ''

    // 简单换行处理
    return content.split('\n').map((line, index) => (
      <React.Fragment key={index}>
        {line}
        {index < content.split('\n').length - 1 && <br />}
      </React.Fragment>
    ))
  }

  return (
    <div className={`message-item ${getRoleClass()}`}>
      <div className="message-header">
        <span className="message-role">{getRoleLabel()}</span>
        <span className="message-time">
          {message.timestamp
            ? new Date(message.timestamp).toLocaleTimeString()
            : '刚刚'}
        </span>
      </div>
      <div className="message-content">
        {formatContent(message.content)}
      </div>
      {message.error && (
        <div className="message-error">
          <span className="error-icon">⚠️</span>
          <span className="error-text">{message.error}</span>
        </div>
      )}
    </div>
  )
}

export default MessageItem