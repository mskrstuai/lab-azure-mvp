import { useEffect, useState, useMemo } from "react";
import { fetchCustomers, fetchSummaryStats } from "../api/apiClient";

const REGIONS = ["", "midwest", "northeast", "southeast", "southwest", "west"];
const TYPES = ["", "hospital", "clinic", "surgery_center", "nursing_home", "urgent_care"];

function CustomersPage() {
  const [customers, setCustomers] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [region, setRegion] = useState("");
  const [type, setType] = useState("");
  const [sortCol, setSortCol] = useState("total_orders_90d");
  const [sortAsc, setSortAsc] = useState(false);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchCustomers({ region: region || undefined, type: type || undefined, limit: 50 }),
      fetchSummaryStats(),
    ])
      .then(([c, s]) => {
        setCustomers(c);
        setStats(s);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [region, type]);

  const sorted = useMemo(() => {
    if (!customers.length) return [];
    return [...customers].sort((a, b) => {
      const va = a[sortCol];
      const vb = b[sortCol];
      let cmp = 0;
      if (typeof va === "number") cmp = va - vb;
      else cmp = String(va || "").localeCompare(String(vb || ""));
      return sortAsc ? cmp : -cmp;
    });
  }, [customers, sortCol, sortAsc]);

  const handleSort = (col) => {
    setSortCol(col);
    setSortAsc((prev) => (sortCol === col ? !prev : false));
  };

  const columns = [
    { key: "customer_id", label: "ID" },
    { key: "name", label: "Name" },
    { key: "type", label: "Type" },
    { key: "region", label: "Region" },
    { key: "size", label: "Size" },
    { key: "total_orders_90d", label: "Orders (90d)" },
    { key: "avg_order_value", label: "Avg Value" },
  ];

  return (
    <section className="page-section">
      <h2 className="page-title">
        🏥 Customers {stats && <span className="badge">{stats.total_customers}</span>}
      </h2>
      <p className="page-desc">
        Healthcare supply chain customer profiles with purchasing patterns.
      </p>

      {stats && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-card-value">{stats.total_customers}</div>
            <div className="stat-card-label">Total Customers</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-value">{stats.avg_orders_90d}</div>
            <div className="stat-card-label">Avg Orders (90d)</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-value">${stats.avg_order_value?.toLocaleString()}</div>
            <div className="stat-card-label">Avg Order Value</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-value">{stats.total_products}</div>
            <div className="stat-card-label">Products</div>
          </div>
        </div>
      )}

      <div className="filter-bar">
        <div className="filter-field">
          <label>Region</label>
          <select value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">All Regions</option>
            {REGIONS.filter(Boolean).map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <label>Facility Type</label>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All Types</option>
            {TYPES.filter(Boolean).map((t) => (
              <option key={t} value={t}>{t.replace("_", " ")}</option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="loading">
          <div className="spinner" />
          <p>Loading customers...</p>
        </div>
      ) : sorted.length === 0 ? (
        <div className="empty-state">
          <div className="icon">🏥</div>
          <p>No customers found.</p>
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                {columns.map(({ key, label }) => (
                  <th
                    key={key}
                    className="sortable"
                    onClick={() => handleSort(key)}
                  >
                    {label}
                    <span className={`sort-icon ${sortCol === key ? "active" : ""}`}>
                      {sortCol === key ? (sortAsc ? " ↑" : " ↓") : " ⇅"}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => (
                <tr
                  key={c.customer_id}
                  className="clickable"
                  onClick={() => setSelected(c)}
                >
                  <td><code>{c.customer_id}</code></td>
                  <td>{c.name}</td>
                  <td>{c.type?.replace("_", " ")}</td>
                  <td>{c.region}</td>
                  <td>{c.size}</td>
                  <td>{c.total_orders_90d}</td>
                  <td>${c.avg_order_value?.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="modal-overlay" onClick={() => setSelected(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setSelected(null)}>
              ×
            </button>
            <h2 className="detail-title">
              {selected.name} ({selected.customer_id})
            </h2>
            <table className="detail-table">
              <tbody>
                <tr><th>Type</th><td>{selected.type?.replace("_", " ")}</td></tr>
                <tr><th>Region</th><td>{selected.region}</td></tr>
                <tr><th>Size</th><td>{selected.size}</td></tr>
                <tr><th>Orders (90d)</th><td>{selected.total_orders_90d}</td></tr>
                <tr><th>Avg Order Value</th><td>${selected.avg_order_value?.toLocaleString()}</td></tr>
                <tr>
                  <th>Active Categories</th>
                  <td>
                    <div className="detail-tags">
                      {selected.active_categories?.map((cat) => (
                        <span key={cat} className="detail-tag">{cat}</span>
                      ))}
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

export default CustomersPage;
