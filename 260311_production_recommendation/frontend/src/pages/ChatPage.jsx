import { useState, useRef, useEffect, useCallback } from "react";
import { sendChatMessage, resetChat } from "../api/apiClient";

let nextId = 1;

function parseMarkdown(text) {
  if (!text) return "";
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  html = html.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code.trim()}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  const lines = html.split("\n");
  const result = [];
  let inList = false;
  let listType = null;

  for (const line of lines) {
    const trimmed = line.trim();
    const ulMatch = trimmed.match(/^[-•]\s+(.+)/);
    const olMatch = trimmed.match(/^\d+\.\s+(.+)/);

    if (ulMatch) {
      if (!inList || listType !== "ul") {
        if (inList) result.push(listType === "ul" ? "</ul>" : "</ol>");
        result.push("<ul>");
        inList = true;
        listType = "ul";
      }
      result.push(`<li>${ulMatch[1]}</li>`);
    } else if (olMatch) {
      if (!inList || listType !== "ol") {
        if (inList) result.push(listType === "ul" ? "</ul>" : "</ol>");
        result.push("<ol>");
        inList = true;
        listType = "ol";
      }
      result.push(`<li>${olMatch[1]}</li>`);
    } else {
      if (inList) {
        result.push(listType === "ul" ? "</ul>" : "</ol>");
        inList = false;
        listType = null;
      }
      if (trimmed.startsWith("<h") || trimmed.startsWith("<pre>") || trimmed === "") {
        result.push(trimmed === "" ? "" : line);
      } else {
        result.push(`<p>${line}</p>`);
      }
    }
  }
  if (inList) result.push(listType === "ul" ? "</ul>" : "</ol>");

  return result.join("\n");
}

const EXAMPLES = [
  "Show me hospitals in the midwest",
  "Who are similar customers to CG-0001?",
  "Recommend products for CG-0023",
  "Are there any inventory alerts?",
  "Explain why CG-0001 and CG-0012 are similar",
  "Compare similarity algorithms for CG-0005",
];

function ChatPage() {
  const [messages, setMessages] = useState([
    {
      id: 0,
      sender: "assistant",
      text: "Hello! I'm the **Healthcare Supply Chain Advisor**. I can help with customer profiling, product recommendations, inventory optimization, and ML model insights.\n\nTry asking me something, or click one of the examples below.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(() => `session_${Date.now()}`);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(
    async (text) => {
      const msg = (text || input).trim();
      if (!msg || loading) return;

      const userMsg = { id: nextId++, sender: "user", text: msg };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setLoading(true);

      try {
        const data = await sendChatMessage(msg, sessionId);
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
            text: "Failed to reach the server. Make sure the backend is running and Azure OpenAI is configured.",
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [input, loading, sessionId]
  );

  const handleReset = useCallback(async () => {
    await resetChat(sessionId).catch(() => {});
    setMessages([
      {
        id: nextId++,
        sender: "assistant",
        text: "Conversation reset. How can I help you?",
      },
    ]);
  }, [sessionId]);

  return (
    <section className="chat-page">
      <div className="chat-container">
        <div className="chat-messages">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`chat-bubble ${msg.sender === "user" ? "chat-user" : "chat-assistant"}`}
            >
              <div className="chat-avatar">
                {msg.sender === "user" ? "👤" : "🤖"}
              </div>
              <div
                className="chat-text"
                dangerouslySetInnerHTML={{ __html: parseMarkdown(msg.text) }}
              />
            </div>
          ))}
          {loading && (
            <div className="chat-bubble chat-assistant">
              <div className="chat-avatar">🤖</div>
              <div className="chat-text">
                <div className="chat-typing">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          )}
          {messages.length === 1 && !loading && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: "0 48px" }}>
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  className="chip"
                  onClick={() => handleSend(ex)}
                >
                  {ex}
                </button>
              ))}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        <div className="chat-actions">
          <button className="chat-reset-btn" onClick={handleReset}>
            Reset conversation
          </button>
        </div>
        <div className="chat-input-bar">
          <input
            type="text"
            className="chat-input"
            placeholder="Ask about customers, recommendations, inventory, or ML model..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            disabled={loading}
          />
          <button
            className="chat-send-btn"
            onClick={() => handleSend()}
            disabled={loading || !input.trim()}
          >
            {loading ? "..." : "Send"}
          </button>
        </div>
      </div>
    </section>
  );
}

export default ChatPage;
