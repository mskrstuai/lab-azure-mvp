import { useEffect, useState, useCallback } from "react";
import {
  fetchCustomers,
  fetchRecommendations,
  fetchSimilarCustomers,
  fetchCustomer,
} from "../api/apiClient";

function RecommendationsPage() {
  const [customers, setCustomers] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [profile, setProfile] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [similarCustomers, setSimilarCustomers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [customersLoading, setCustomersLoading] = useState(true);

  useEffect(() => {
    fetchCustomers({ limit: 50, sort_by: "name" })
      .then(setCustomers)
      .catch(() => {})
      .finally(() => setCustomersLoading(false));
  }, []);

  const handleSelect = useCallback(async (id) => {
    if (!id) {
      setSelectedId("");
      setProfile(null);
      setRecommendations([]);
      setSimilarCustomers([]);
      return;
    }
    setSelectedId(id);
    setLoading(true);
    try {
      const [p, recs, similar] = await Promise.all([
        fetchCustomer(id),
        fetchRecommendations(id),
        fetchSimilarCustomers(id, { limit: 5, min_similarity: 0.3 }),
      ]);
      setProfile(p);
      setRecommendations(recs);
      setSimilarCustomers(similar);
    } catch {
      setProfile(null);
      setRecommendations([]);
      setSimilarCustomers([]);
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <section className="page-section">
      <h2 className="page-title">📋 Recommendations</h2>
      <p className="page-desc">
        Product recommendations and similar customers based on Jaccard similarity.
      </p>

      <div className="customer-select-bar">
        <div className="select-group">
          <span className="select-label">Select Customer</span>
          {customersLoading ? (
            <select disabled><option>Loading...</option></select>
          ) : (
            <select value={selectedId} onChange={(e) => handleSelect(e.target.value)}>
              <option value="">-- Select a customer --</option>
              {customers.map((c) => (
                <option key={c.customer_id} value={c.customer_id}>
                  {c.customer_id} — {c.name} ({c.type?.replace("_", " ")}, {c.region})
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {loading && (
        <div className="loading">
          <div className="spinner" />
          <p>Loading recommendations...</p>
        </div>
      )}

      {!loading && profile && (
        <>
          <div className="stats-grid" style={{ marginBottom: 24 }}>
            <div className="stat-card">
              <div className="stat-card-value">{profile.total_orders_90d}</div>
              <div className="stat-card-label">Orders (90d)</div>
            </div>
            <div className="stat-card">
              <div className="stat-card-value">${profile.avg_order_value?.toLocaleString()}</div>
              <div className="stat-card-label">Avg Value</div>
            </div>
            <div className="stat-card">
              <div className="stat-card-value">{profile.active_categories?.length || 0}</div>
              <div className="stat-card-label">Active Categories</div>
            </div>
            <div className="stat-card">
              <div className="stat-card-value">{similarCustomers.length}</div>
              <div className="stat-card-label">Similar Customers</div>
            </div>
          </div>

          {similarCustomers.length > 0 && (
            <>
              <h3 className="page-title" style={{ fontSize: "1rem" }}>
                Similar Customers
              </h3>
              <div className="similar-grid">
                {similarCustomers.map((sc) => (
                  <div key={sc.customer_id} className="similar-card">
                    <div className="sim-score">{(sc.similarity * 100).toFixed(1)}%</div>
                    <div className="sim-name">{sc.name}</div>
                    <div className="sim-meta">
                      <code>{sc.customer_id}</code> · {sc.type?.replace("_", " ")} · {sc.region}
                    </div>
                    <div className="sim-meta" style={{ marginTop: 4 }}>
                      {sc.shared_categories} shared categories
                      {sc.confidence_interval_95 && (
                        <span> · CI: [{(sc.confidence_interval_95[0] * 100).toFixed(0)}%–{(sc.confidence_interval_95[1] * 100).toFixed(0)}%]</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {recommendations.length > 0 && (
            <>
              <h3 className="page-title" style={{ fontSize: "1rem", marginTop: 28 }}>
                Recommended Products <span className="badge">{recommendations.length}</span>
              </h3>
              <div className="rec-grid">
                {recommendations.map((rec) => (
                  <div key={rec.product_id} className="rec-card">
                    <div className="rec-name">{rec.name}</div>
                    <div className="rec-category">{rec.category}</div>
                    <div className="rec-meta">
                      <span>${rec.unit_price?.toFixed(2)}</span>
                      <span>{rec.reason}</span>
                    </div>
                    <div className="rec-confidence">
                      Confidence: {(rec.confidence * 100).toFixed(0)}%
                    </div>
                    <div className="confidence-bar">
                      <div className="fill" style={{ width: `${rec.confidence * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {recommendations.length === 0 && (
            <div className="empty-state" style={{ paddingTop: 30 }}>
              <div className="icon">📋</div>
              <p>No recommendations found for this customer.</p>
            </div>
          )}
        </>
      )}

      {!loading && !profile && selectedId === "" && (
        <div className="empty-state">
          <div className="icon">📋</div>
          <p>Select a customer to see recommendations and similar customers.</p>
        </div>
      )}
    </section>
  );
}

export default RecommendationsPage;
