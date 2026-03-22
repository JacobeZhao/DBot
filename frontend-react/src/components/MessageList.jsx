import React from 'react'
import MessageItem from './MessageItem'
import ToolCallView from './ToolCallView'
import '../styles/MessageList.css'

const MessageList = ({ messages }) => {
  if (!messages || messages.length === 0) {
    return (
      <div className="message-list empty">
        <div className="empty-message">
          <p>还没有消息，开始对话吧！</p>
        </div>
      </div>
    )
  }

  return (
    <div className="message-list">
      {messages.map((message, index) => (
        <div key={message.id || index} className="message-wrapper">
          <MessageItem message={message} isLast={index === messages.length - 1} />

          {/* 显示工具调用信息 */}
          {message.tool_calls && message.tool_calls.length > 0 && (
            <div className="tool-calls-section">
              {message.tool_calls.map((toolCall, toolIndex) => (
                <ToolCallView
                  key={toolCall.id || `${index}-${toolIndex}`}
                  toolCall={toolCall}
                />
              ))}
            </div>
          )}

          {/* 显示确认信息 */}
          {message.confirmation && (
            <div className="confirmation-section">
              <div className="confirmation-info">
                <span className="confirmation-label">待确认操作:</span>
                <span className="confirmation-message">
                  {message.confirmation.message}
                </span>
              </div>
            </div>
          )}

          {/* 显示执行结果 */}
          {message.execution_result && (
            <div className="execution-result-section">
              <div className="execution-result">
                <span className="result-label">执行结果:</span>
                <span className="result-message">
                  {message.execution_result.success ? '✓ 成功' : '✗ 失败'}
                  {message.execution_result.message &&
                    `: ${message.execution_result.message}`}
                </span>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default MessageList