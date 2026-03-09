import { useEffect, useState } from "react";

import { fetchEntities } from "../api/apiClient";
import { API_BASE_URL } from "../api/apiClient";
import EntityTable from "../components/EntityTable";
import { DEFAULT_PAGE_LIMIT } from "../constants";

function ChatsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [customerIdFilter, setCustomerIdFilter] = useState("");
  const [appliedFilter, setAppliedFilter] = useState("");
  const [newMessage, setNewMessage] = useState("");
  const [senderId, setSenderId] = useState("");
  const limit = DEFAULT_PAGE_LIMIT;
  const page = Math.floor(offset / limit) + 1;

  const loadChats = () => {
    setLoading(true);
    const filters = appliedFilter ? { customer_id: appliedFilter } : {};
    fetchEntities("chats", limit, offset, filters)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadChats();
  }, [limit, offset, appliedFilter]);

  const handleApplyFilter = () => {
    setOffset(0);
    setAppliedFilter(customerIdFilter);
  };

  const handleClearFilter = () => {
    setCustomerIdFilter("");
    setOffset(0);
    setAppliedFilter("");
  };

  const handleSendMessage = async () => {
    if (!newMessage.trim()) return;
    try {
      await fetch(`${API_BASE_URL}/chats`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_id: senderId || null,
          message: newMessage,
          sender: "user",
        }),
      });
      setNewMessage("");
      loadChats();
    } catch {
      /* ignore send errors for now */
    }
  };

  return (
    <section className="page-section">
      <h2 className="page-title">
        💬 Chats
        <span className="badge">Page {page}</span>
      </h2>

      <div className="filter-bar-inline">
        <input
          type="text"
          className="filter-input"
          placeholder="Filter by customer ID…"
          value={customerIdFilter}
          onChange={(e) => setCustomerIdFilter(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleApplyFilter()}
        />
        <button className="filter-apply-btn" onClick={handleApplyFilter}>
          Search
        </button>
        {appliedFilter && (
          <button className="filter-clear-btn" onClick={handleClearFilter}>
            Clear
          </button>
        )}
      </div>

      <div className="chat-compose">
        <input
          type="text"
          className="filter-input"
          placeholder="Customer ID (optional)"
          value={senderId}
          onChange={(e) => setSenderId(e.target.value)}
          style={{ maxWidth: 220 }}
        />
        <input
          type="text"
          className="filter-input chat-message-input"
          placeholder="Type a message…"
          value={newMessage}
          onChange={(e) => setNewMessage(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSendMessage()}
        />
        <button className="filter-apply-btn" onClick={handleSendMessage}>
          Send
        </button>
      </div>

      {loading ? (
        <div className="loading">
          <div className="spinner" />
          <p>Loading chats…</p>
        </div>
      ) : rows.length === 0 ? (
        <div className="empty-state">
          <p className="empty-icon">💬</p>
          <p>No chats yet. Send a message to get started.</p>
        </div>
      ) : (
        <EntityTable rows={rows} />
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

export default ChatsPage;
