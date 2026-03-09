import { useState } from "react";
import { API_SERVER_URL } from "../api/apiClient";

function ArticleCard({ article, onClick }) {
  const [imgError, setImgError] = useState(false);
  const imageUrl = article.image_url ? `${API_SERVER_URL}${article.image_url}` : null;

  return (
    <div className="article-card" onClick={() => onClick && onClick(article.article_id)}>
      {imageUrl && !imgError ? (
        <img
          className="card-image"
          src={imageUrl}
          alt={article.prod_name || article.article_id}
          loading="lazy"
          onError={() => setImgError(true)}
        />
      ) : (
        <div className="card-image-placeholder">No Image</div>
      )}
      <div className="card-body">
        <h3>{article.prod_name || "Unnamed Article"}</h3>
        <p className="card-id">ID: {article.article_id}</p>
        <div className="card-meta">
          {article.product_type_name && (
            <span className="card-tag">{article.product_type_name}</span>
          )}
          {article.colour_group_name && (
            <span className="card-tag colour">{article.colour_group_name}</span>
          )}
          {article.department_name && (
            <span className="card-tag">{article.department_name}</span>
          )}
          {article.section_name && (
            <span className="card-tag">{article.section_name}</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default ArticleCard;
