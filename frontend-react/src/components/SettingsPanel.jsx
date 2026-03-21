import React, { useState, useEffect } from 'react'
import { useApp } from '../context/AppContext'
import '../styles/SettingsPanel.css'

const SettingsPanel = ({ onClose }) => {
  const {
    autoExecuteEnabled,
    setAutoExecuteEnabled,
    autoExecuteThreshold,
    setAutoExecuteThreshold,
    autoExecuteAllowedOperations,
    setAutoExecuteAllowedOperations,
    autoExecuteExcludeTables,
    setAutoExecuteExcludeTables,
    llmProvider,
    setLlmProvider,
    temperature,
    setTemperature,
    config,
    updateConfig,
  } = useApp()

  const [localSettings, setLocalSettings] = useState({
    autoExecuteEnabled,
    autoExecuteThreshold,
    autoExecuteAllowedOperations,
    autoExecuteExcludeTables,
    llmProvider,
    temperature,
  })

  const [showAdvanced, setShowAdvanced] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    setLocalSettings({
      autoExecuteEnabled,
      autoExecuteThreshold,
      autoExecuteAllowedOperations,
      autoExecuteExcludeTables,
      llmProvider,
      temperature,
    })
  }, [
    autoExecuteEnabled,
    autoExecuteThreshold,
    autoExecuteAllowedOperations,
    autoExecuteExcludeTables,
    llmProvider,
    temperature,
  ])

  const handleSettingChange = (key, value) => {
    setLocalSettings((prev) => ({
      ...prev,
      [key]: value,
    }))
  }

  const handleSave = async () => {
    setIsSaving(true)

    try {
      // 更新应用状态
      setAutoExecuteEnabled(localSettings.autoExecuteEnabled)
      setAutoExecuteThreshold(localSettings.autoExecuteThreshold)
      setAutoExecuteAllowedOperations(localSettings.autoExecuteAllowedOperations)
      setAutoExecuteExcludeTables(localSettings.autoExecuteExcludeTables)
      setLlmProvider(localSettings.llmProvider)
      setTemperature(localSettings.temperature)

      // TODO: 保存到后端
      console.log('保存设置:', localSettings)

      // 关闭面板
      onClose()
    } catch (error) {
      console.error('保存设置失败:', error)
    } finally {
      setIsSaving(false)
    }
  }

  const handleReset = () => {
    setLocalSettings({
      autoExecuteEnabled: false,
      autoExecuteThreshold: 0.8,
      autoExecuteAllowedOperations: ['query_data', 'get_schema', 'list_tables'],
      autoExecuteExcludeTables: ['_app_config', '_table_metadata'],
      llmProvider: 'claude-4.6-sonnet',
      temperature: 0.0,
    })
  }

  const handleCancel = () => {
    onClose()
  }

  const toggleAllowedOperation = (operation) => {
    const current = localSettings.autoExecuteAllowedOperations || []
    const updated = current.includes(operation)
      ? current.filter((op) => op !== operation)
      : [...current, operation]

    handleSettingChange('autoExecuteAllowedOperations', updated)
  }

  const addExcludeTable = () => {
    const tableName = prompt('输入要排除的表名:')
    if (tableName && tableName.trim()) {
      const current = localSettings.autoExecuteExcludeTables || []
      if (!current.includes(tableName.trim())) {
        handleSettingChange('autoExecuteExcludeTables', [...current, tableName.trim()])
      }
    }
  }

  const removeExcludeTable = (tableName) => {
    const current = localSettings.autoExecuteExcludeTables || []
    handleSettingChange(
      'autoExecuteExcludeTables',
      current.filter((table) => table !== tableName)
    )
  }

  const allowedOperationsOptions = [
    { value: 'query_data', label: '查询数据' },
    { value: 'get_schema', label: '获取表结构' },
    { value: 'list_tables', label: '列出表' },
    { value: 'insert_row', label: '插入行', risky: true },
    { value: 'update_row', label: '更新行', risky: true },
    { value: 'delete_row', label: '删除行', risky: true },
    { value: 'add_column', label: '添加列', risky: true },
    { value: 'drop_column', label: '删除列', risky: true },
    { value: 'rename_column', label: '重命名列', risky: true },
    { value: 'create_table', label: '创建表', risky: true },
    { value: 'drop_table', label: '删除表', destructive: true },
  ]

  return (
    <div className="settings-panel-overlay">
      <div className="settings-panel">
        <div className="panel-header">
          <h2>设置</h2>
          <button className="close-button" onClick={handleCancel}>
            ×
          </button>
        </div>

        <div className="panel-content">
          <div className="settings-section">
            <h3>自动执行设置</h3>

            <div className="setting-item">
              <div className="setting-label">
                <label htmlFor="autoExecuteEnabled">启用自动执行</label>
                <span className="setting-description">
                  允许系统在置信度达到阈值时自动执行操作
                </span>
              </div>
              <div className="setting-control">
                <input
                  id="autoExecuteEnabled"
                  type="checkbox"
                  checked={localSettings.autoExecuteEnabled}
                  onChange={(e) =>
                    handleSettingChange('autoExecuteEnabled', e.target.checked)
                  }
                />
              </div>
            </div>

            {localSettings.autoExecuteEnabled && (
              <>
                <div className="setting-item">
                  <div className="setting-label">
                    <label htmlFor="autoExecuteThreshold">置信度阈值</label>
                    <span className="setting-description">
                      达到此阈值时自动执行操作 (0.0 - 1.0)
                    </span>
                  </div>
                  <div className="setting-control">
                    <input
                      id="autoExecuteThreshold"
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={localSettings.autoExecuteThreshold}
                      onChange={(e) =>
                        handleSettingChange(
                          'autoExecuteThreshold',
                          parseFloat(e.target.value)
                        )
                      }
                    />
                    <span className="threshold-value">
                      {(localSettings.autoExecuteThreshold * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>

                <div className="setting-item">
                  <div className="setting-label">
                    <label>允许自动执行的操作</label>
                    <span className="setting-description">
                      选择哪些操作可以自动执行
                    </span>
                  </div>
                  <div className="setting-control">
                    <div className="operations-list">
                      {allowedOperationsOptions.map((option) => {
                        const isChecked = localSettings.autoExecuteAllowedOperations?.includes(
                          option.value
                        )
                        return (
                          <div
                            key={option.value}
                            className={`operation-option ${
                              option.risky ? 'risky' : ''
                            } ${option.destructive ? 'destructive' : ''}`}
                          >
                            <label>
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={() =>
                                  toggleAllowedOperation(option.value)
                                }
                              />
                              <span className="operation-label">
                                {option.label}
                                {option.risky && <span className="risk-badge">⚠️</span>}
                                {option.destructive && (
                                  <span className="destructive-badge">🔥</span>
                                )}
                              </span>
                            </label>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>

                <div className="setting-item">
                  <div className="setting-label">
                    <label>排除的表</label>
                    <span className="setting-description">
                      这些表永远不会自动执行操作
                    </span>
                  </div>
                  <div className="setting-control">
                    <div className="exclude-tables-list">
                      {localSettings.autoExecuteExcludeTables?.map((table) => (
                        <div key={table} className="exclude-table-item">
                          <span>{table}</span>
                          <button
                            type="button"
                            className="remove-table-button"
                            onClick={() => removeExcludeTable(table)}
                          >
                            ×
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        className="add-table-button"
                        onClick={addExcludeTable}
                      >
                        + 添加表
                      </button>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>

          <div className="settings-section">
            <h3>LLM 设置</h3>

            <div className="setting-item">
              <div className="setting-label">
                <label htmlFor="llmModel">模型</label>
                <span className="setting-description">选择使用的 AI 模型</span>
              </div>
              <div className="setting-control">
                <select
                  id="llmModel"
                  value={localSettings.llmProvider}
                  onChange={(e) =>
                    handleSettingChange('llmProvider', e.target.value)
                  }
                >
                  <option value="claude-4.6-opus">Claude 4.6 Opus</option>
                  <option value="claude-4.6-sonnet">Claude 4.6 Sonnet</option>
                  <option value="claude-4.5-haiku">Claude 4.5 Haiku</option>
                </select>
              </div>
            </div>

            <div className="setting-item">
              <div className="setting-label">
                <label htmlFor="temperature">温度 (Temperature)</label>
                <span className="setting-description">
                  控制生成文本的随机性 (0.0 - 1.0)
                </span>
              </div>
              <div className="setting-control">
                <input
                  id="temperature"
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={localSettings.temperature}
                  onChange={(e) =>
                    handleSettingChange('temperature', parseFloat(e.target.value))
                  }
                />
                <span className="temperature-value">
                  {localSettings.temperature.toFixed(1)}
                </span>
              </div>
            </div>
          </div>

          <div className="settings-section">
            <div className="section-header">
              <h3>高级设置</h3>
              <button
                type="button"
                className="toggle-advanced-button"
                onClick={() => setShowAdvanced(!showAdvanced)}
              >
                {showAdvanced ? '隐藏' : '显示'}
              </button>
            </div>

            {showAdvanced && (
              <div className="advanced-settings">
                <div className="setting-item">
                  <div className="setting-label">
                    <label>当前配置</label>
                    <span className="setting-description">
                      从后端获取的配置信息
                    </span>
                  </div>
                  <div className="setting-control">
                    <pre className="config-pre">
                      {JSON.stringify(config, null, 2)}
                    </pre>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="panel-footer">
          <button
            type="button"
            className="reset-button"
            onClick={handleReset}
            disabled={isSaving}
          >
            重置为默认值
          </button>
          <div className="footer-actions">
            <button
              type="button"
              className="cancel-button"
              onClick={handleCancel}
              disabled={isSaving}
            >
              取消
            </button>
            <button
              type="button"
              className="save-button"
              onClick={handleSave}
              disabled={isSaving}
            >
              {isSaving ? '保存中...' : '保存设置'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SettingsPanel