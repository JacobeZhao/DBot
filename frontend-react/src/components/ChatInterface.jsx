import React, { useState, useRef, useEffect } from 'react'
import MessageList from './MessageList'
import MessageInput from './MessageInput'
import { useApp } from '../context/AppContext'
import '../styles/ChatInterface.css'

const ChatInterface = () => {
  const { currentSession, sendMessage } = useApp()
  const [inputMessage, setInputMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [currentSession?.messages])

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

  if (!currentSession) {
    return (
      <div className="chat-interface no-session">
        <div className="no-session-message">
          <p>请从左侧选择或创建会话</p>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-interface">
      <div className="chat-header">
        <h2>{currentSession.name}</h2>
        <div className="session-info">
          <span className="session-id">ID: {currentSession.id}</span>
          <span className="message-count">
            消息数: {currentSession.messages?.length || 0}
          </span>
        </div>
      </div>

      <div className="messages-container">
        <MessageList messages={currentSession.messages || []} />
        <div ref={messagesEndRef} />
      </div>

      <div className="input-area">
        <MessageInput
          value={inputMessage}
          onChange={setInputMessage}
          onSend={handleSendMessage}
          onKeyPress={handleKeyPress}
          isLoading={isLoading}
        />
        <div className="input-hint">
          <span>按 Enter 发送，Shift + Enter 换行</span>
        </div>
      </div>
    </div>
  )
}

export default ChatInterface