import { useState, useRef, useEffect, useCallback } from "react";

import { API_BASE_URL } from "../api/apiClient";

let nextId = 1;

function ChatsPage() {
  const [messages, setMessages] = useState([
    {
      id: 0,
      sender: "assistant",
      text: "👋 Hi! I'm the H&M Fashion Assistant. Ask me anything about products, recommendations, or style advice. (Agent coming soon!)",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

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

    try {
      const res = await fetch(`${API_BASE_URL}/chats`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        { id: nextId++, sender: "assistant", text: data.reply },
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
  }, [input, loading]);

  return (
    <section className="chat-page">
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
                <p>{msg.text}</p>
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
    </section>
  );
}

export default ChatsPage;
