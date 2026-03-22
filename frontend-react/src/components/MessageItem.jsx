import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useApp } from '../context/AppContext'
import '../styles/MessageItem.css'

const MessageItem = ({ message, isLast }) => {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'
  const { showToast } = useApp()

  const getRoleClass = () => {
    if (isUser) return 'msg-user'
    if (isSystem) return 'msg-system'
    return 'msg-assistant'
  }

  const handleCopy = async (e) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(message.content || '')
      showToast('已复制到剪贴板', 'success')
    } catch {
      showToast('复制失败', 'error')
    }
  }

  return (
    <div className={`msg-row ${getRoleClass()}`}>
      {!isUser && !isSystem && (
        <div className="msg-avatar assistant-avatar">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
      )}
      <div className="msg-bubble">
        <div className="msg-text">
          {isUser ? (
            message.content
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content || ''}
            </ReactMarkdown>
          )}
        </div>
        <div className="msg-footer">
          <span className="msg-time">
            {message.timestamp
              ? new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
              : ''}
          </span>
          <div className="msg-actions">
            <button className="msg-action-btn" onClick={handleCopy} title="复制">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
            </button>
          </div>
        </div>
      </div>
      {message.error && (
        <div className="msg-error">
          <span>{message.error}</span>
        </div>
      )}
    </div>
  )
}

export default MessageItem
