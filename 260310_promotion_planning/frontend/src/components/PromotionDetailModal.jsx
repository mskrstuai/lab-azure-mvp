import { useEffect, useState } from "react";
import { fetchPromotion } from "../api/apiClient";

function formatNum(v) {
  if (v == null || (typeof v === "number" && Number.isNaN(v))) return "—";
  if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(v);
}

function PromotionDetailModal({ promoId, onClose }) {
  const [promo, setPromo] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPromotion(promoId)
      .then(setPromo)
      .catch(() => setPromo(null))
      .finally(() => setLoading(false));
  }, [promoId]);

  const rows = promo
    ? [
        ["Promo ID", promo.promo_event_id],
        ["Market", promo.market],
        ["Retailer", promo.retailer],
        ["Segment", promo.segment],
        ["Category", promo.category],
        ["Brand", promo.brand],
        ["Flavor", promo.flavor],
        ["Pack Size", promo.pack_size],
        ["SKU", promo.sku_id],
        ["Description", promo.sku_description],
        ["Start", promo.promo_start_date],
        ["End", promo.promo_end_date],
        ["Duration", promo.promo_duration ? `${promo.promo_duration} days` : null],
        ["Offer Type", promo.offer_type],
        ["Discount Depth", promo.discount_depth != null ? `${(promo.discount_depth * 100).toFixed(0)}%` : null],
        ["Unit Price", promo.unit_price != null ? `$${promo.unit_price}` : null],
        ["Promo Price", promo.promo_unit_price != null ? `$${promo.promo_unit_price}` : null],
        ["Baseline Volume", formatNum(promo.baseline_volume)],
        ["Incremental Volume", formatNum(promo.incremental_volume)],
        ["Total Volume", formatNum(promo.total_volume)],
        ["Revenue", promo.revenue != null ? `$${formatNum(promo.revenue)}` : null],
        ["Incremental Revenue", promo.incremental_revenue != null ? `$${formatNum(promo.incremental_revenue)}` : null],
        ["Promo Investment", promo.promo_investment != null ? `$${formatNum(promo.promo_investment)}` : null],
        ["Profit System", promo.profit_system != null ? `$${formatNum(promo.profit_system)}` : null],
        ["Incremental Profit", promo.incremental_profit_system != null ? `$${formatNum(promo.incremental_profit_system)}` : null],
        ["Uplift %", promo.promo_uplift_pct != null ? `${(promo.promo_uplift_pct * 100).toFixed(1)}%` : null],
      ].filter(([, v]) => v != null && v !== "")
    : [];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <h2 className="detail-title">Promotion Details</h2>
        {loading ? (
          <div className="loading">
            <div className="spinner" />
            <p>Loading…</p>
          </div>
        ) : !promo ? (
          <p>Promotion not found.</p>
        ) : (
          <div className="detail-layout">
            <div className="detail-main">
              <div className="detail-product">
                <strong>{promo.sku_description || promo.sku_id}</strong>
                <div className="detail-meta">
                  <span className="detail-tag">{promo.brand}</span>
                  <span className="detail-tag">{promo.category}</span>
                  <span className="detail-tag">{promo.offer_type}</span>
                </div>
              </div>
              <table className="detail-table">
                <tbody>
                  {rows.map(([label, value]) => (
                    <tr key={label}>
                      <th>{label}</th>
                      <td>{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default PromotionDetailModal;
