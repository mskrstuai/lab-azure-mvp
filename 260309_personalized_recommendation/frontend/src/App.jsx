import { useState } from "react";

import ArticlesPage from "./pages/ArticlesPage";
import CustomersPage from "./pages/CustomersPage";
import TransactionsPage from "./pages/TransactionsPage";

const TABS = {
  articles: "Articles",
  customers: "Customers",
  transactions: "Transactions"
};

function App() {
  const [activeTab, setActiveTab] = useState("articles");

  return (
    <div className="container">
      <h1>H&amp;M Personalized Recommendation Demo</h1>
      <div className="tabs">
        {Object.entries(TABS).map(([key, label]) => (
          <button
            key={key}
            className={`tab ${activeTab === key ? "active" : ""}`}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {activeTab === "articles" && <ArticlesPage />}
      {activeTab === "customers" && <CustomersPage />}
      {activeTab === "transactions" && <TransactionsPage />}
    </div>
  );
}

export default App;
