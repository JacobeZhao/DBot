import { useState, useRef, useEffect } from 'react'
import MessageList from './MessageList'
import MessageInput from './MessageInput'
import { useApp } from '../context/AppContext'
import '../styles/ChatInterface.css'

const ChatInterface = () => {
  const { messages, sendMessage } = useApp()
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

  const isEmpty = !messages || messages.length === 0

  return (
    <div className="chat-interface">
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
