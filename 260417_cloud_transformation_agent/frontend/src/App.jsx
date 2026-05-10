import { useState } from "react";

import DiscoverPage from "./pages/DiscoverPage";
import DeployPage from "./pages/DeployPage";
import HomePage from "./pages/HomePage";
import MigrationPage, { useAzureMapping } from "./pages/MigrationPage";

/* ── Migration steps definition ──────────────────────────────── */

const STEPS = [
  { key: "setup",    label: "Connect",  icon: "🔌", desc: "AWS · Azure 계정" },
  { key: "discover", label: "Discover", icon: "🔎", desc: "리소스 탐색 & 선택" },
  { key: "plan",     label: "Plan",     icon: "🧭", desc: "마이그레이션 계획" },
  { key: "deploy",   label: "Deploy",   icon: "🚀", desc: "배포 & 데이터 이전" },
];

/* ── Stepper bar component ────────────────────────────────────── */

function StepperBar({ current, completed, unlocked, onChange }) {
  return (
    <div style={{
      display: "flex", alignItems: "flex-end",
      padding: "0 32px",
      background: "var(--color-surface)",
      borderBottom: "1px solid var(--color-border)",
      gap: 0,
    }}>
      {STEPS.map((s, i) => {
        const isDone     = completed.has(s.key);
        const isActive   = i === current;
        const isUnlocked = unlocked.has(s.key);

        return (
          <div key={s.key} style={{ display: "flex", alignItems: "center", flex: i < STEPS.length - 1 ? 1 : "none" }}>

            {/* Step button */}
            <button
              type="button"
              onClick={() => isUnlocked && onChange(i)}
              disabled={!isUnlocked}
              style={{
                display: "flex", flexDirection: "column", alignItems: "center",
                gap: 6, padding: "16px 12px 14px",
                background: "none", border: "none",
                cursor: isUnlocked ? "pointer" : "not-allowed",
                position: "relative",
                opacity: isUnlocked ? 1 : 0.4,
              }}
            >
              {/* Active underline */}
              {isActive && (
                <div style={{
                  position: "absolute", bottom: 0, left: 8, right: 8, height: 2,
                  background: "var(--color-accent)", borderRadius: "2px 2px 0 0",
                }} />
              )}

              {/* Circle */}
              <div style={{
                width: 34, height: 34, borderRadius: "50%",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: isDone ? "0.85rem" : "1.05rem",
                background: isDone ? "#16a34a" : isActive ? "var(--color-accent)" : "transparent",
                color: isDone || isActive ? "#fff" : "var(--color-text-light)",
                border: (!isDone && !isActive) ? "2px solid var(--color-border)" : "none",
                transition: "all 0.2s",
                flexShrink: 0,
              }}>
                {isDone ? "✓" : s.icon}
              </div>

              {/* Label */}
              <div style={{ textAlign: "center" }}>
                <div style={{
                  fontSize: "0.8rem", fontWeight: isActive ? 700 : 500,
                  color: isDone ? "#16a34a" : isActive ? "var(--color-text)" : "var(--color-text-light)",
                  whiteSpace: "nowrap",
                }}>
                  {s.label}
                </div>
                <div style={{ fontSize: "0.68rem", color: "var(--color-text-light)", whiteSpace: "nowrap" }}>
                  {s.desc}
                </div>
              </div>
            </button>

            {/* Connector */}
            {i < STEPS.length - 1 && (
              <div style={{
                flex: 1, height: 2, marginBottom: 22,
                background: isDone ? "#16a34a" : "var(--color-border)",
                transition: "background 0.3s",
                minWidth: 24,
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function SessionScopeToolbar({ scope }) {
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        display: "flex",
        alignItems: "center",
        gap: 10,
        height: 36,
        padding: "0 12px",
        background: "var(--color-surface)",
        borderTop: "1px solid var(--color-border)",
        color: "var(--color-text)",
        fontSize: "0.72rem",
        zIndex: 10,
      }}
    >
      <span style={{ color: "var(--color-accent)", fontWeight: 600, whiteSpace: "nowrap" }}>
        ● 세션 활성
      </span>
      <span style={{ color: "var(--color-text-light)", flexShrink: 0 }}>AWS</span>
      <span style={{ fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {scope.aws_account_id} · {scope.aws_region}
      </span>
      <span style={{ color: "var(--color-accent)", flexShrink: 0 }} aria-hidden="true">-&gt;</span>
      <span style={{ color: "var(--color-text-light)", flexShrink: 0 }}>Azure</span>
      <span style={{ fontWeight: 500, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {scope.azure_subscription_name} · {scope.azure_region}
      </span>
    </div>
  );
}

/* ── Default values ───────────────────────────────────────────── */

const DEFAULT_AWS_SPEC = `Region: us-east-1
Services: Application Load Balancer, ECS Fargate services, RDS PostgreSQL, S3 buckets for static assets, ElastiCache Redis, Secrets Manager, CloudWatch.`;

const DEFAULT_GOALS =
  "가동 중단 시간 최소화; hub-spoke 네트워킹에 맞춤; 가능한 한 managed service 사용.";

/* ── App ──────────────────────────────────────────────────────── */

function App() {
  const [currentStep, setCurrentStep] = useState(0);

  // Phase 0 — credentials
  const [sessionId, setSessionId]       = useState(null);
  const [sessionScope, setSessionScope] = useState(null);

  // Phase 1 — discovery
  const [scopedRows, setScopedRows]     = useState([]);
  const [scopedMeta, setScopedMeta]     = useState(null);
  const [awsSpec, setAwsSpec]           = useState(DEFAULT_AWS_SPEC);
  const [architecture, setArchitecture] = useState(null);  // full Phase-1 graph for v2 pipeline

  // Phase 2 — plan
  const [azureRegion, setAzureRegion]     = useState("koreacentral");
  const [goals, setGoals]                 = useState(DEFAULT_GOALS);
  const [planCompleted, setPlanCompleted] = useState(false);
  const [discoveryDone, setDiscoveryDone] = useState(false);

  const mapping = useAzureMapping(
    scopedRows,
    azureRegion,
    scopedMeta?.region || "",
    sessionScope?.azure_subscription_id || "",
  );

  /* ── Step unlock / completion logic ── */
  const credReady = !!sessionId && !!sessionScope;
  // Deploy 는 디스크에 영속된 Plan output 만 있으면 가능 — 현 세션의 planCompleted
  // 와 무관. 백엔드 reload 후에도 sessionScope(React 상태)만 있으면 진입 가능.
  const scopeKnown = !!sessionScope?.azure_subscription_id;

  const completed = new Set([
    credReady     && "setup",
    discoveryDone && "discover",
    planCompleted && "plan",
  ].filter(Boolean));

  const unlocked = new Set([
    "setup",
    credReady                       && "discover",
    credReady && discoveryDone      && "plan",
    // Deploy: scope 만 알면 unlock — DeployPage 가 디스크의 plan 목록을 읽어 처리
    (credReady || scopeKnown)       && "deploy",
  ].filter(Boolean));

  /* ── Callbacks ── */

  const handleCredentialsReady = ({ sessionId: sid, scope }) => {
    setSessionId(sid);
    setSessionScope(scope);
    if (scope?.azure_region) setAzureRegion(scope.azure_region);
    // Auto-advance to Discover
    setCurrentStep(1);
  };

  const handleSendToMigration = ({ spec, goals: g, rows, region, resourceGroup, mode, architecture: arch }) => {
    if (spec) setAwsSpec(spec);
    if (g)    setGoals(g);
    setScopedRows(Array.isArray(rows) ? rows : []);
    setScopedMeta({ region, resourceGroup, mode });
    if (arch) setArchitecture(arch);  // Phase-1 graph passed to v2 pipeline
    setDiscoveryDone(true);
    // Auto-advance to Plan
    setCurrentStep(2);
  };

  const handlePlanCompleted = () => {
    setPlanCompleted(true);
  };

  return (
    <div className="app-layout">

      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="sidebar-brand-icon" aria-hidden="true">☁️</span>
          <div>
            <div className="sidebar-title-h1">Azure Solution Showcase</div>
            <div className="sidebar-subtitle">Migration Workspace</div>
          </div>
        </div>

        <div style={{ padding: "0 12px", flex: 1 }}>
          <button
            type="button"
            onClick={() => setCurrentStep(0)}
            className="sidebar-nav-item active"
            style={{ width: "100%" }}
          >
            <span className="sidebar-nav-icon" aria-hidden="true">🔌</span>
            <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
              <span className="sidebar-nav-label" style={{ fontWeight: 600 }}>Cloud Transformation</span>
              <span style={{ fontSize: "0.7rem", color: "var(--color-text-light)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                AWS -> Azure Migration
              </span>
            </span>
          </button>
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="main-content" style={{ display: "flex", flexDirection: "column", padding: 0, overflow: "hidden", position: "relative" }}>

        {/* Stepper bar */}
        <StepperBar
          current={currentStep}
          completed={completed}
          unlocked={unlocked}
          onChange={setCurrentStep}
        />

        {/* Step content */}
        <div style={{ flex: 1, overflowY: "auto", padding: credReady ? "24px 32px 64px" : "24px 32px" }}>
          {currentStep === 0 && (
            <HomePage
              sessionId={sessionId}
              setSessionId={setSessionId}
              onReady={handleCredentialsReady}
              onStart={() => setCurrentStep(1)}
            />
          )}
          {currentStep === 1 && (
            <DiscoverPage
              sessionId={sessionId}
              sessionScope={sessionScope}
              onSendToMigration={handleSendToMigration}
            />
          )}
          {currentStep === 2 && (
            <MigrationPage
              awsSpec={awsSpec}
              setAwsSpec={setAwsSpec}
              azureRegion={azureRegion}
              setAzureRegion={setAzureRegion}
              goals={goals}
              setGoals={setGoals}
              scopedRows={scopedRows}
              scopedMeta={scopedMeta}
              architecture={architecture}
              onGoToDiscover={() => setCurrentStep(1)}
              mapping={mapping}
              onPlanCompleted={handlePlanCompleted}
              targetSubscriptionId={sessionScope?.azure_subscription_id || ""}
            />
          )}
          {currentStep === 3 && (
            <DeployPage
              sessionId={sessionId}
              sessionScope={sessionScope}     /* fallback when backend session expired */
              onGoToPlan={() => setCurrentStep(2)}
              onGoToConnect={() => setCurrentStep(0)}
            />
          )}
        </div>

        {credReady && sessionScope && <SessionScopeToolbar scope={sessionScope} />}
      </main>

    </div>
  );
}

export default App;
