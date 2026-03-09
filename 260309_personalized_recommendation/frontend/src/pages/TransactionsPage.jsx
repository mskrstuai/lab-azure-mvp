import { useEffect, useState } from "react";

import { fetchEntities } from "../api/apiClient";
import EntityTable from "../components/EntityTable";
import { DEFAULT_PAGE_LIMIT } from "../constants";

function TransactionsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const limit = DEFAULT_PAGE_LIMIT;
  const page = Math.floor(offset / limit) + 1;

  useEffect(() => {
    setLoading(true);
    fetchEntities("transactions", limit, offset)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [offset]);

  return (
    <section className="page-section">
      <h2 className="page-title">
        📋 Transactions
        <span className="badge">Page {page}</span>
      </h2>

      {loading ? (
        <div className="loading">
          <div className="spinner" />
          <p>Loading transactions…</p>
        </div>
      ) : (
        <EntityTable rows={rows} />
      )}

      <div className="pagination">
        <button
          onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
          disabled={offset === 0}
        >
          ← Previous
        </button>
        <span className="page-info">Page {page}</span>
        <button
          onClick={() => setOffset((prev) => prev + limit)}
          disabled={rows.length < limit}
        >
          Next →
        </button>
      </div>
    </section>
  );
}

export default TransactionsPage;
