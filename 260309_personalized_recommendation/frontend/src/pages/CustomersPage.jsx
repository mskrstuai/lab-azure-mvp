import { useEffect, useState } from "react";

import { fetchEntities } from "../api/apiClient";
import EntityTable from "../components/EntityTable";
import { DEFAULT_PAGE_LIMIT } from "../constants";

function CustomersPage() {
  const [rows, setRows] = useState([]);
  const [offset, setOffset] = useState(0);
  const limit = DEFAULT_PAGE_LIMIT;

  useEffect(() => {
    fetchEntities("customers", limit, offset).then(setRows).catch(() => setRows([]));
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

export default CustomersPage;
