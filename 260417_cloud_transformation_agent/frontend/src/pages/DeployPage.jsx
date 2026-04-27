import { useEffect, useMemo, useRef, useState } from "react";

import {
  fetchDeployPreflight,
  fetchDeployStatus,
  fetchMigrationOutput,
  fetchMigrationOutputs,
  startTerraformDeploy,
  terraformZipUrl,
} from "../api/apiClient";
import TerraformViewer from "../components/TerraformViewer";

/**
 * Deploy & Migrate page.
 *
 * Pick a previously-generated Terraform module → choose an Azure subscription
 * → press "Deploy". The backend runs `terraform init/plan/apply` against the
 * module and streams logs back to the browser. No more zip download dance.
 */
function DeployPage({ onGoToPlan }) {
  const [runs, setRuns] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [output, setOutput] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingOutput, setLoadingOutput] = useState(false);

  // Preflight (terraform + az status)
  const [preflight, setPreflight] = useState(null);
  const [loadingPreflight, setLoadingPreflight] = useState(true);
  const [subscriptionId, setSubscriptionId] = useState("");

  // Active deployment job
  const [deploy, setDeploy] = useState(null);
  const [deployLogs, setDeployLogs] = useState([]);
  const [deployError, setDeployError] = useState("");
  const [starting, setStarting] = useState(false);
  const logBoxRef = useRef(null);

  useEffect(() => {
    fetchMigrationOutputs()
      .then((res) => {
        const list = (res.runs || []).filter((r) => r.has_terraform);
        setRuns(list);
        if (list.length > 0) setSelectedId(list[0].run_id);
      })
      .catch(() => setRuns([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setOutput(null);
      return;
    }
    setLoadingOutput(true);
    fetchMigrationOutput(selectedId)
      .then(setOutput)
      .catch(() => setOutput(null))
      .finally(() => setLoadingOutput(false));
  }, [selectedId]);

  const refreshPreflight = () => {
    setLoadingPreflight(true);
    fetchDeployPreflight()
      .then((p) => {
        setPreflight(p);
        const def = p?.azure?.default_subscription_id;
        setSubscriptionId((cur) => cur || def || "");
      })
      .catch(() => setPreflight({ terraform: { installed: false }, azure: { installed: false } }))
      .finally(() => setLoadingPreflight(false));
  };

  useEffect(() => {
    refreshPreflight();
  }, []);

  // Poll the active deploy.
  useEffect(() => {
    if (!deploy?.deploy_id) return undefined;
    if (deploy.status === "succeeded" || deploy.status === "failed") return undefined;

    let cancelled = false;
    let offset = deployLogs.length;

    const tick = async () => {
      try {
        const next = await fetchDeployStatus(deploy.deploy_id, offset);
        if (cancelled) return;
        if (Array.isArray(next.log_lines) && next.log_lines.length > 0) {
          setDeployLogs((prev) => [...prev, ...next.log_lines]);
          offset = next.log_total ?? offset + next.log_lines.length;
        } else if (typeof next.log_total === "number") {
          offset = next.log_total;
        }
        setDeploy((cur) => (cur ? { ...cur, ...next, log_lines: undefined } : cur));
      } catch (err) {
        if (!cancelled) setDeployError(err.message || String(err));
      }
    };

    const interval = setInterval(tick, 1200);
    tick();
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deploy?.deploy_id, deploy?.status]);

  // Auto-scroll the log viewer.
  useEffect(() => {
    const el = logBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [deployLogs]);

  const tfFiles = useMemo(() => {
    const jd = output?.json_data;
    return Array.isArray(jd?.terraform) ? jd.terraform : [];
  }, [output]);

  const azure = preflight?.azure;
  const terraform = preflight?.terraform;
  const tfReady = !!terraform?.installed;
  const azReady = !!azure?.signed_in;
  const subs = azure?.subscriptions || [];

  const isRunning = deploy && (deploy.status === "pending" || deploy.status === "running");
  const canDeploy =
    !!selectedId && !!subscriptionId && tfReady && azReady && !isRunning && !starting;

  const handleStart = async (action) => {
    if (!selectedId || !subscriptionId) return;
    setStarting(true);
    setDeployError("");
    setDeployLogs([]);
    try {
      const res = await startTerraformDeploy(selectedId, {
        action,
        subscriptionId,
      });
      setDeploy({ ...res, current_step: "queued" });
    } catch (err) {
      setDeployError(err.message || String(err));
    } finally {
      setStarting(false);
    }
  };

  if (loading) {
    return (
      <section className="page-section">
        <h2 className="page-title">🚀 Deploy & Migrate</h2>
        <div className="loading">
          <div className="spinner" />
          <p>이전 Plan 결과를 불러오는 중…</p>
        </div>
      </section>
    );
  }

  if (runs.length === 0) {
    return (
      <section className="page-section">
        <h2 className="page-title">🚀 Deploy & Migrate</h2>
        <p className="page-desc">
          Planner가 만든 Azure Terraform 모듈을 이 화면에서 바로 적용할 수 있습니다.
        </p>
        <div className="empty-state">
          <div className="icon">📦</div>
          <p>Terraform 모듈이 아직 없습니다.</p>
          <p className="hint">
            먼저 <strong>Plan</strong>을 실행해 Terraform을 생성한 뒤 이 탭에서 배포하세요.
          </p>
          {onGoToPlan && (
            <button
              type="button"
              className="run-btn"
              style={{ marginTop: 16 }}
              onClick={onGoToPlan}
            >
              🧭 Go to Plan
            </button>
          )}
        </div>
      </section>
    );
  }

  const stepBadge = deploy?.current_step ? (
    <span
      className="badge"
      style={{ background: "var(--color-accent)", color: "#0d1117" }}
    >
      {deploy.current_step}
    </span>
  ) : null;

  const statusColor =
    deploy?.status === "succeeded"
      ? "#22c55e"
      : deploy?.status === "failed"
      ? "#ef4444"
      : deploy?.status === "running" || deploy?.status === "pending"
      ? "var(--color-accent)"
      : "var(--color-text-light)";

  return (
    <section className="page-section">
      <h2 className="page-title">🚀 Deploy & Migrate</h2>
      <p className="page-desc">
        Planner가 생성한 Terraform 모듈을 고르고 Azure subscription을 선택한 뒤 이
        화면에서 바로 적용하세요. 백엔드가 <code>terraform init / plan / apply</code>를
        대신 실행하고 아래에 로그를 스트리밍합니다.
      </p>

      <div className="outputs-panel">
        <div className="outputs-sidebar">
          <h3 className="sidebar-title">
            Terraform-ready runs ({runs.length})
          </h3>
          <div className="run-list">
            {runs.map((r) => (
              <button
                key={r.run_id}
                type="button"
                className={`run-card ${selectedId === r.run_id ? "active" : ""}`}
                onClick={() => setSelectedId(r.run_id)}
                disabled={isRunning}
              >
                <span className="run-id">{r.run_id}</span>
                <span className="run-badges">
                  <span
                    className="badge"
                    style={{ background: "var(--color-accent)", color: "#0d1117" }}
                  >
                    {r.terraform_file_count || 0} TF
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="outputs-content">
          {loadingOutput && (
            <div className="loading">
              <div className="spinner" />
              <p>모듈을 불러오는 중…</p>
            </div>
          )}

          {!loadingOutput && selectedId && (
            <>
              {/* Deploy panel ------------------------------------------- */}
              <div
                className="result-section"
                style={{
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-md, 8px)",
                  padding: 16,
                  background: "var(--color-surface)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    flexWrap: "wrap",
                    gap: 12,
                    marginBottom: 12,
                  }}
                >
                  <h3 className="result-section-title" style={{ margin: 0 }}>
                    ⚙️ Deploy to Azure
                  </h3>
                  <button
                    type="button"
                    className="tab"
                    onClick={refreshPreflight}
                    disabled={loadingPreflight}
                    style={{ padding: "6px 10px", fontSize: "0.78rem" }}
                  >
                    {loadingPreflight ? "Checking..." : "↻ Refresh status"}
                  </button>
                </div>

                {/* Preflight banner */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 8,
                    marginBottom: 12,
                  }}
                >
                  <PreflightTile
                    label="Terraform"
                    ok={tfReady}
                    detail={
                      tfReady
                        ? `백엔드에 terraform v${terraform?.version || "?"}`
                        : terraform?.error || "백엔드에 terraform 미탐지"
                    }
                  />
                  <PreflightTile
                    label="Azure CLI"
                    ok={azReady}
                    detail={
                      azReady
                        ? `구독 ${subs.length}개 표시됨`
                        : azure?.installed
                        ? "백엔드에서 az login 필요"
                        : "백엔드에 Azure CLI 미탐지"
                    }
                  />
                </div>

                {/* Subscription chooser */}
                <div style={{ marginBottom: 12 }}>
                  <label
                    htmlFor="azure-sub"
                    style={{
                      display: "block",
                      fontSize: "0.8rem",
                      color: "var(--color-text-light)",
                      marginBottom: 4,
                    }}
                  >
                    Target Azure subscription
                  </label>
                  {subs.length > 0 ? (
                    <select
                      id="azure-sub"
                      value={subscriptionId}
                      onChange={(e) => setSubscriptionId(e.target.value)}
                      disabled={isRunning}
                      style={{
                        width: "100%",
                        padding: "8px 10px",
                        fontSize: "0.85rem",
                        background: "var(--color-bg)",
                        color: "var(--color-text)",
                        border: "1px solid var(--color-border)",
                        borderRadius: "var(--radius-sm, 4px)",
                      }}
                    >
                      <option value="">— select a subscription —</option>
                      {subs.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name} {s.isDefault ? "(default)" : ""} — {s.id}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id="azure-sub"
                      type="text"
                      value={subscriptionId}
                      onChange={(e) => setSubscriptionId(e.target.value)}
                      placeholder="00000000-0000-0000-0000-000000000000"
                      disabled={isRunning}
                      style={{
                        width: "100%",
                        padding: "8px 10px",
                        fontSize: "0.85rem",
                        background: "var(--color-bg)",
                        color: "var(--color-text)",
                        border: "1px solid var(--color-border)",
                        borderRadius: "var(--radius-sm, 4px)",
                        fontFamily: "monospace",
                      }}
                    />
                  )}
                </div>

                {/* Action buttons */}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  <button
                    type="button"
                    className="run-btn"
                    onClick={() => handleStart("apply")}
                    disabled={!canDeploy}
                    title={
                      !tfReady
                        ? "백엔드 호스트에 terraform 설치"
                        : !azReady
                        ? "백엔드 호스트에서 az login"
                        : !subscriptionId
                        ? "구독을 선택하세요"
                        : "terraform init → plan → apply 실행"
                    }
                    style={{ padding: "10px 18px" }}
                  >
                    {isRunning && deploy?.action === "apply"
                      ? "🚀 Applying..."
                      : "🚀 Deploy to Azure"}
                  </button>
                  <button
                    type="button"
                    className="tab"
                    onClick={() => {
                      if (
                        window.confirm(
                          "이 모듈이 만든 모든 리소스를 제거하기 위해 `terraform destroy`를 실행합니다. 계속할까요?",
                        )
                      ) {
                        handleStart("destroy");
                      }
                    }}
                    disabled={!canDeploy}
                    style={{ padding: "10px 18px", fontSize: "0.85rem" }}
                  >
                    {isRunning && deploy?.action === "destroy"
                      ? "💥 Destroying..."
                      : "💥 Destroy"}
                  </button>
                </div>

                {deployError && (
                  <div
                    style={{
                      marginTop: 10,
                      padding: 10,
                      borderRadius: "var(--radius-sm, 4px)",
                      background: "rgba(239,68,68,0.1)",
                      color: "#ef4444",
                      fontSize: "0.8rem",
                    }}
                  >
                    {deployError}
                  </div>
                )}

                {/* Live log + status */}
                {deploy && (
                  <div style={{ marginTop: 14 }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 8,
                        marginBottom: 6,
                        flexWrap: "wrap",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span
                          style={{
                            display: "inline-block",
                            width: 10,
                            height: 10,
                            borderRadius: "50%",
                            background: statusColor,
                          }}
                        />
                        <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>
                          {deploy.action} · {deploy.status}
                        </span>
                        {stepBadge}
                      </div>
                      <span
                        style={{ fontSize: "0.72rem", color: "var(--color-text-light)" }}
                      >
                        deploy_id: {deploy.deploy_id?.slice(0, 8)}…
                      </span>
                    </div>
                    <pre
                      ref={logBoxRef}
                      style={{
                        background: "#0d1117",
                        color: "#d1d5db",
                        border: "1px solid var(--color-border)",
                        borderRadius: "var(--radius-sm, 4px)",
                        padding: 12,
                        fontSize: "0.74rem",
                        lineHeight: 1.5,
                        overflow: "auto",
                        margin: 0,
                        maxHeight: 380,
                        minHeight: 160,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                      }}
                    >
                      {deployLogs.length === 0
                        ? "출력 대기 중…"
                        : deployLogs.join("\n")}
                    </pre>
                  </div>
                )}

                <details style={{ marginTop: 12 }}>
                  <summary
                    style={{
                      cursor: "pointer",
                      fontSize: "0.78rem",
                      color: "var(--color-text-light)",
                    }}
                  >
                    ▸ Terraform을 직접 실행하려면
                  </summary>
                  <div style={{ marginTop: 8, fontSize: "0.78rem" }}>
                    모듈을 받아 로컬에서 적용:{" "}
                    <a
                      href={terraformZipUrl(selectedId)}
                      style={{ color: "var(--color-accent)" }}
                    >
                      ⬇ azure-terraform-{selectedId}.zip
                    </a>
                  </div>
                </details>
              </div>

              {/* Terraform file viewer (preview only — no built-in apply guide) */}
              {tfFiles.length > 0 ? (
                <TerraformViewer files={tfFiles} runId={selectedId} compact />
              ) : (
                <div className="empty-state" style={{ padding: 28 }}>
                  <div className="icon">🗂</div>
                  <p>이 실행에 Terraform 파일이 없습니다.</p>
                  <p className="hint">
                    Terraform 자동 생성 이전에 저장된 구 결과일 수 있습니다.
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function PreflightTile({ label, ok, detail }) {
  return (
    <div
      style={{
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-sm, 4px)",
        padding: "8px 10px",
        background: "var(--color-bg)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            display: "inline-block",
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: ok ? "#22c55e" : "#ef4444",
          }}
        />
        <strong style={{ fontSize: "0.82rem" }}>{label}</strong>
        <span
          style={{
            fontSize: "0.7rem",
            color: ok ? "#22c55e" : "#ef4444",
            marginLeft: "auto",
          }}
        >
          {ok ? "가능" : "차단"}
        </span>
      </div>
      <div style={{ fontSize: "0.72rem", color: "var(--color-text-light)", marginTop: 2 }}>
        {detail}
      </div>
    </div>
  );
}

export default DeployPage;
