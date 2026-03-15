import React, { useState } from 'react'
import { useApp } from '../context/AppContext'
import '../styles/ConfirmationModal.css'

const ConfirmationModal = () => {
  const {
    pendingConfirmation,
    approveConfirmation,
    rejectConfirmation,
    closeConfirmation,
    autoExecuteEnabled,
  } = useApp()

  const [notes, setNotes] = useState('')

  if (!pendingConfirmation) {
    return null
  }

  const {
    id,
    toolCall,
    message,
    sessionId,
    requiresConfirmation,
    confidence,
  } = pendingConfirmation

  const handleApprove = () => {
    approveConfirmation(id, notes)
    setNotes('')
  }

  const handleReject = () => {
    rejectConfirmation(id, notes)
    setNotes('')
  }

  const handleClose = () => {
    closeConfirmation()
    setNotes('')
  }

  const formatArguments = (args) => {
    if (!args) return '无参数'

    try {
      return JSON.stringify(args, null, 2)
    } catch {
      return String(args)
    }
  }

  const getRiskLevel = () => {
    if (!requiresConfirmation) return '低风险'
    if (toolCall?.confidence_level === 'RISKY') return '中等风险'
    if (toolCall?.confidence_level === 'DESTRUCTIVE') return '高风险'
    return '低风险'
  }

  const getRiskClass = () => {
    if (!requiresConfirmation) return 'risk-low'
    if (toolCall?.confidence_level === 'RISKY') return 'risk-medium'
    if (toolCall?.confidence_level === 'DESTRUCTIVE') return 'risk-high'
    return 'risk-low'
  }

  return (
    <div className="confirmation-modal-overlay">
      <div className="confirmation-modal">
        <div className="modal-header">
          <h2>操作确认</h2>
          <button className="close-button" onClick={handleClose}>
            ×
          </button>
        </div>

        <div className="modal-content">
          <div className="confirmation-message">
            <p>{message}</p>
          </div>

          <div className="tool-call-details">
            <div className="detail-section">
              <h3>工具调用详情</h3>
              <div className="detail-row">
                <span className="detail-label">工具名称:</span>
                <span className="detail-value">{toolCall?.name}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">风险等级:</span>
                <span className={`detail-value ${getRiskClass()}`}>
                  {getRiskLevel()}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">置信度:</span>
                <span className="detail-value">
                  {confidence ? `${(confidence * 100).toFixed(1)}%` : 'N/A'}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">会话:</span>
                <span className="detail-value">{sessionId}</span>
              </div>
            </div>

            <div className="detail-section">
              <h3>参数</h3>
              <div className="arguments-container">
                <pre className="arguments-pre">
                  {formatArguments(toolCall?.arguments)}
                </pre>
              </div>
            </div>
          </div>

          <div className="notes-section">
            <label htmlFor="confirmation-notes">备注 (可选):</label>
            <textarea
              id="confirmation-notes"
              className="notes-textarea"
              placeholder="输入备注..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
            />
          </div>

          {autoExecuteEnabled && (
            <div className="auto-execute-warning">
              <span className="warning-icon">⚠️</span>
              <span className="warning-text">
                自动执行模式已启用。如果置信度达到阈值，此操作将自动执行。
              </span>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="reject-button" onClick={handleReject}>
            拒绝
          </button>
          <button className="approve-button" onClick={handleApprove}>
            批准执行
          </button>
        </div>
      </div>
    </div>
  )
}

export default ConfirmationModal