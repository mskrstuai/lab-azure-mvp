import { useEffect, useMemo, useState } from "react";

/** Hook that memoises a sliced page of ``items`` given a page size. */
export function usePagination(items, defaultPageSize = 20) {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(defaultPageSize);
  const total = items?.length || 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  // Snap back to the last page if rows shrink beneath the current cursor.
  useEffect(() => {
    if (page > pageCount - 1) setPage(Math.max(0, pageCount - 1));
  }, [page, pageCount]);

  const pageItems = useMemo(() => {
    if (!items) return [];
    const start = page * pageSize;
    return items.slice(start, start + pageSize);
  }, [items, page, pageSize]);

  return {
    page,
    pageSize,
    pageCount,
    total,
    pageItems,
    setPage,
    setPageSize,
    start: page * pageSize,
  };
}

/**
 * Lightweight pagination bar — renders nothing when ``total`` fits in a
 * single page so small result sets stay uncluttered.
 */
function Pagination({
  page,
  pageCount,
  total,
  pageSize,
  start,
  setPage,
  setPageSize,
  pageSizeOptions = [10, 20, 50, 100],
}) {
  if (!total || pageCount <= 1) return null;
  const shownFrom = total === 0 ? 0 : start + 1;
  const shownTo = Math.min(start + pageSize, total);

  return (
    <div className="pagination" role="navigation" aria-label="Pagination">
      <button
        type="button"
        onClick={() => setPage(Math.max(0, page - 1))}
        disabled={page === 0}
      >
        ← Prev
      </button>
      <span className="page-info">
        {shownFrom}–{shownTo} of {total}
      </span>
      <button
        type="button"
        onClick={() => setPage(Math.min(pageCount - 1, page + 1))}
        disabled={page >= pageCount - 1}
      >
        Next →
      </button>
      {setPageSize && pageSizeOptions?.length > 0 && (
        <label
          style={{
            fontSize: "0.82rem",
            color: "var(--color-text-light)",
            marginLeft: 8,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          Per page
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(0);
            }}
            style={{ padding: "4px 8px" }}
          >
            {pageSizeOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

export default Pagination;
