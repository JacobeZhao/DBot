import { useState, useRef, useEffect } from 'react'
import MessageList from './MessageList'
import MessageInput from './MessageInput'
import ThinkingIndicator from './ThinkingIndicator'
import { useApp } from '../context/AppContext'
import '../styles/ChatInterface.css'

const ChatInterface = () => {
  const { messages, sendMessage, clearMessages, showToast } = useApp()
  const [inputMessage, setInputMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || isLoading) return

    const message = inputMessage.trim()
    setInputMessage('')
    setIsLoading(true)

    try {
      await sendMessage(message)
    } catch (error) {
      console.error('发送消息失败:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  const handleQuickAction = (text) => {
    setInputMessage(text)
  }

  const handleClearChat = () => {
    if (messages.length === 0) return
    clearMessages()
    showToast('聊天记录已清空', 'info')
  }

  const isEmpty = !messages || messages.length === 0

  return (
    <div className="chat-interface">
      <div className="chat-header">
        <span className="chat-title">对话</span>
        {!isEmpty && (
          <button className="chat-clear-btn" onClick={handleClearChat} title="清空聊天">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        )}
      </div>
      <div className="messages-container">
        {isEmpty ? (
          <div className="empty-state">
            <p className="empty-hint">输入指令操作数据库</p>
            <div className="quick-actions">
              <button className="quick-action-btn" onClick={() => handleQuickAction('显示所有表')}>
                显示所有表
              </button>
              <button className="quick-action-btn" onClick={() => handleQuickAction('查询数据库中有多少条记录')}>
                查询记录数
              </button>
            </div>
          </div>
        ) : (
          <>
            <MessageList messages={messages} />
            {isLoading && <ThinkingIndicator />}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      <div className="input-area">
        <MessageInput
          value={inputMessage}
          onChange={setInputMessage}
          onSend={handleSendMessage}
          onKeyPress={handleKeyPress}
          isLoading={isLoading}
        />
      </div>
    </div>
  )
}

export default ChatInterface
