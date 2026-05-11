import { useEffect, useRef, useState } from "react";

import DiscoverPage from "./pages/DiscoverPage";
import DeployPage from "./pages/DeployPage";
import HomePage from "./pages/HomePage";
import MigrationPage, { useAzureMapping } from "./pages/MigrationPage";
import { listActiveSessions, fetchSettingsEnv, saveSettingsEnv, createSelectedPlan, updateSelectedPlan } from "./api/apiClient";

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
                {/* Only the Connect step swaps to ✓ when done — others
                    keep their original icon. */}
                {isDone && s.key === "setup" ? "✓" : s.icon}
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

function SettingsPage() {
  return (
    <section className="page-section">
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: "0 0 4px", fontSize: "1.2rem", fontWeight: 700 }}>⚙️ Settings</h2>
        <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--color-text-light)" }}>
        </p>
      </div>
      <SettingsEnvPanel />
    </section>
  );
}

function SettingsEnvPanel() {
  const [env, setEnv]         = useState(null);
  const [draft, setDraft]     = useState({});       // local edits
  const [showSecret, setShow] = useState({});       // per-key reveal toggle
  const [error, setError]     = useState(null);
  const [busy, setBusy]       = useState(false);
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => {
    fetchSettingsEnv()
      .then(d => { setEnv(d); setDraft({ ...d.values }); })
      .catch((e) => setError(e.message || String(e)));
  }, []);

  if (error) return <div className="form-error">{error}</div>;
  if (!env)  return <div style={{ fontSize: "0.8rem", color: "var(--color-text-light)" }}>
    <span className="spinner" /> 로드 중…
  </div>;

  const secretKeys = new Set(env.secret_keys || []);
  const dirty = (env.keys || []).some(k => (draft[k] || "") !== (env.values[k] || ""));

  const onSave = async () => {
    setBusy(true); setError(null);
    try {
      const updated = await saveSettingsEnv(draft);
      setEnv(prev => ({ ...prev, values: updated.values }));
      setDraft({ ...updated.values });
      setSavedAt(new Date());
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const onReset = () => {
    setDraft({ ...env.values });
    setError(null);
  };

  return (
    <div style={{
      padding: "14px 18px",
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: "var(--radius-sm)",
    }}>
      <div style={{ fontSize: "0.85rem", fontWeight: 700, marginBottom: 4 }}>환경 설정</div>

      <table style={{ width: "100%", fontSize: "0.82rem", borderCollapse: "collapse" }}>
        <tbody>
          {(env.keys || []).map(k => {
            const isSecret = secretKeys.has(k);
            const reveal  = !!showSecret[k];
            return (
              <tr key={k} style={{ borderBottom: "1px solid var(--color-border)" }}>
                <td style={{
                  padding: "8px 8px", color: "var(--color-text-light)",
                  fontFamily: "monospace", whiteSpace: "nowrap",
                  width: 260, verticalAlign: "middle",
                }}>
                  {k}{isSecret && <span style={{ marginLeft: 6, color: "#d97706" }}>🔒</span>}
                </td>
                <td style={{ padding: "6px 8px" }}>
                  <div style={{ display: "flex", gap: 6 }}>
                    <input
                      type={isSecret && !reveal ? "password" : "text"}
                      value={draft[k] || ""}
                      onChange={e => setDraft(d => ({ ...d, [k]: e.target.value }))}
                      placeholder="(미설정)"
                      autoComplete="off"
                      spellCheck={false}
                      style={{
                        flex: 1, minWidth: 0,
                        padding: "5px 8px",
                        background: "var(--color-bg)",
                        border: "1px solid var(--color-border)",
                        borderRadius: "var(--radius-sm)",
                        color: "var(--color-text)",
                        fontFamily: "monospace", fontSize: "0.8rem",
                      }}
                    />
                    {isSecret && (
                      <button type="button"
                        onClick={() => setShow(s => ({ ...s, [k]: !s[k] }))}
                        title={reveal ? "숨김" : "표시"}
                        style={{
                          background: "none", border: "1px solid var(--color-border)",
                          color: "var(--color-text-light)", borderRadius: "var(--radius-sm)",
                          padding: "0 10px", fontSize: "0.78rem", cursor: "pointer",
                          minWidth: 38,
                        }}>
                        {reveal ? "🙈" : "👁"}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center" }}>
        <button type="button" onClick={onSave} disabled={busy || !dirty}
          className="run-btn action-btn"
          style={{ minHeight: 32, padding: "0 18px", fontSize: "0.85rem" }}>
          {busy ? <><span className="spinner" />저장 중…</> : "💾 저장"}
        </button>
        <button type="button" onClick={onReset} disabled={busy || !dirty}
          className="tab action-btn action-btn--secondary"
          style={{ minHeight: 32, padding: "0 14px", fontSize: "0.82rem" }}>
          되돌리기
        </button>
        {savedAt && !dirty && (
          <span style={{ fontSize: "0.78rem", color: "#16a34a" }}>
            ✓ 저장됨 ({savedAt.toLocaleTimeString()})
          </span>
        )}
        {dirty && (
          <span style={{ fontSize: "0.78rem", color: "#d97706" }}>
            • 변경 사항 있음
          </span>
        )}
      </div>
    </div>
  );
}


function SessionScopeToolbar({ scope, awsLive, azureLive, onReconnect }) {
  const liveColor   = "var(--color-accent)";
  const staleColor  = "#d97706";
  const dimColor    = "var(--color-text-light)";
  const hasScope = !!scope;
  const allLive  = awsLive && azureLive;
  const stale    = hasScope && !allLive;

  return (
    <div
      style={{
        position: "absolute",
        left: 0, right: 0, bottom: 0,
        display: "flex", alignItems: "center",
        gap: 10, height: 36,
        padding: "0 16px",
        background: "var(--color-surface)",
        borderTop: "1px solid var(--color-border)",
        color: "var(--color-text)",
        fontSize: "0.72rem",
        zIndex: 10,
        width: "100%",
        boxSizing: "border-box",
      }}
    >
      <span style={{
        color: !hasScope ? dimColor : allLive ? liveColor : staleColor,
        fontWeight: 600, whiteSpace: "nowrap",
      }}>
        {!hasScope ? "○ 미연결" : allLive ? "● 세션 활성" : "◌ 세션 stale"}
      </span>

      <span style={{ color: dimColor, flexShrink: 0 }}>AWS</span>
      {hasScope ? (
        <span style={{
          fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          opacity: awsLive ? 1 : 0.7,
        }}>
          {scope.aws_account_id} · {scope.aws_region}
          {!awsLive && <span style={{ color: staleColor, marginLeft: 4 }}>(재연결)</span>}
        </span>
      ) : (
        <span style={{ color: dimColor }}>—</span>
      )}

      <span style={{ color: dimColor, flexShrink: 0 }} aria-hidden="true">→</span>

      <span style={{ color: dimColor, flexShrink: 0 }}>Azure</span>
      {hasScope ? (
        <span style={{
          fontWeight: 500, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          opacity: azureLive ? 1 : 0.7,
        }}>
          {scope.azure_subscription_name} · {scope.azure_region}
          {!azureLive && <span style={{ color: staleColor, marginLeft: 4 }}>(재연결)</span>}
        </span>
      ) : (
        <span style={{ color: dimColor }}>—</span>
      )}

      <div style={{ flex: 1 }} />
      {(stale || !hasScope) && onReconnect && (
        <button type="button" onClick={onReconnect}
          style={{
            background: "none",
            border: `1px solid ${stale ? staleColor : "var(--color-border)"}`,
            color: stale ? staleColor : "var(--color-text-light)",
            borderRadius: "var(--radius-sm)",
            padding: "3px 12px", fontSize: "0.72rem", cursor: "pointer",
          }}>
          🔌 Connect
        </button>
      )}
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

  const [showSettings, setShowSettings] = useState(false);

  // Resizable sidebar — width persisted across reloads.
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const v = parseInt(localStorage.getItem("sidebarWidth") || "232", 10);
    return Number.isFinite(v) ? Math.max(56, Math.min(360, v)) : 232;
  });
  useEffect(() => {
    localStorage.setItem("sidebarWidth", String(sidebarWidth));
  }, [sidebarWidth]);
  const sidebarCollapsed = sidebarWidth < 110;
  const startSidebarDrag = (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = sidebarWidth;
    const onMove = (ev) => {
      const next = Math.max(56, Math.min(360, startW + (ev.clientX - startX)));
      setSidebarWidth(next);
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
    };
    document.body.style.cursor = "col-resize";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  // Phase 0 — credentials
  const [sessionId, setSessionId]       = useState(null);
  const [sessionScope, setSessionScope] = useState(null);
  // Live status for the bottom bar (kept in sync with backend periodically).
  const [awsLive, setAwsLive]     = useState(false);
  const [azureLive, setAzureLive] = useState(false);

  // On mount: ask the backend if there are persisted sessions; if so,
  // restore them into local state and skip Connect when scope is known.
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const { sessions = [] } = await listActiveSessions();
        if (cancelled) return;
        // Pick the most recently updated session (sessions list comes pre-sorted)
        const s = sessions[0];
        if (s) {
          setSessionId(prev => prev || s.session_id);
          if (s.scope) setSessionScope(prev => prev || s.scope);
          setAwsLive(!!s.aws_live);
          setAzureLive(!!s.azure_live);
        } else {
          setAwsLive(false);
          setAzureLive(false);
        }
      } catch {
        /* backend unreachable — leave whatever we already had */
      }
    };
    refresh();
    const id = setInterval(refresh, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Auto-skip Connect (step 0) when a complete scope is already known
  // — runs once after restore.
  const [didAutoSkip, setDidAutoSkip] = useState(false);
  useEffect(() => {
    if (!didAutoSkip && currentStep === 0 && sessionScope?.azure_subscription_id) {
      setDidAutoSkip(true);
      setCurrentStep(1);    // jump to Discovery
    }
  }, [didAutoSkip, currentStep, sessionScope]);

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
  // DB id of the selected_plan row created at the most recent Discover→Plan
  // handoff — used to override its status in the Plan list view while
  // mapping is in flight.
  const [currentPlanId, setCurrentPlanId] = useState(null);

  // One-shot seed used to restore mapping state when the user opens a saved
  // plan from the Plan list — populated *before* the scopedRows update so the
  // hook's reset effect picks it up on the same render cycle.
  const seedMappingsRef = useRef(null);
  // Flag set by MigrationPage when opening a saved plan whose DB status is
  // "mapping" — App.jsx watches this and auto-calls mapping.run() once the
  // hydrated rows are visible to the hook.  This is what lets a refresh
  // mid-mapping pick the work back up on its own.
  const shouldAutoResumeRef = useRef(false);
  const mapping = useAzureMapping(
    scopedRows,
    azureRegion,
    scopedMeta?.region || "",
    sessionScope?.azure_subscription_id || "",
    seedMappingsRef,
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

  // Once Connect is done (live session OR previously-known scope), unlock
  // every later step.  Plan / Deploy each render their own list of past
  // artifacts so the user doesn't strictly need to "complete" earlier steps
  // in this session before navigating around.
  const ready = credReady || scopeKnown;
  const unlocked = new Set([
    "setup",
    ready && "discover",
    ready && "plan",
    ready && "deploy",
  ].filter(Boolean));

  /* ── Callbacks ── */

  const handleCredentialsReady = ({ sessionId: sid, scope }) => {
    setSessionId(sid);
    setSessionScope(scope);
    if (scope?.azure_region) setAzureRegion(scope.azure_region);
    // Auto-advance to Discover
    setCurrentStep(1);
  };

  // Friendly random Plan id used for the popup notice when Discovery hands
  // off a selection.  The actual server-side id (uuid) lives in the
  // selected_plans DB row created by MigrationPage on scopedRows change.
  const _randomPlanName = () => {
    const adj  = ["nimble", "violet", "swift", "calm", "amber", "midnight", "lucid", "brave", "cosmic", "arctic"];
    const noun = ["otter", "sparrow", "yak", "comet", "harbor", "fjord", "willow", "delta", "ember", "echo"];
    const pick = a => a[Math.floor(Math.random() * a.length)];
    return `${pick(adj)}-${pick(noun)}-${Math.floor(Math.random() * 9000 + 1000)}`;
  };
  const [planNotice, setPlanNotice] = useState(null);

  const handleSendToMigration = async ({ spec, goals: g, rows, region, resourceGroup, mode, architecture: arch }) => {
    if (spec) setAwsSpec(spec);
    if (g)    setGoals(g);
    const rowsArr = Array.isArray(rows) ? rows : [];
    setScopedRows(rowsArr);
    setScopedMeta({ region, resourceGroup, mode });
    if (arch) setArchitecture(arch);  // Phase-1 graph passed to v2 pipeline
    setDiscoveryDone(true);
    const name = _randomPlanName();
    setPlanNotice({ name, count: rowsArr.length, mode });
    // Persist as a Selected plan in the DB *now* (the only handoff point).
    // Doing this here — rather than inside MigrationPage on scopedRows
    // change — prevents duplicate plans being created every time the user
    // navigates back to the Plan tab.
    try {
      const created = await createSelectedPlan({
        name,
        scoped_meta:  { account_id: arch?.account_id || "", region, resourceGroup, mode },
        scoped_rows:  rowsArr,
        architecture: arch || null,
        azure_region: azureRegion,
        goals:        g,
      });
      setCurrentPlanId(created?.plan?.id || created?.id || null);
    } catch { /* swallow — Plan page will still show in-progress row */ }
    // Auto-advance to Plan
    setCurrentStep(2);
  };

  const handlePlanCompleted = () => {
    setPlanCompleted(true);
  };

  // Persist mappings to the backend selected_plans row as soon as the
  // in-session mapping pass completes — otherwise a browser refresh would
  // wipe everything the user just computed.  Backend auto-promotes status
  // to 'mapped' when mappings are non-empty.
  useEffect(() => {
    if (!currentPlanId) return;
    if (!mapping?.mappingComplete) return;
    const m = mapping?.mappings || [];
    if (!m.length) return;
    updateSelectedPlan(currentPlanId, { mappings: m }).catch(() => {});
  }, [currentPlanId, mapping?.mappingComplete, mapping?.mappings]);

  // Reflect the in-session mapping phase into the DB row status so the Plan
  // list view shows "🔁 Mapping" / "🟢 Mapped" / "🟡 Selected" correctly even
  // after a browser refresh.  Use a ref to dedupe so we only PATCH on real
  // transitions.
  const lastStatusWrittenRef = useRef(null);
  useEffect(() => {
    if (!currentPlanId) return;
    const phase = mapping?.phase;
    const mCount = (mapping?.mappings || []).length;
    let nextStatus = null;
    if (phase === "running")       nextStatus = "mapping";
    else if (phase === "complete") nextStatus = "mapped";
    else if (phase === "paused" && mCount > 0) nextStatus = "mapped";
    // 'idle' or 'paused with 0 mappings' = no actionable signal — leave the
    // DB status alone.  Otherwise refresh would downgrade a 'mapping' status
    // back to 'selected' before the user gets a chance to resume.
    if (!nextStatus) return;
    const key = `${currentPlanId}:${nextStatus}`;
    if (lastStatusWrittenRef.current === key) return;
    lastStatusWrittenRef.current = key;
    updateSelectedPlan(currentPlanId, { status: nextStatus }).catch(() => {});
  }, [currentPlanId, mapping?.phase, mapping?.mappings]);

  // When the active plan changes (e.g. switching from one saved plan to
  // another, or after refresh), reset the status-dedupe ref so the new
  // plan's first transition fires.
  useEffect(() => { lastStatusWrittenRef.current = null; }, [currentPlanId]);

  // Auto-resume mapping when a plan with status="mapping" was just opened.
  // The flag is set in MigrationPage.onOpenSaved, then this effect waits
  // until the rows are actually visible to the hook (so run() doesn't no-op
  // on empty rows) and the hook isn't already running.
  useEffect(() => {
    if (!shouldAutoResumeRef.current) return;
    if (!scopedRows.length) return;
    if (mapping.phase === "running") return;
    if (mapping.mappingComplete) {
      shouldAutoResumeRef.current = false;
      return;
    }
    shouldAutoResumeRef.current = false;
    mapping.run().catch(() => {});
  }, [scopedRows, mapping.phase, mapping.mappingComplete, mapping.run]);

  return (
    <div className="app-layout">

      {/* ── Sidebar ── */}
      <aside
        className={`sidebar${sidebarCollapsed ? " collapsed" : ""}`}
        style={{ width: sidebarWidth, position: "relative" }}
      >
        <div className="sidebar-brand" title="Azure Solution Showcase">
          <span className="sidebar-brand-icon" aria-hidden="true">☁️</span>
          <div>
            <div className="sidebar-title-h1">Azure Solution Showcase</div>
            <div className="sidebar-subtitle">Solution MVP Workspace</div>
          </div>
        </div>

        <div style={{ padding: 0, flex: 1, display: "flex", flexDirection: "column", gap: 2 }}>
          <button
            type="button"
            onClick={() => { setCurrentStep(0); setShowSettings(false); }}
            className={`sidebar-nav-item ${!showSettings ? "active" : ""}`}
            title="Cloud Transformation — AWS → Azure Migration"
            style={{ width: "100%" }}
          >
            <span className="sidebar-nav-icon" aria-hidden="true">🚀</span>
            {!sidebarCollapsed && (
              <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <span className="sidebar-nav-label" style={{ fontWeight: 600 }}>Cloud Transformation</span>
                <span style={{ fontSize: "0.7rem", color: "var(--color-text-light)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  AWS → Azure Migration
                </span>
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setShowSettings(true)}
            className={`sidebar-nav-item ${showSettings ? "active" : ""}`}
            title="Settings"
            style={{ width: "100%" }}
          >
            <span className="sidebar-nav-icon" aria-hidden="true">⚙️</span>
            {!sidebarCollapsed && (
              <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <span className="sidebar-nav-label" style={{ fontWeight: 600 }}>Settings</span>
                <span style={{ fontSize: "0.7rem", color: "var(--color-text-light)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  세션 / 환경 설정
                </span>
              </span>
            )}
          </button>
        </div>

        {/* Drag handle on right edge — drag to resize, drop below 110px to collapse */}
        <div
          className="sidebar-resize-handle"
          onMouseDown={startSidebarDrag}
          title="드래그해서 사이드바 너비 조절 (좁으면 아이콘만 표시)"
        />
      </aside>

      {/* ── Main ── */}
      <main className="main-content" style={{ display: "flex", flexDirection: "column", padding: 0, overflow: "hidden", position: "relative" }}>

        {/* Stepper bar */}
        {!showSettings && (
          <StepperBar
            current={currentStep}
            completed={completed}
            unlocked={unlocked}
            onChange={setCurrentStep}
          />
        )}

        {/* Step content */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px 64px" }}>
          {showSettings ? (
            <SettingsPage />
          ) : (<>
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
              currentPlanId={currentPlanId}
              setScopedRows={setScopedRows}
              setScopedMeta={setScopedMeta}
              setArchitecture={setArchitecture}
              setCurrentPlanId={setCurrentPlanId}
              seedMappingsRef={seedMappingsRef}
              shouldAutoResumeRef={shouldAutoResumeRef}
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
          </>)}
        </div>

        <SessionScopeToolbar
          scope={sessionScope}
          awsLive={awsLive}
          azureLive={azureLive}
          onReconnect={() => setCurrentStep(0)}
        />

        {planNotice && (
          <div onClick={() => setPlanNotice(null)} style={{
            position: "fixed", inset: 0, zIndex: 1100,
            background: "rgba(0,0,0,0.55)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: 20,
          }}>
            <div onClick={e => e.stopPropagation()} style={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-md, 10px)",
              width: "min(440px, 100%)",
              boxShadow: "0 16px 48px rgba(0,0,0,0.45)",
              overflow: "hidden",
            }}>
              <div style={{
                padding: "12px 18px", fontWeight: 700, fontSize: "0.95rem",
                background: "var(--color-bg)",
                borderBottom: "1px solid var(--color-border)",
              }}>
                ✓ Plan 이 만들어졌습니다
              </div>
              <div style={{ padding: "16px 18px", fontSize: "0.85rem", lineHeight: 1.6 }}>
                <code style={{ fontSize: "0.95rem", color: "var(--color-accent)" }}>{planNotice.name}</code>
                <div style={{ marginTop: 6, color: "var(--color-text-light)" }}>
                  · 리소스 {planNotice.count}개 ({planNotice.mode})<br/>
                  · Plan 페이지의 Plan 목록에서 확인하세요.
                </div>
              </div>
              <div style={{
                display: "flex", justifyContent: "flex-end", gap: 8,
                padding: "12px 18px",
                borderTop: "1px solid var(--color-border)",
                background: "var(--color-bg)",
              }}>
                <button type="button" onClick={() => setPlanNotice(null)}
                  className="run-btn action-btn"
                  style={{ minHeight: 32, padding: "0 18px" }}>
                  확인
                </button>
              </div>
            </div>
          </div>
        )}
      </main>

    </div>
  );
}

export default App;
