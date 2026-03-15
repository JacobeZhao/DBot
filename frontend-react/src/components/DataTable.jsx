import React, { useState } from 'react'
import '../styles/DataTable.css'

const DataTable = ({ data }) => {
  const [currentPage, setCurrentPage] = useState(1)
  const [itemsPerPage, setItemsPerPage] = useState(10)
  const [sortColumn, setSortColumn] = useState(null)
  const [sortDirection, setSortDirection] = useState('asc')

  if (!data || !data.rows || data.rows.length === 0) {
    return (
      <div className="data-table empty">
        <div className="empty-message">
          <p>没有数据</p>
        </div>
      </div>
    )
  }

  const columns = data.columns || []
  const rows = data.rows || []
  const totalRows = data.count || rows.length

  // 分页计算
  const totalPages = Math.ceil(totalRows / itemsPerPage)
  const startIndex = (currentPage - 1) * itemsPerPage
  const endIndex = Math.min(startIndex + itemsPerPage, totalRows)
  const currentRows = rows.slice(startIndex, endIndex)

  // 排序
  const sortedRows = [...currentRows]
  if (sortColumn) {
    sortedRows.sort((a, b) => {
      const aValue = a[sortColumn]
      const bValue = b[sortColumn]

      if (aValue === bValue) return 0
      if (aValue === null || aValue === undefined) return 1
      if (bValue === null || bValue === undefined) return -1

      if (typeof aValue === 'string' && typeof bValue === 'string') {
        return sortDirection === 'asc'
          ? aValue.localeCompare(bValue)
          : bValue.localeCompare(aValue)
      }

      return sortDirection === 'asc' ? aValue - bValue : bValue - aValue
    })
  }

  const handleSort = (columnName) => {
    if (sortColumn === columnName) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortColumn(columnName)
      setSortDirection('asc')
    }
  }

  const handlePageChange = (page) => {
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page)
    }
  }

  const getSortIcon = (columnName) => {
    if (sortColumn !== columnName) return '↕️'
    return sortDirection === 'asc' ? '↑' : '↓'
  }

  const formatValue = (value) => {
    if (value === null || value === undefined) {
      return <span className="null-value">NULL</span>
    }

    if (typeof value === 'boolean') {
      return value ? '✓' : '✗'
    }

    if (typeof value === 'object') {
      try {
        return JSON.stringify(value)
      } catch {
        return String(value)
      }
    }

    return String(value)
  }

  return (
    <div className="data-table">
      <div className="table-info">
        <span className="row-count">共 {totalRows} 行</span>
        <div className="pagination-controls">
          <select
            className="page-size-select"
            value={itemsPerPage}
            onChange={(e) => {
              setItemsPerPage(Number(e.target.value))
              setCurrentPage(1)
            }}
          >
            <option value={5}>每页 5 行</option>
            <option value={10}>每页 10 行</option>
            <option value={25}>每页 25 行</option>
            <option value={50}>每页 50 行</option>
          </select>

          <div className="page-navigation">
            <button
              className="page-button"
              onClick={() => handlePageChange(1)}
              disabled={currentPage === 1}
            >
              «
            </button>
            <button
              className="page-button"
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={currentPage === 1}
            >
              ‹
            </button>
            <span className="page-info">
              第 {currentPage} / {totalPages} 页
            </span>
            <button
              className="page-button"
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={currentPage === totalPages}
            >
              ›
            </button>
            <button
              className="page-button"
              onClick={() => handlePageChange(totalPages)}
              disabled={currentPage === totalPages}
            >
              »
            </button>
          </div>
        </div>
      </div>

      <div className="table-container">
        <table className="data-table-content">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.name}
                  className="column-header"
                  onClick={() => handleSort(col.name)}
                >
                  <div className="header-content">
                    <span className="column-name">{col.name}</span>
                    <span className="sort-icon">{getSortIcon(col.name)}</span>
                  </div>
                  <div className="column-type">{col.type}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row, rowIndex) => (
              <tr key={rowIndex} className="data-row">
                {columns.map((col) => (
                  <td key={col.name} className="data-cell">
                    {formatValue(row[col.name])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="table-footer">
        <div className="page-info-footer">
          显示 {startIndex + 1} - {endIndex} 行，共 {totalRows} 行
        </div>
      </div>
    </div>
  )
}

export default DataTable