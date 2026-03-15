import React, { useState } from 'react'
import ChatInterface from './components/ChatInterface'
import DatabasePanel from './components/DatabasePanel'
import ConfirmationModal from './components/ConfirmationModal'
import SettingsPanel from './components/SettingsPanel'
import { AppProvider } from './context/AppContext'
import './styles/App.css'

function App() {
  const [showSettings, setShowSettings] = useState(false)

  return (
    <AppProvider>
      <div className="app-container">
        <header className="app-header">
          <h1>DBot NL2CLI (新版本)</h1>
          <button
            className="settings-button"
            onClick={() => setShowSettings(!showSettings)}
          >
            ⚙️ 设置
          </button>
        </header>

        <div className="main-content">
          <div className="left-panel">
            <DatabasePanel />
          </div>
          <div className="center-panel">
            <ChatInterface />
          </div>
          <div className="right-panel">
            {/* 预留右侧面板，可用于显示详情或其他信息 */}
            <div className="info-panel">
              <h3>系统信息</h3>
              <p>基于DeepSeek函数调用的数据库自然语言交互系统</p>
              <p>版本: 2.0.0</p>
            </div>
          </div>
        </div>

        <ConfirmationModal />
        {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
      </div>
    </AppProvider>
  )
}

export default App