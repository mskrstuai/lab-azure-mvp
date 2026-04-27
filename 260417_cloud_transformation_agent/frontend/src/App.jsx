import { useState } from "react";

import AwsResourcesPage from "./pages/AwsResourcesPage";
import DeployPage from "./pages/DeployPage";
import HomePage from "./pages/HomePage";
import MigrationPage, { useAzureMapping } from "./pages/MigrationPage";

const TABS = [
  { key: "home", label: "Overview", icon: "☁️" },
  { key: "aws", label: "Discover & Select", icon: "🔎" },
  { key: "migration", label: "Plan", icon: "🧭" },
  { key: "deploy", label: "Deploy & Migrate", icon: "🚀" },
];

const DEFAULT_AWS_SPEC = `Region: us-east-1
Services: Application Load Balancer, ECS Fargate services, RDS PostgreSQL, S3 buckets for static assets, ElastiCache Redis, Secrets Manager, CloudWatch.

ARN·이름 예시를 여기 나열할 수 있습니다. ID가 가려져 있으면 플래너는 서비스 수준에서 추론합니다.`;

const DEFAULT_GOALS =
  "가동 중단 시간 최소화; hub-spoke 네트워킹에 맞춤; 가능한 한 managed service 사용.";

function App() {
  const [activeTab, setActiveTab] = useState("home");
  // Lifted so the Discover page can seed the Plan form.
  const [awsSpec, setAwsSpec] = useState(DEFAULT_AWS_SPEC);
  const [azureRegion, setAzureRegion] = useState("eastus");
  const [goals, setGoals] = useState(DEFAULT_GOALS);
  // Structured rows pushed from Discover & Select — shown as a compact
  // summary table on the Plan page.
  const [scopedRows, setScopedRows] = useState([]);
  const [scopedMeta, setScopedMeta] = useState(null);

  /** Lives in App so Mapping results survive tab switches (Plan ↔ other pages). */
  const mapping = useAzureMapping(
    scopedRows,
    azureRegion,
    scopedMeta?.region || "",
  );

  const handleSendToMigration = ({
    spec,
    goals: nextGoals,
    rows,
    region,
    resourceGroup,
    mode,
  }) => {
    if (spec) setAwsSpec(spec);
    if (nextGoals) setGoals(nextGoals);
    setScopedRows(Array.isArray(rows) ? rows : []);
    setScopedMeta({ region, resourceGroup, mode });
    setActiveTab("migration");
  };

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="sidebar-brand-icon" aria-hidden="true">☁️</span>
          <div>
            <div className="sidebar-title-h1">Cloud Transformation</div>
            <div className="sidebar-subtitle">
              AWS → Azure, Azure OpenAI 기반 마이그레이션 플래너
            </div>
          </div>
        </div>
        <nav className="sidebar-nav" aria-label="주요 메뉴">
          {TABS.map(({ key, label, icon }) => (
            <button
              key={key}
              type="button"
              className={`sidebar-nav-item ${activeTab === key ? "active" : ""}`}
              onClick={() => setActiveTab(key)}
              aria-current={activeTab === key ? "page" : undefined}
            >
              <span className="sidebar-nav-icon" aria-hidden="true">{icon}</span>
              <span className="sidebar-nav-label">{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span>v0.2</span>
        </div>
      </aside>

      <main className="main-content">
        {activeTab === "home" && <HomePage onStart={() => setActiveTab("aws")} />}
        {activeTab === "aws" && (
          <AwsResourcesPage onSendToMigration={handleSendToMigration} />
        )}
        {activeTab === "migration" && (
          <MigrationPage
            awsSpec={awsSpec}
            setAwsSpec={setAwsSpec}
            azureRegion={azureRegion}
            setAzureRegion={setAzureRegion}
            goals={goals}
            setGoals={setGoals}
            scopedRows={scopedRows}
            scopedMeta={scopedMeta}
            onGoToDiscover={() => setActiveTab("aws")}
            mapping={mapping}
          />
        )}
        {activeTab === "deploy" && (
          <DeployPage onGoToPlan={() => setActiveTab("migration")} />
        )}
      </main>
    </div>
  );
}

export default App;
