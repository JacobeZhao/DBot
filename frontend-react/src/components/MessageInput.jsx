import React from 'react'
import '../styles/MessageInput.css'

const MessageInput = ({
  value,
  onChange,
  onSend,
  onKeyPress,
  isLoading,
}) => {
  const textareaRef = React.useRef(null)

  const handleChange = (e) => {
    onChange(e.target.value)

    // 自动调整高度
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = `${textarea.scrollHeight}px`
    }
  }

  const handleSendClick = () => {
    onSend()
  }

  const handleKeyDown = (e) => {
    if (onKeyPress) {
      onKeyPress(e)
    }
  }

  return (
    <div className="message-input-container">
      <div className="input-wrapper">
        <textarea
          ref={textareaRef}
          className="message-textarea"
          placeholder="输入消息...（支持自然语言操作数据库）"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={isLoading}
        />
        <button
          className="send-button"
          onClick={handleSendClick}
          disabled={isLoading || !value.trim()}
        >
          {isLoading ? (
            <span className="loading-spinner"></span>
          ) : (
            '发送'
          )}
        </button>
      </div>
      <div className="input-features">
        <div className="feature-hints">
          <span className="hint-item">🔍 查询数据</span>
          <span className="hint-item">📝 插入/更新数据</span>
          <span className="hint-item">🗃️ 管理表格</span>
        </div>
      </div>
    </div>
  )
}

export default MessageInput