import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";

import { API_BASE_URL, API_SERVER_URL } from "../api/apiClient";

let nextId = 1;

function CustomerPreferencesPanel({ customerId, preferences, onClose }) {
  if (!preferences) return null;
  return (
    <div className="chat-preferences-panel">
      <div className="chat-preferences-header">
        <span className="chat-preferences-title">Customer Preferences</span>
        <button type="button" className="chat-preferences-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <div className="chat-preferences-body">
        <div className="chat-preferences-section">
          <h5>Overall Preferences</h5>
          <div className="chat-preferences-content">
            <ReactMarkdown remarkPlugins={[remarkBreaks]}>
              {preferences.overall_summary || "No overall preferences available."}
            </ReactMarkdown>
          </div>
        </div>
        <div className="chat-preferences-section">
          <h5>Short-term Preferences</h5>
          <div className="chat-preferences-content">
            <ReactMarkdown remarkPlugins={[remarkBreaks]}>
              {preferences.short_term_summary || "No short-term preferences available."}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
}

function ChatSearchResults({ results }) {
  if (!results || results.length === 0) return null;
  return (
    <div className="chat-search-results">
      <h4 className="chat-search-results-title">Search Results ({results.length} items)</h4>
      <div className="chat-search-results-grid">
        {results.map((item) => (
          <div key={item.article_id} className="chat-search-result-card">
            <div className="chat-search-result-img-wrap">
              {item.image_url ? (
                <>
                  <img
                    src={`${API_SERVER_URL}${item.image_url}`}
                    alt={item.prod_name || item.article_id}
                    className="chat-search-result-img"
                    onError={(e) => {
                      e.target.style.display = "none";
                      e.target.nextElementSibling?.classList.add("visible");
                    }}
                  />
                  <div className="chat-search-result-placeholder">No image</div>
                </>
              ) : (
                <div className="chat-search-result-placeholder visible">No image</div>
              )}
            </div>
            <div className="chat-search-result-info">
              <div className="chat-search-result-name" title={item.prod_name}>
                {item.prod_name || "Unknown"}
              </div>
              <div className="chat-search-result-meta">{item.product_type_name}</div>
              <div className="chat-search-result-meta colour">{item.colour_group_name}</div>
              <div className="chat-search-result-id">ID: {item.article_id}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChatsPage() {
  const [messages, setMessages] = useState([
    {
      id: 0,
      sender: "assistant",
      text: "👋 Hi! I'm the H&M Fashion Assistant. Select a customer to personalize recommendations, then ask me anything about products or style advice.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [customers, setCustomers] = useState([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState("");
  const [preferences, setPreferences] = useState(null);
  const [showPreferences, setShowPreferences] = useState(false);
  const [preferencesLoading, setPreferencesLoading] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/preferences/customers`)
      .then((r) => r.json())
      .then((data) => setCustomers(data.customers || []))
      .catch(() => setCustomers([]));
  }, []);

  useEffect(() => {
    if (!selectedCustomerId) {
      setPreferences(null);
      return;
    }

    // Reset server-side agent session and frontend chat when customer changes
    fetch(`${API_BASE_URL}/chats?customer_id=${selectedCustomerId}`, { method: "DELETE" }).catch(() => {});
    setMessages([
      {
        id: 0,
        sender: "assistant",
        text: `Customer selected. Ask me anything about products, recommendations, or style advice!`,
      },
    ]);
    nextId = 1;

    setPreferencesLoading(true);
    fetch(`${API_BASE_URL}/preferences/customers/${selectedCustomerId}`)
      .then((r) => r.json())
      .then((data) => {
        setPreferences(data);
        setShowPreferences(true);
      })
      .catch(() => setPreferences(null))
      .finally(() => setPreferencesLoading(false));
  }, [selectedCustomerId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg = { id: nextId++, sender: "user", text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    const body = { message: text };
    if (selectedCustomerId) body.customer_id = selectedCustomerId;

    try {
      const res = await fetch(`${API_BASE_URL}/chats`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          id: nextId++,
          sender: "assistant",
          text: data.reply,
          searchResults: data.search_results || null,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: nextId++,
          sender: "assistant",
          text: "⚠️ Failed to reach the server. Please try again.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, selectedCustomerId]);

  return (
    <section className="chat-page">
      <div className="chat-page-layout">
        <aside className="chat-sidebar">
          <div className="chat-customer-selector">
            <label htmlFor="customer-select">Customer</label>
            <select
              id="customer-select"
              value={selectedCustomerId}
              onChange={(e) => setSelectedCustomerId(e.target.value)}
              className="chat-customer-select"
            >
              <option value="">— Select customer —</option>
              {customers.map((cid, i) => (
                <option key={cid} value={cid} title={cid}>
                  Customer {i + 1} ({cid.slice(0, 8)}…)
                </option>
              ))}
            </select>
            {selectedCustomerId && (
              <button
                type="button"
                className="chat-show-prefs-btn"
                onClick={() => setShowPreferences(!showPreferences)}
                disabled={preferencesLoading}
              >
                {showPreferences ? "Hide" : "Show"} preferences
              </button>
            )}
          </div>
          {showPreferences && preferences && (
            <CustomerPreferencesPanel
              customerId={selectedCustomerId}
              preferences={preferences}
              onClose={() => setShowPreferences(false)}
            />
          )}
        </aside>
        <div className="chat-main">
      <div className="chat-container">
        {/* Message area */}
        <div className="chat-messages">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`chat-bubble ${msg.sender === "user" ? "chat-user" : "chat-assistant"}`}
            >
              <div className="chat-avatar">
                {msg.sender === "user" ? "👤" : "🤖"}
              </div>
              <div className="chat-text">
                <div className="chat-text-content">
                  <ReactMarkdown remarkPlugins={[remarkBreaks]}>{msg.text}</ReactMarkdown>
                </div>
                {msg.sender === "assistant" && msg.searchResults && (
                  <ChatSearchResults results={msg.searchResults} />
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="chat-bubble chat-assistant">
              <div className="chat-avatar">🤖</div>
              <div className="chat-text">
                <div className="chat-typing">
                  <span></span><span></span><span></span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="chat-input-bar">
          <input
            type="text"
            className="chat-input"
            placeholder="Type your message…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            disabled={loading}
          />
          <button
            className="chat-send-btn"
            onClick={handleSend}
            disabled={loading || !input.trim()}
          >
            {loading ? "…" : "Send ➤"}
          </button>
        </div>
      </div>
        </div>
      </div>
    </section>
  );
}

export default ChatsPage;
