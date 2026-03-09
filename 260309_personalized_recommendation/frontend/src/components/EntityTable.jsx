import { useMemo, useState } from "react";

function EntityTable({ rows }) {
  const [sortConfig, setSortConfig] = useState({ key: null, direction: "asc" });
  const columns = useMemo(() => (rows.length ? Object.keys(rows[0]) : []), [rows]);

  const sortedRows = useMemo(() => {
    if (!sortConfig.key) return rows;
    return [...rows].sort((a, b) => {
      const left = a[sortConfig.key] ?? "";
      const right = b[sortConfig.key] ?? "";
      if (left === right) return 0;
      if (sortConfig.direction === "asc") return left > right ? 1 : -1;
      return left < right ? 1 : -1;
    });
  }, [rows, sortConfig]);

  const onSort = (column) => {
    setSortConfig((prev) => ({
      key: column,
      direction: prev.key === column && prev.direction === "asc" ? "desc" : "asc"
    }));
  };

  if (!rows.length) {
    return (
      <div className="empty-state">
        <div className="icon">📭</div>
        <p>No rows found.</p>
      </div>
    );
  }

  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            {columns.map((column) => {
              const isActive = sortConfig.key === column;
              const arrow = isActive ? (sortConfig.direction === "asc" ? "▲" : "▼") : "⇅";
              return (
                <th key={column} onClick={() => onSort(column)}>
                  {column}
                  <span className={`sort-icon ${isActive ? "active" : ""}`}>{arrow}</span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, index) => {
            const rowKey = row.id ?? row.article_id ?? row.customer_id ?? `row-${index}-${Object.values(row).slice(0, 3).join("-")}`;
            return (
              <tr key={rowKey}>
                {columns.map((column) => (
                  <td key={`${rowKey}-${column}`}>
                    {String(row[column] ?? "—")}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default EntityTable;
