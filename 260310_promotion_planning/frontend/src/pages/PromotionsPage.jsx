import { useCallback, useEffect, useState } from "react";
import { fetchPromotions, fetchFilterOptions } from "../api/apiClient";
import PromotionFilters from "../components/PromotionFilters";
import PromotionDetailModal from "../components/PromotionDetailModal";

const LIMIT = 30;

function PromotionsPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState({
    market: "",
    retailer: "",
    segment: "",
    category: "",
    brand: "",
    offer_type: "",
    search: "",
  });
  const [filterOptions, setFilterOptions] = useState(null);
  const [selectedId, setSelectedId] = useState(null);

  const loadPromotions = useCallback(() => {
    setLoading(true);
    fetchPromotions({
      limit: LIMIT,
      offset,
      ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v != null && v !== "")),
    })
      .then((res) => {
        setItems(res.items);
        setTotal(res.total);
      })
      .catch(() => {
        setItems([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [offset, filters]);

  useEffect(() => {
    loadPromotions();
  }, [loadPromotions]);

  useEffect(() => {
    fetchFilterOptions().then(setFilterOptions).catch(() => setFilterOptions({}));
  }, []);

  const handleFilterChange = (newFilters) => {
    setFilters(newFilters);
    setOffset(0);
  };

  const page = Math.floor(offset / LIMIT) + 1;
  const totalPages = Math.ceil(total / LIMIT) || 1;

  return (
    <section className="page-section">
      <h2 className="page-title">
        🏷️ Promotions
        <span className="badge">Page {page} of {totalPages} ({total} total)</span>
      </h2>

      <PromotionFilters filters={filters} filterOptions={filterOptions} onFilterChange={handleFilterChange} />

      {loading ? (
        <div className="loading">
          <div className="spinner" />
          <p>Loading promotions…</p>
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>No promotions found.</p>
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Market</th>
                <th>Retailer</th>
                <th>Brand</th>
                <th>Category</th>
                <th>Offer</th>
                <th>Discount</th>
                <th>Revenue</th>
                <th>Uplift</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.promo_event_id} onClick={() => setSelectedId(p.promo_event_id)} className="clickable">
                  <td><code>{p.promo_event_id}</code></td>
                  <td>{p.market}</td>
                  <td>{p.retailer}</td>
                  <td>{p.brand}</td>
                  <td>{p.category}</td>
                  <td>{p.offer_type}</td>
                  <td>{p.discount_depth != null ? `${(p.discount_depth * 100).toFixed(0)}%` : "—"}</td>
                  <td>{p.revenue != null ? `$${Number(p.revenue).toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}</td>
                  <td>{p.promo_uplift_pct != null ? `${(p.promo_uplift_pct * 100).toFixed(1)}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="pagination">
        <button onClick={() => setOffset((prev) => Math.max(0, prev - LIMIT))} disabled={offset === 0}>
          ← Previous
        </button>
        <span className="page-info">Page {page} of {totalPages}</span>
        <button onClick={() => setOffset((prev) => prev + LIMIT)} disabled={offset + LIMIT >= total}>
          Next →
        </button>
      </div>

      {selectedId && (
        <PromotionDetailModal promoId={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </section>
  );
}

export default PromotionsPage;
