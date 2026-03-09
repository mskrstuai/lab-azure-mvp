import { useEffect, useState } from "react";

import { fetchEntities } from "../api/apiClient";
import EntityTable from "../components/EntityTable";
import { DEFAULT_PAGE_LIMIT } from "../constants";

function TransactionsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [customerIdFilter, setCustomerIdFilter] = useState("");
  const [appliedFilter, setAppliedFilter] = useState("");
  const limit = DEFAULT_PAGE_LIMIT;
  const page = Math.floor(offset / limit) + 1;

  useEffect(() => {
    setLoading(true);
    const filters = appliedFilter ? { customer_id: appliedFilter } : {};
    fetchEntities("transactions", limit, offset, filters)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [offset, appliedFilter]);

  const handleApplyFilter = () => {
    setOffset(0);
    setAppliedFilter(customerIdFilter);
  };

  const handleClearFilter = () => {
    setCustomerIdFilter("");
    setOffset(0);
    setAppliedFilter("");
  };

  return (
    <section className="page-section">
      <h2 className="page-title">
        📋 Transactions
        <span className="badge">Page {page}</span>
      </h2>

      <div className="filter-bar-inline">
        <input
          type="text"
          className="filter-input"
          placeholder="Filter by customer ID…"
          value={customerIdFilter}
          onChange={(e) => setCustomerIdFilter(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleApplyFilter()}
        />
        <button className="filter-apply-btn" onClick={handleApplyFilter}>
          Search
        </button>
        {appliedFilter && (
          <button className="filter-clear-btn" onClick={handleClearFilter}>
            Clear
          </button>
        )}
      </div>

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
