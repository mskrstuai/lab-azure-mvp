import { useEffect, useState } from "react";
import { fetchStats } from "../api/apiClient";

function formatCurrency(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  const suffix = v < 0 ? "-" : "";
  if (abs >= 1e6) return `${suffix}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${suffix}$${(abs / 1e3).toFixed(1)}K`;
  return `${suffix}$${abs.toFixed(0)}`;
}

function formatPct(v) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function StatCard({ label, value, sub }) {
  return (
    <div className="stat-card">
      <div className="stat-card-value">{value}</div>
      <div className="stat-card-label">{label}</div>
      {sub != null && <div className="stat-card-sub">{sub}</div>}
    </div>
  );
}

function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <section className="page-section">
        <div className="loading">
          <div className="spinner" />
          <p>Loading dashboard…</p>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="page-section">
        <div className="empty-state">
          <div className="icon">⚠️</div>
          <p>{error}</p>
          <p className="hint">Ensure the backend is running on port 8000.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="page-section">
      <h2 className="page-title">📊 Dashboard</h2>

      <div className="stats-grid">
        <StatCard label="Total Promotions" value={stats?.total_promotions ?? "—"} />
        <StatCard label="Total Revenue" value={formatCurrency(stats?.total_revenue)} />
        <StatCard label="Incremental Revenue" value={formatCurrency(stats?.total_incremental_revenue)} />
        <StatCard label="Incremental Profit" value={formatCurrency(stats?.total_incremental_profit)} />
        <StatCard label="Promo Investment" value={formatCurrency(stats?.total_promo_investment)} />
        <StatCard label="Avg Uplift" value={formatPct(stats?.avg_uplift_pct)} />
      </div>

      <div className="stats-grid stats-grid-sm">
        <StatCard label="Markets" value={stats?.markets_count ?? "—"} />
        <StatCard label="Retailers" value={stats?.retailers_count ?? "—"} />
        <StatCard label="Brands" value={stats?.brands_count ?? "—"} />
      </div>
    </section>
  );
}

export default DashboardPage;
