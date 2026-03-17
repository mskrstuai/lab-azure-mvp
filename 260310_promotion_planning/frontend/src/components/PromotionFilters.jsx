import { useState } from "react";

function PromotionFilters({ filters, filterOptions, onFilterChange }) {
  const [expanded, setExpanded] = useState(true);
  const activeCount = Object.values(filters).filter((v) => v != null && v !== "").length;

  const handleChange = (key, value) => {
    onFilterChange({ ...filters, [key]: value });
  };

  const handleClear = () => {
    onFilterChange({
      market: "",
      retailer: "",
      segment: "",
      category: "",
      brand: "",
      offer_type: "",
      search: "",
    });
  };

  const opts = filterOptions || {};

  return (
    <div className="filter-bar">
      <div className="filter-header">
        <button className="filter-toggle" onClick={() => setExpanded(!expanded)}>
          Filters {activeCount > 0 && <span className="filter-count">{activeCount}</span>}
          <span className="toggle-arrow">{expanded ? "▼" : "▶"}</span>
        </button>
        {activeCount > 0 && (
          <button className="filter-clear" onClick={handleClear}>
            Clear
          </button>
        )}
      </div>
      {expanded && (
        <div className="filter-grid">
          <div className="filter-field">
            <label>Search</label>
            <input
              type="text"
              placeholder="SKU, brand, description…"
              value={filters.search || ""}
              onChange={(e) => handleChange("search", e.target.value)}
            />
          </div>
          <div className="filter-field">
            <label>Market</label>
            <select value={filters.market || ""} onChange={(e) => handleChange("market", e.target.value)}>
              <option value="">All</option>
              {(opts.markets || []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <label>Retailer</label>
            <select value={filters.retailer || ""} onChange={(e) => handleChange("retailer", e.target.value)}>
              <option value="">All</option>
              {(opts.retailers || []).map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <label>Segment</label>
            <select value={filters.segment || ""} onChange={(e) => handleChange("segment", e.target.value)}>
              <option value="">All</option>
              {(opts.segments || []).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <label>Category</label>
            <select value={filters.category || ""} onChange={(e) => handleChange("category", e.target.value)}>
              <option value="">All</option>
              {(opts.categories || []).map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <label>Brand</label>
            <select value={filters.brand || ""} onChange={(e) => handleChange("brand", e.target.value)}>
              <option value="">All</option>
              {(opts.brands || []).map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <label>Offer Type</label>
            <select value={filters.offer_type || ""} onChange={(e) => handleChange("offer_type", e.target.value)}>
              <option value="">All</option>
              {(opts.offer_types || []).map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </div>
        </div>
      )}
    </div>
  );
}

export default PromotionFilters;
