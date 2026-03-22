import { useState } from 'react'
import '../styles/ToolCallView.css'

const ToolCallView = ({ toolCall }) => {
  const [expanded, setExpanded] = useState(false)

  if (!toolCall) return null

  const getStatusBadge = (status) => {
    const map = {
      pending: { label: '等待', cls: 'tc-badge-warning' },
      executing: { label: '执行中', cls: 'tc-badge-info' },
      completed: { label: '完成', cls: 'tc-badge-success' },
      failed: { label: '失败', cls: 'tc-badge-danger' },
      cancelled: { label: '取消', cls: 'tc-badge-muted' },
    }
    return map[status] || { label: status || '未知', cls: 'tc-badge-muted' }
  }

  const formatJson = (obj) => {
    if (!obj) return '无'
    try {
      return JSON.stringify(obj, null, 2)
    } catch {
      return String(obj)
    }
  }

  const getSummary = () => {
    const args = toolCall.arguments
    if (!args || typeof args !== 'object') return null
    const parts = []
    if (args.table_name) parts.push(`table: ${args.table_name}`)
    if (args.query) parts.push(args.query.length > 60 ? args.query.slice(0, 60) + '...' : args.query)
    if (args.sql) parts.push(args.sql.length > 60 ? args.sql.slice(0, 60) + '...' : args.sql)
    if (args.column_name) parts.push(`col: ${args.column_name}`)
    if (args.limit) parts.push(`limit: ${args.limit}`)
    if (parts.length === 0) {
      const keys = Object.keys(args).slice(0, 3)
      keys.forEach((k) => {
        const v = String(args[k])
        parts.push(`${k}: ${v.length > 30 ? v.slice(0, 30) + '...' : v}`)
      })
    }
    return parts.join(', ')
  }

  const badge = getStatusBadge(toolCall.status)
  const summary = getSummary()

  return (
    <div className="tc-card">
      <div className="tc-header" onClick={() => setExpanded(!expanded)}>
        <div className="tc-left">
          <svg className={`tc-chevron ${expanded ? 'open' : ''}`} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
          <span className="tc-name">{toolCall.name}</span>
          {summary && <span className="tc-summary">{summary}</span>}
        </div>
        <span className={`tc-badge ${badge.cls}`}>{badge.label}</span>
      </div>

      {expanded && (
        <div className="tc-body">
          {toolCall.arguments && (
            <div className="tc-section">
              <span className="tc-label">参数</span>
              <pre className="tc-pre">{formatJson(toolCall.arguments)}</pre>
            </div>
          )}
          {toolCall.result && (
            <div className="tc-section">
              <span className="tc-label">结果</span>
              <pre className="tc-pre">{formatJson(toolCall.result)}</pre>
            </div>
          )}
          {toolCall.error && (
            <div className="tc-section tc-error">
              <span className="tc-label">错误</span>
              <div className="tc-error-text">{toolCall.error}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default ToolCallView
