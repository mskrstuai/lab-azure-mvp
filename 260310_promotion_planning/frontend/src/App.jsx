import { useState } from "react";

import DashboardPage from "./pages/DashboardPage";
import PromotionsPage from "./pages/PromotionsPage";
import RunAnalysisPage from "./pages/RunAnalysisPage";

const TABS = {
  dashboard: { label: "Dashboard", icon: "📊" },
  promotions: { label: "Promotions", icon: "🏷️" },
  runAnalysis: { label: "Run Analysis", icon: "🔬" },
};

function App() {
  const [activeTab, setActiveTab] = useState("dashboard");

  return (
    <>
      <header className="app-header">
        <h1>Promotion Planning</h1>
        <p className="subtitle">Snacks & Beverage Promotions Analytics</p>
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
        {activeTab === "dashboard" && <DashboardPage />}
        {activeTab === "promotions" && <PromotionsPage />}
        {activeTab === "runAnalysis" && <RunAnalysisPage />}
      </main>
    </>
  );
}

export default App;
