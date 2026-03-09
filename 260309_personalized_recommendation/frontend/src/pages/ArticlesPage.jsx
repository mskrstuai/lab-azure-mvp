import { useEffect, useState } from "react";

import { fetchEntities } from "../api/apiClient";
import EntityTable from "../components/EntityTable";

function ArticlesPage() {
  const [rows, setRows] = useState([]);
  const [offset, setOffset] = useState(0);
  const limit = 20;

  useEffect(() => {
    fetchEntities("articles", limit, offset).then(setRows).catch(() => setRows([]));
  }, [offset]);

  return (
    <section>
      <EntityTable rows={rows} />
      <div className="pagination">
        <button onClick={() => setOffset((prev) => Math.max(0, prev - limit))}>Previous</button>
        <button onClick={() => setOffset((prev) => prev + limit)}>Next</button>
      </div>
    </section>
  );
}

export default ArticlesPage;
