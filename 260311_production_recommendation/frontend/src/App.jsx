import { useState } from "react";

import CustomersPage from "./pages/CustomersPage";
import RecommendationsPage from "./pages/RecommendationsPage";
import InventoryPage from "./pages/InventoryPage";
import ChatPage from "./pages/ChatPage";

const TABS = {
  chat: { label: "Chat Advisor", icon: "💬" },
  customers: { label: "Customers", icon: "🏥" },
  recommendations: { label: "Recommendations", icon: "📋" },
  inventory: { label: "Inventory", icon: "📦" },
};

function App() {
  const [activeTab, setActiveTab] = useState("chat");

  return (
    <>
      <header className="app-header">
        <h1>Production Recommendation</h1>
        <p className="subtitle">Healthcare Supply Chain &mdash; Hybrid AI Demo</p>
        <nav className="tabs">
          {Object.entries(TABS).map(([key, { label, icon }]) => (
            <button
              key={key}
              className={`tab ${activeTab === key ? "active" : ""}`}
              onClick={() => setActiveTab(key)}
            >
              {icon}&ensp;{label}
            </button>
          ))}
        </nav>
      </header>
      <main className="main-content">
        {activeTab === "chat" && <ChatPage />}
        {activeTab === "customers" && <CustomersPage />}
        {activeTab === "recommendations" && <RecommendationsPage />}
        {activeTab === "inventory" && <InventoryPage />}
      </main>
    </>
  );
}

export default App;
