import { useRef } from 'react'
import '../styles/MessageInput.css'

const MessageInput = ({ value, onChange, onSend, onKeyPress, isLoading }) => {
  const textareaRef = useRef(null)

  const handleChange = (e) => {
    onChange(e.target.value)
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`
    }
  }

  return (
    <div className="msg-input-wrap">
      <textarea
        ref={textareaRef}
        className="msg-textarea"
        placeholder="输入你的问题或数据库指令..."
        value={value}
        onChange={handleChange}
        onKeyDown={onKeyPress}
        rows={1}
        disabled={isLoading}
      />
      <button
        className="msg-send-btn"
        onClick={onSend}
        disabled={isLoading || !value.trim()}
        title="发送"
      >
        {isLoading ? (
          <span className="send-spinner" />
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        )}
      </button>
    </div>
  )
}

export default MessageInput
