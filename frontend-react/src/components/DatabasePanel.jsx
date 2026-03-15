import React, { useState, useEffect } from 'react'
import { useApp } from '../context/AppContext'
import DataTable from './DataTable'
import '../styles/DatabasePanel.css'

const DatabasePanel = () => {
  const {
    tables,
    currentTable,
    setCurrentTable,
    loadTables,
    loadTableData,
    tableData,
    isLoadingTables,
    isLoadingData,
  } = useApp()

  const [searchQuery, setSearchQuery] = useState('')
  const [showSystemTables, setShowSystemTables] = useState(false)

  useEffect(() => {
    loadTables()
  }, [])

  useEffect(() => {
    if (currentTable) {
      loadTableData(currentTable)
    }
  }, [currentTable])

  const filteredTables = tables.filter((table) => {
    if (!showSystemTables && table.name.startsWith('_')) {
      return false
    }

    if (!searchQuery.trim()) {
      return true
    }

    const query = searchQuery.toLowerCase()
    return (
      table.name.toLowerCase().includes(query) ||
      (table.description && table.description.toLowerCase().includes(query)) ||
      (table.aliases && table.aliases.some((alias) =>
        alias.toLowerCase().includes(query)
      ))
    )
  })

  const handleTableSelect = (tableName) => {
    setCurrentTable(tableName)
  }

  const handleRefresh = () => {
    loadTables()
    if (currentTable) {
      loadTableData(currentTable)
    }
  }

  const handleCreateTable = () => {
    // TODO: 实现创建表功能
    console.log('创建新表')
  }

  return (
    <div className="database-panel">
      <div className="panel-header">
        <h2>数据库</h2>
        <div className="header-actions">
          <button
            className="refresh-button"
            onClick={handleRefresh}
            disabled={isLoadingTables}
          >
            {isLoadingTables ? '刷新中...' : '🔄'}
          </button>
          <button className="create-button" onClick={handleCreateTable}>
            + 新建表
          </button>
        </div>
      </div>

      <div className="panel-search">
        <input
          type="text"
          className="search-input"
          placeholder="搜索表..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <label className="system-tables-toggle">
          <input
            type="checkbox"
            checked={showSystemTables}
            onChange={(e) => setShowSystemTables(e.target.checked)}
          />
          显示系统表
        </label>
      </div>

      <div className="tables-list">
        {isLoadingTables ? (
          <div className="loading-tables">
            <div className="loading-spinner"></div>
            <span>加载表中...</span>
          </div>
        ) : filteredTables.length === 0 ? (
          <div className="no-tables">
            <p>没有找到表</p>
          </div>
        ) : (
          <ul className="table-items">
            {filteredTables.map((table) => (
              <li
                key={table.name}
                className={`table-item ${
                  currentTable === table.name ? 'active' : ''
                }`}
                onClick={() => handleTableSelect(table.name)}
              >
                <div className="table-info">
                  <div className="table-name">
                    {table.name}
                    {table.name.startsWith('_') && (
                      <span className="system-badge">系统</span>
                    )}
                  </div>
                  <div className="table-description">{table.description}</div>
                  <div className="table-meta">
                    <span className="column-count">
                      {table.column_count} 列
                    </span>
                    {table.aliases && table.aliases.length > 0 && (
                      <span className="aliases">
                        别名: {table.aliases.join(', ')}
                      </span>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="data-preview">
        <div className="preview-header">
          <h3>
            {currentTable ? `${currentTable} 数据` : '选择表查看数据'}
          </h3>
          {currentTable && (
            <button
              className="refresh-data-button"
              onClick={() => loadTableData(currentTable)}
              disabled={isLoadingData}
            >
              {isLoadingData ? '加载中...' : '刷新数据'}
            </button>
          )}
        </div>

        {currentTable ? (
          isLoadingData ? (
            <div className="loading-data">
              <div className="loading-spinner"></div>
              <span>加载数据中...</span>
            </div>
          ) : (
            <DataTable data={tableData} />
          )
        ) : (
          <div className="no-table-selected">
            <p>请从左侧列表选择一个表查看数据</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default DatabasePanel