import { useMemo, useState } from "react";
import { API_SERVER_URL } from "../api/apiClient";

function EntityTable({ rows }) {
  const [sortConfig, setSortConfig] = useState({ key: null, direction: "asc" });
  const [hiddenImages, setHiddenImages] = useState({});
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

  if (!rows.length) return <p>No rows found.</p>;

  return (
    <table>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column} onClick={() => onSort(column)}>
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sortedRows.map((row, index) => {
          const rowKey = row.id ?? row.article_id ?? row.customer_id ?? `${index}-${JSON.stringify(row)}`;
          return (
          <tr key={rowKey}>
            {columns.map((column) => (
              <td key={`${rowKey}-${column}`}>
                {column === "image_url" && row[column] && !hiddenImages[rowKey] ? (
                  <img
                    className="article-image"
                    src={`${API_SERVER_URL}${row[column]}`}
                    alt={row.prod_name || row.article_id}
                    onError={(event) => {
                      setHiddenImages((prev) => ({ ...prev, [rowKey]: true }));
                    }}
                  />
                ) : (
                  String(row[column] ?? "")
                )}
              </td>
            ))}
          </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default EntityTable;
