import { useState } from "react";

import ArticlesPage from "./pages/ArticlesPage";
import CustomersPage from "./pages/CustomersPage";
import TransactionsPage from "./pages/TransactionsPage";
import ChatsPage from "./pages/ChatsPage";

const TABS = {
  articles: { label: "Articles", icon: "👗" },
  customers: { label: "Customers", icon: "👤" },
  transactions: { label: "Transactions", icon: "📋" },
  chats: { label: "Chats", icon: "💬" }
};

function App() {
  const [activeTab, setActiveTab] = useState("articles");

  return (
    <>
      <header className="app-header">
        <h1>H&amp;M Recommendation Demo</h1>
        <p className="subtitle">Personalized Fashion Recommendations</p>
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
        {activeTab === "articles" && <ArticlesPage />}
        {activeTab === "customers" && <CustomersPage />}
        {activeTab === "transactions" && <TransactionsPage />}
        {activeTab === "chats" && <ChatsPage />}
      </main>
    </>
  );
}

export default App;
