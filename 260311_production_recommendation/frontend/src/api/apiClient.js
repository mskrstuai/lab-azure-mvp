const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export async function fetchCustomers(params = {}) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value != null && value !== "") searchParams.append(key, value);
  });
  const res = await fetch(`${API_BASE}/customers?${searchParams}`);
  if (!res.ok) throw new Error("Failed to load customers");
  return res.json();
}

export async function fetchCustomer(id) {
  const res = await fetch(`${API_BASE}/customers/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error("Customer not found");
  return res.json();
}

export async function fetchSimilarCustomers(id, params = {}) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value != null && value !== "") searchParams.append(key, value);
  });
  const res = await fetch(`${API_BASE}/customers/${encodeURIComponent(id)}/similar?${searchParams}`);
  if (!res.ok) throw new Error("Failed to load similar customers");
  return res.json();
}

export async function fetchRecommendations(id, limit = 10) {
  const res = await fetch(`${API_BASE}/customers/${encodeURIComponent(id)}/recommendations?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to load recommendations");
  return res.json();
}

export async function fetchSummaryStats() {
  const res = await fetch(`${API_BASE}/stats/summary`);
  if (!res.ok) throw new Error("Failed to load stats");
  return res.json();
}

export async function fetchInventoryAlerts() {
  const res = await fetch(`${API_BASE}/inventory/alerts`);
  if (!res.ok) throw new Error("Failed to load alerts");
  return res.json();
}

export async function fetchRegionalInventory(region) {
  const res = await fetch(`${API_BASE}/inventory/${encodeURIComponent(region)}`);
  if (!res.ok) throw new Error("Failed to load inventory");
  return res.json();
}

export async function fetchModelSummary() {
  const res = await fetch(`${API_BASE}/model/summary`);
  if (!res.ok) throw new Error("Failed to load model summary");
  return res.json();
}

export async function sendChatMessage(message, sessionId = "default") {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Chat request failed");
  }
  return res.json();
}

export async function resetChat(sessionId = "default") {
  const res = await fetch(`${API_BASE}/chat/reset?session_id=${sessionId}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to reset chat");
  return res.json();
}
