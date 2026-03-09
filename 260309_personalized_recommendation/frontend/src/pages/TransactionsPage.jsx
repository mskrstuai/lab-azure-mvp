import { useEffect, useState } from "react";

import { API_BASE_URL, API_SERVER_URL } from "../api/apiClient";
import { DEFAULT_PAGE_LIMIT } from "../constants";

const GROUPED_LIMIT = 100;

function MiniArticleCard({ item }) {
  const [imgError, setImgError] = useState(false);
  const article = item.article;
  const imageUrl = article?.image_url ? `${API_SERVER_URL}${article.image_url}` : null;

  return (
    <div className="txn-article-card">
      {imageUrl && !imgError ? (
        <img
          className="txn-article-img"
          src={imageUrl}
          alt={article?.prod_name || item.article_id}
          loading="lazy"
          onError={() => setImgError(true)}
        />
      ) : (
        <div className="txn-article-img-placeholder">📷</div>
      )}
      <div className="txn-article-info">
        <p className="txn-article-name">{article?.prod_name || "Unknown Article"}</p>
        <p className="txn-article-id">ID: {item.article_id}</p>
        <div className="txn-article-tags">
          {article?.product_type_name && (
            <span className="txn-tag">{article.product_type_name}</span>
          )}
          {article?.colour_group_name && (
            <span className="txn-tag colour">{article.colour_group_name}</span>
          )}
        </div>
        {item.price != null && (
          <p className="txn-article-price">💰 {item.price.toFixed(4)}</p>
        )}
      </div>
    </div>
  );
}

function TransactionsPage() {
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [customerIdFilter, setCustomerIdFilter] = useState("");
  const [appliedFilter, setAppliedFilter] = useState("");
  const limit = GROUPED_LIMIT;
  const page = Math.floor(offset / limit) + 1;

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit, offset });
    if (appliedFilter) params.append("customer_id", appliedFilter);
    fetch(`${API_BASE_URL}/transactions/grouped?${params}`)
      .then((r) => r.json())
      .then(setGroups)
      .catch(() => setGroups([]))
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
      ) : groups.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>No transactions found.</p>
        </div>
      ) : (
        <div className="txn-groups">
          {groups.map((group, idx) => (
            <div className="txn-group" key={`${group.t_dat}-${group.customer_id}-${idx}`}>
              <div className="txn-group-header">
                <span className="txn-date">📅 {group.t_dat}</span>
                <span className="txn-customer">👤 {group.customer_id}</span>
                <span className="txn-count">{group.items.length} item{group.items.length !== 1 ? "s" : ""}</span>
              </div>
              <div className="txn-articles-grid">
                {group.items.map((item, i) => (
                  <MiniArticleCard key={`${item.article_id}-${i}`} item={item} />
                ))}
              </div>
            </div>
          ))}
        </div>
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
          disabled={groups.length === 0}
        >
          Next →
        </button>
      </div>
    </section>
  );
}

export default TransactionsPage;
