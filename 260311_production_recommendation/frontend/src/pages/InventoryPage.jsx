import { useEffect, useState } from "react";
import { fetchInventoryAlerts, fetchRegionalInventory } from "../api/apiClient";

const REGIONS = ["midwest", "northeast", "southeast", "southwest", "west"];

function InventoryPage() {
  const [alerts, setAlerts] = useState([]);
  const [region, setRegion] = useState("midwest");
  const [inventory, setInventory] = useState([]);
  const [alertsLoading, setAlertsLoading] = useState(true);
  const [invLoading, setInvLoading] = useState(false);

  useEffect(() => {
    fetchInventoryAlerts()
      .then(setAlerts)
      .catch(() => setAlerts([]))
      .finally(() => setAlertsLoading(false));
  }, []);

  useEffect(() => {
    if (!region) return;
    setInvLoading(true);
    fetchRegionalInventory(region)
      .then(setInventory)
      .catch(() => setInventory([]))
      .finally(() => setInvLoading(false));
  }, [region]);

  const getStatusClass = (status) => {
    if (status === "critical" || status === "shortage") return "critical";
    if (status === "low") return "low";
    return "adequate";
  };

  return (
    <section className="page-section">
      <h2 className="page-title">📦 Inventory</h2>
      <p className="page-desc">
        Regional inventory status and active supply chain alerts.
      </p>

      {alertsLoading ? (
        <div className="loading">
          <div className="spinner" />
          <p>Loading alerts...</p>
        </div>
      ) : alerts.length > 0 ? (
        <>
          <h3 className="page-title" style={{ fontSize: "1rem" }}>
            Active Alerts <span className="badge">{alerts.length}</span>
          </h3>
          {alerts.map((alert) => (
            <div
              key={alert.alert_id}
              className={`alert-card ${alert.type === "critical_shortage" ? "critical" : "warning"}`}
            >
              <div className="alert-title">
                {alert.type === "critical_shortage" ? "🔴" : "🟡"} {alert.alert_id}
              </div>
              <div className="alert-region">{alert.region}</div>
              <div className="alert-message">{alert.message}</div>
              <div className="alert-products">
                {alert.products_affected?.map((p) => (
                  <span key={p} className="detail-tag">{p}</span>
                ))}
              </div>
            </div>
          ))}
        </>
      ) : (
        <div style={{ marginBottom: 24, color: "var(--color-success)", fontSize: "0.9rem" }}>
          ✅ No active alerts
        </div>
      )}

      <h3 className="page-title" style={{ fontSize: "1rem", marginTop: 28 }}>
        Regional Inventory
      </h3>

      <div className="region-tabs">
        {REGIONS.map((r) => (
          <button
            key={r}
            className={`region-tab ${region === r ? "active" : ""}`}
            onClick={() => setRegion(r)}
          >
            {r}
          </button>
        ))}
      </div>

      {invLoading ? (
        <div className="loading">
          <div className="spinner" />
          <p>Loading inventory...</p>
        </div>
      ) : inventory.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📦</div>
          <p>No inventory data for this region.</p>
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Product ID</th>
                <th>Name</th>
                <th>Stock Level</th>
                <th>Days of Supply</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {inventory.map((item) => (
                <tr key={item.product_id}>
                  <td><code>{item.product_id}</code></td>
                  <td>{item.name}</td>
                  <td>{item.stock_level?.toLocaleString()}</td>
                  <td>{item.days_of_supply}</td>
                  <td>
                    <span className={`status-badge ${getStatusClass(item.status)}`}>
                      {item.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default InventoryPage;
