import { useEffect, useState } from "react";
import { fetchFilterOptions } from "../api/apiClient";

const FILTER_LABELS = {
  prod_name: "Product Name",
  index_group_name: "Gender / Index Group",
  product_type_name: "Product Type",
  product_group_name: "Product Group",
  colour_group_name: "Colour",
  section_name: "Section",
  garment_group_name: "Garment Group",
};

function ArticleFilters({ filters, onFilterChange }) {
  const [options, setOptions] = useState({});
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetchFilterOptions()
      .then(setOptions)
      .catch(() => setOptions({}));
  }, []);

  const activeCount = Object.values(filters).filter(Boolean).length;

  return (
    <div className="filter-bar">
      <div className="filter-header">
        <button
          className="filter-toggle"
          onClick={() => setExpanded((prev) => !prev)}
        >
          🔍 Filters {activeCount > 0 && <span className="filter-count">{activeCount}</span>}
          <span className="toggle-arrow">{expanded ? "▲" : "▼"}</span>
        </button>
        {activeCount > 0 && (
          <button
            className="filter-clear"
            onClick={() => {
              const cleared = {};
              Object.keys(filters).forEach((k) => (cleared[k] = ""));
              onFilterChange(cleared);
            }}
          >
            Clear all
          </button>
        )}
      </div>

      {expanded && (
        <div className="filter-grid">
          {/* Text search for product name */}
          <div className="filter-field">
            <label>{FILTER_LABELS.prod_name}</label>
            <input
              type="text"
              placeholder="Search name…"
              value={filters.prod_name || ""}
              onChange={(e) =>
                onFilterChange({ ...filters, prod_name: e.target.value })
              }
            />
          </div>

          {/* Dropdown filters */}
          {Object.entries(FILTER_LABELS)
            .filter(([key]) => key !== "prod_name")
            .map(([key, label]) => (
              <div className="filter-field" key={key}>
                <label>{label}</label>
                <select
                  value={filters[key] || ""}
                  onChange={(e) =>
                    onFilterChange({ ...filters, [key]: e.target.value })
                  }
                >
                  <option value="">All</option>
                  {(options[key] || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

export default ArticleFilters;
