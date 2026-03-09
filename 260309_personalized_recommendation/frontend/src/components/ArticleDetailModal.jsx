import { useEffect, useState } from "react";
import { API_SERVER_URL, fetchEntity } from "../api/apiClient";

const FIELD_LABELS = {
  article_id: "Article ID",
  product_code: "Product Code",
  prod_name: "Product Name",
  product_type_name: "Product Type",
  product_group_name: "Product Group",
  graphical_appearance_name: "Graphical Appearance",
  colour_group_name: "Colour Group",
  perceived_colour_value_name: "Perceived Colour Value",
  perceived_colour_master_name: "Perceived Colour Master",
  department_name: "Department",
  index_name: "Index",
  index_group_name: "Index Group",
  section_name: "Section",
  garment_group_name: "Garment Group",
  detail_desc: "Description",
};

function ArticleDetailModal({ articleId, onClose }) {
  const [article, setArticle] = useState(null);
  const [loading, setLoading] = useState(true);
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    if (!articleId) return;
    setLoading(true);
    setImgError(false);
    fetchEntity("articles", articleId)
      .then(setArticle)
      .catch(() => setArticle(null))
      .finally(() => setLoading(false));
  }, [articleId]);

  if (!articleId) return null;

  const imageUrl = article?.image_url ? `${API_SERVER_URL}${article.image_url}` : null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>

        {loading ? (
          <div className="loading">
            <div className="spinner" />
            <p>Loading article…</p>
          </div>
        ) : !article ? (
          <div className="empty-state">
            <div className="icon">❌</div>
            <p>Article not found.</p>
          </div>
        ) : (
          <div className="detail-layout">
            <div className="detail-image-section">
              {imageUrl && !imgError ? (
                <img
                  className="detail-image"
                  src={imageUrl}
                  alt={article.prod_name || article.article_id}
                  onError={() => setImgError(true)}
                />
              ) : (
                <div className="detail-image-placeholder">No Image</div>
              )}
            </div>
            <div className="detail-info-section">
              <h2 className="detail-title">{article.prod_name || "Unnamed Article"}</h2>
              <table className="detail-table">
                <tbody>
                  {Object.entries(FIELD_LABELS).map(([key, label]) => (
                    <tr key={key}>
                      <th>{label}</th>
                      <td>{article[key] ?? "—"}</td>
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

export default ArticleDetailModal;
