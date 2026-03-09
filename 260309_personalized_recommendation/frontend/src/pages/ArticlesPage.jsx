import { useCallback, useEffect, useState } from "react";

import { fetchEntities } from "../api/apiClient";
import ArticleCard from "../components/ArticleCard";
import ArticleDetailModal from "../components/ArticleDetailModal";
import ArticleFilters from "../components/ArticleFilters";
import { DEFAULT_PAGE_LIMIT } from "../constants";

const EMPTY_FILTERS = {
  prod_name: "",
  index_group_name: "",
  product_type_name: "",
  product_group_name: "",
  colour_group_name: "",
  section_name: "",
  garment_group_name: "",
};

function ArticlesPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState(null);
  const limit = DEFAULT_PAGE_LIMIT;
  const page = Math.floor(offset / limit) + 1;

  const loadArticles = useCallback(() => {
    setLoading(true);
    fetchEntities("articles", limit, offset, filters)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [offset, filters, limit]);

  useEffect(() => {
    loadArticles();
  }, [loadArticles]);

  const handleFilterChange = (newFilters) => {
    setFilters(newFilters);
    setOffset(0);
  };

  return (
    <section className="page-section">
      <h2 className="page-title">
        👗 Articles
        <span className="badge">Page {page}</span>
      </h2>

      <ArticleFilters filters={filters} onFilterChange={handleFilterChange} />

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
            <ArticleCard
              key={article.article_id}
              article={article}
              onClick={setSelectedId}
            />
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

      {selectedId && (
        <ArticleDetailModal
          articleId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </section>
  );
}

export default ArticlesPage;
