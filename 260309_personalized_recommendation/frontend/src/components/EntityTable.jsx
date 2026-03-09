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
        {sortedRows.map((row, index) => (
          <tr key={index}>
            {columns.map((column) => (
              <td key={`${index}-${column}`}>
                {column === "image_url" && row[column] ? (
                  <img
                    className="article-image"
                    src={`http://127.0.0.1:8000${row[column]}`}
                    alt={row.prod_name || row.article_id}
                    onError={(event) => {
                      event.currentTarget.style.display = "none";
                    }}
                  />
                ) : (
                  String(row[column] ?? "")
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default EntityTable;
