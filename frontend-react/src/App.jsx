import { useState, useRef, useEffect, useCallback } from 'react'
import ChatInterface from './components/ChatInterface'
import DataTable from './components/DataTable'
import Toast from './components/Toast'
import ConfirmationModal from './components/ConfirmationModal'
import SettingsPanel from './components/SettingsPanel'
import { AppProvider, useApp } from './context/AppContext'
import useTheme from './hooks/useTheme'
import './styles/App.css'

function AppContent() {
  const [showSettings, setShowSettings] = useState(false)
  const { theme, toggleTheme, isDark } = useTheme()
  const {
    tables,
    currentTable,
    setCurrentTable,
    loadTableData,
    tableData,
    isLoadingData,
    isLoadingTables,
    loadTables,
  } = useApp()

  // 拖拽分割线
  const [chatWidth, setChatWidth] = useState(25)
  const [isDragging, setIsDragging] = useState(false)
  const containerRef = useRef(null)

  // 选表后自动加载数据
  useEffect(() => {
    if (currentTable) {
      loadTableData(currentTable)
    }
  }, [currentTable, loadTableData])

  // 拖拽处理
  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e) => {
      const container = containerRef.current
      if (!container) return
      const rect = container.getBoundingClientRect()
      const percent = ((e.clientX - rect.left) / rect.width) * 100
      setChatWidth(Math.min(50, Math.max(15, percent)))
    }

    const handleMouseUp = () => setIsDragging(false)

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [isDragging])

  const handleRefresh = useCallback(() => {
    loadTables()
    if (currentTable) loadTableData(currentTable)
  }, [loadTables, loadTableData, currentTable])

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-brand">
          <svg className="brand-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
          <span className="brand-text">DBot</span>
        </div>

        <div className="header-center">
          <select
            className="table-selector"
            value={currentTable || ''}
            onChange={(e) => setCurrentTable(e.target.value)}
            disabled={isLoadingTables}
          >
            <option value="" disabled>
              {isLoadingTables ? '加载中...' : '选择数据表...'}
            </option>
            {tables
              .filter((t) => !t.name.startsWith('_'))
              .map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}（{t.column_count} 列）
                </option>
              ))}
          </select>
          <button
            className="header-btn refresh-btn"
            onClick={handleRefresh}
            disabled={isLoadingTables || isLoadingData}
            title="刷新"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={isLoadingTables || isLoadingData ? 'spin' : ''}>
              <polyline points="23 4 23 10 17 10" />
              <polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
          </button>
        </div>

        <div className="header-actions">
          <button
            className="header-btn theme-btn"
            onClick={toggleTheme}
            title={isDark ? '切换到亮色主题' : '切换到暗色主题'}
          >
            {isDark ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="5" />
                <line x1="12" y1="1" x2="12" y2="3" />
                <line x1="12" y1="21" x2="12" y2="23" />
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                <line x1="1" y1="12" x2="3" y2="12" />
                <line x1="21" y1="12" x2="23" y2="12" />
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            )}
          </button>
          <button
            className="header-btn settings-btn"
            onClick={() => setShowSettings(!showSettings)}
            title="设置"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
        </div>
      </header>

      <main className="app-main" ref={containerRef}>
        <section className="chat-section" style={{ width: `${chatWidth}%` }}>
          <ChatInterface />
        </section>

        <div
          className={`resize-handle ${isDragging ? 'active' : ''}`}
          onMouseDown={() => setIsDragging(true)}
        />

        <section className="data-section">
          {isLoadingData ? (
            <div className="data-loading">
              <span className="data-spinner" />
              <span>加载中...</span>
            </div>
          ) : currentTable && tableData ? (
            <DataTable data={tableData} />
          ) : (
            <div className="data-empty">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <ellipse cx="12" cy="5" rx="9" ry="3" />
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
              </svg>
              <p>从上方下拉菜单选择一个数据表</p>
            </div>
          )}
        </section>
      </main>

      <ConfirmationModal />
      <Toast />
      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </div>
  )
}

function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  )
}

export default App
