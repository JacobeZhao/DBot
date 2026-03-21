import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import '../styles/MessageItem.css'

const MessageItem = ({ message }) => {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'

  const getRoleClass = () => {
    if (isUser) return 'msg-user'
    if (isSystem) return 'msg-system'
    return 'msg-assistant'
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
        <span className="msg-time">
          {message.timestamp
            ? new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            : ''}
        </span>
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
