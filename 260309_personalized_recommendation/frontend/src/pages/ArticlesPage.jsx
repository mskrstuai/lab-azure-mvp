import { useEffect, useState } from "react";

import { fetchEntities } from "../api/apiClient";
import ArticleCard from "../components/ArticleCard";
import { DEFAULT_PAGE_LIMIT } from "../constants";

function ArticlesPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const limit = DEFAULT_PAGE_LIMIT;
  const page = Math.floor(offset / limit) + 1;

  useEffect(() => {
    setLoading(true);
    fetchEntities("articles", limit, offset)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [offset]);

  return (
    <section className="page-section">
      <h2 className="page-title">
        👗 Articles
        <span className="badge">Page {page}</span>
      </h2>

      {loading ? (
        <div className="loading">
          <div className="spinner" />
          <p>Loading articles…</p>
        </div>
      ) : rows.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>No articles found.</p>
        </div>
      ) : (
        <div className="article-grid">
          {rows.map((article) => (
            <ArticleCard key={article.article_id} article={article} />
          ))}
        </div>
      )}

      <div className="pagination">
        <button
          onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
          disabled={offset === 0}
        >
          ← Previous
        </button>
        <span className="page-info">Page {page}</span>
        <button
          onClick={() => setOffset((prev) => prev + limit)}
          disabled={rows.length < limit}
        >
          Next →
        </button>
      </div>
    </section>
  );
}

export default ArticlesPage;
