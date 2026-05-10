import { useEffect, useMemo, useRef, useState } from "react";
import {
  abandonDeploy,
  applyFix,
  approveDeployV2Plan,
  cancelDeployV2,
  checkDeployScope,
  completeDataMigrationStep,
  destroyAndRestart,
  execInDeployWorkdir,
  fetchMigrationOutput,
  fetchMigrationOutputs,
  getDeployV2Status,
  getRunVariables,
  listAllDeploys,
  listDeployFiles,
  listDeploysForRun,
  requestAiFix,
  retryDeployApply,
  skipDataMigration,
  startDeployV2,
} from "../api/apiClient";

/* ── Phase metadata ────────────────────────────────────────── */

const PHASES = [
  { id: "preflight",      label: "1. 배포 사전 점검", icon: "🔍" },
  { id: "plan_running",   label: "1. 배포 사전 점검", icon: "📋" },
  { id: "plan_ready",     label: "1. 배포 사전 점검", icon: "📋" },
  { id: "apply_running",  label: "2. 리소스 배포",     icon: "🚀" },
  { id: "applied",        label: "2. 리소스 배포",     icon: "🚀" },
  { id: "validating",     label: "3. 배포 검증",       icon: "✓" },
  { id: "data_migration", label: "4. 데이터 이전",     icon: "📦" },
  { id: "complete",       label: "✓ 완료",            icon: "🎉" },
  { id: "failed",         label: "✗ 실패",            icon: "❌" },
  { id: "cancelled",      label: "✗ 취소됨",          icon: "⊘" },
];

const DISPLAY_PHASES = [
  { id: "preflight",      label: "배포 사전 점검", matchPhases: ["preflight", "plan_running", "plan_ready"] },
  { id: "apply",          label: "리소스 배포",    matchPhases: ["apply_running", "applied"] },
  { id: "validating",     label: "배포 검증" },
  { id: "data_migration", label: "데이터 이전" },
];

function _activeStepIndex(phase) {
  if (phase === "preflight" || phase === "plan_running" || phase === "plan_ready") return 0;
  if (phase === "apply_running" || phase === "applied" || phase === "apply_failed" || phase === "auto_fixing") return 1;
  if (phase === "validating") return 2;
  if (phase === "data_migration") return 3;
  if (phase === "complete") return 4;
  return -1;
}

const FAILED_PHASES = new Set(["failed", "cancelled", "apply_failed"]);

/* ── Phase stepper (continuous chevron ribbon) ───────────── */

// Wider gradient (lighter top-left, much darker bottom-right) gives each
// chevron its own shape even when adjacent segments share a state.
const STEPPER_COLORS = {
  failed:  { from: "#ef4444", to: "#991b1b", fg: "#fff" },
  done:    { from: "#22c55e", to: "#15803d", fg: "#fff" },
  active:  { from: "#3b82f6", to: "#1d4ed8", fg: "#fff" },
  pending: { from: "#374151", to: "#111827", fg: "#94a3b8" },
};

function PhaseStepper({ phase }) {
  const active = _activeStepIndex(phase);
  const failed = FAILED_PHASES.has(phase);
  const HEIGHT = 46;
  const ARROW  = 16;

  return (
    <div style={{
      display: "flex", alignItems: "stretch",
      marginBottom: 16,
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--color-border)",
      overflow: "hidden",
      height: HEIGHT,
      boxShadow: "0 1px 2px rgba(0,0,0,0.18)",
    }}>
      {DISPLAY_PHASES.map((p, i) => {
        const isDone   = active > i || phase === "complete";
        const isActive = active === i && !failed;
        const isFailed = failed && i === Math.max(0, active);
        const isLast   = i === DISPLAY_PHASES.length - 1;

        let key, marker;
        if (isFailed)      { key = "failed";  marker = "✗"; }
        else if (isDone)   { key = "done";    marker = "✓"; }
        else if (isActive) { key = "active";  marker = String(i + 1); }
        else               { key = "pending"; marker = String(i + 1); }
        const c = STEPPER_COLORS[key];

        return (
          <div key={p.id} style={{
            flex: 1, position: "relative",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
            padding: `0 ${isLast ? 14 : ARROW + 16}px 0 ${i === 0 ? 14 : ARROW + 8}px`,
            // Horizontal gradient — keeps the right edge uniformly `c.to`,
            // which matches the chevron tail color and avoids any vertical
            // seam where the two meet.
            background: `linear-gradient(to right, ${c.from} 0%, ${c.to} 100%)`,
            color: c.fg,
            fontSize: "0.8rem",
            fontWeight: isActive || isDone || isFailed ? 700 : 500,
            whiteSpace: "nowrap",
            zIndex: DISPLAY_PHASES.length - i,
          }}>
            <span style={{
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              minWidth: 20, height: 20,
              borderRadius: "50%",
              background: "rgba(255,255,255,0.22)",
              color: c.fg,
              fontSize: "0.72rem", fontWeight: 700,
              boxShadow: "0 0 0 1px rgba(255,255,255,0.18) inset",
            }}>
              {marker}
            </span>
            <span style={{ textShadow: key === "pending" ? "none" : "0 1px 1px rgba(0,0,0,0.18)" }}>
              {p.label}
            </span>
            {/* Chevron tail — uses the segment's *darkest* color so the seam
                between same-state segments still shows the gradient step. */}
            {!isLast && (
              <span aria-hidden style={{
                position: "absolute", top: 0, right: -ARROW,
                width: 0, height: 0,
                borderTop:    `${HEIGHT / 2}px solid transparent`,
                borderBottom: `${HEIGHT / 2}px solid transparent`,
                borderLeft:   `${ARROW}px solid ${c.to}`,
                pointerEvents: "none",
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── Preflight panel ───────────────────────────────────────── */

function PreflightPanel({ result }) {
  if (!result) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {result.checks.map((c, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 12px",
          background: c.ok ? "rgba(22,163,74,0.06)" : "rgba(220,38,38,0.06)",
          border: `1px solid ${c.ok ? "#16a34a" : "#dc2626"}`,
          borderRadius: "var(--radius-sm)", fontSize: "0.82rem",
        }}>
          <span>{c.ok ? "✓" : "✗"}</span>
          <strong>{c.name}</strong>
          <span style={{ color: "var(--color-text-light)", marginLeft: "auto", fontFamily: "monospace", fontSize: "0.78rem" }}>
            {c.detail}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ── Plan preview ──────────────────────────────────────────── */

function PlanPreview({ planOutput, onApprove, onCancel, applying }) {
  // Extract the summary line from terraform plan output
  const summaryLine = useMemo(() => {
    if (!planOutput) return null;
    // Look for "Plan: X to add, Y to change, Z to destroy."
    const m = planOutput.match(/Plan:\s*(\d+)\s*to\s*add[^\n]*/i);
    return m ? m[0] : null;
  }, [planOutput]);

  return (
    <div>
      {summaryLine && (
        <div style={{
          padding: "10px 14px", marginBottom: 10,
          background: "rgba(0,212,170,0.08)", border: "1px solid var(--color-accent)",
          borderRadius: "var(--radius-sm)", fontSize: "0.85rem", fontWeight: 600,
        }}>
          📋 {summaryLine}
        </div>
      )}
      <details>
        <summary style={{ cursor: "pointer", fontSize: "0.82rem", color: "var(--color-text-light)" }}>
          상세 plan 보기
        </summary>
        <pre style={{
          marginTop: 8, padding: "10px 12px",
          background: "#0d1117", border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-sm)", maxHeight: 320, overflow: "auto",
          fontSize: "0.75rem", fontFamily: "monospace",
          whiteSpace: "pre-wrap",
        }}>
          {planOutput || "(plan output not yet available)"}
        </pre>
      </details>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button type="button" onClick={onApprove} disabled={applying}
          className="run-btn action-btn"
          style={{ minHeight: 36, padding: "0 24px", fontSize: "0.85rem" }}>
          {applying ? <><span className="spinner" />Apply 중…</> : "✓ 승인 후 Apply"}
        </button>
        <button type="button" onClick={onCancel} disabled={applying}
          className="tab action-btn action-btn--secondary"
          style={{ minHeight: 36, padding: "0 18px", fontSize: "0.82rem" }}>
          취소
        </button>
      </div>
    </div>
  );
}

/* ── Data migration checklist ──────────────────────────────── */

function DataMigrationChecklist({ deployId, scripts, fullScripts, onComplete, onSkip }) {
  return (
    <div>
      <div style={{ fontSize: "0.82rem", color: "var(--color-text-light)", marginBottom: 10 }}>
        Terraform 인프라는 완료되었습니다. 아래 데이터 이전 스크립트를 실행한 뒤 각 항목을 완료 처리해 주세요.
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {scripts.map((s, i) => {
          const fullScript = fullScripts?.[i];
          return (
            <div key={i} style={{
              border: `1px solid ${s.completed ? "#16a34a" : "var(--color-border)"}`,
              borderRadius: "var(--radius-sm)",
              padding: "10px 14px",
              background: s.completed ? "rgba(22,163,74,0.06)" : "transparent",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>
                  {s.completed ? "✓" : `${i + 1}.`} {s.title}
                </span>
                <span style={{ fontSize: "0.75rem", color: "var(--color-text-light)" }}>
                  {s.resource}
                </span>
                {!s.completed && (
                  <button type="button" onClick={() => onComplete(i)}
                    style={{
                      marginLeft: "auto", fontSize: "0.75rem", padding: "3px 10px",
                      background: "none", border: "1px solid var(--color-accent)",
                      color: "var(--color-accent)", borderRadius: "var(--radius-sm)",
                      cursor: "pointer",
                    }}>
                    완료 표시
                  </button>
                )}
              </div>
              {fullScript?.steps?.length > 0 && (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ fontSize: "0.75rem", cursor: "pointer", color: "var(--color-text-light)" }}>
                    명령어 보기
                  </summary>
                  <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
                    {fullScript.steps.map((step, si) => (
                      <pre key={si} style={{
                        margin: 0, padding: "6px 10px",
                        background: "#0d1117", borderRadius: 4,
                        fontSize: "0.72rem", fontFamily: "monospace",
                        color: "#00d4aa",
                        whiteSpace: "pre-wrap", wordBreak: "break-all",
                      }}>{step.command}</pre>
                    ))}
                  </div>
                </details>
              )}
            </div>
          );
        })}
      </div>
      <button type="button" onClick={onSkip}
        style={{
          marginTop: 12, fontSize: "0.78rem",
          background: "none", border: "1px solid var(--color-border)",
          color: "var(--color-text-light)",
          borderRadius: "var(--radius-sm)", padding: "5px 14px",
          cursor: "pointer",
        }}>
        모두 건너뛰고 검증으로 이동
      </button>
    </div>
  );
}

/* ── Modal (배포 시작 팝업 등) ──────────────────────────── */

function Modal({ title, onClose, children, footer }) {
  // Close on Esc
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20,
      }}>
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-md, 10px)",
          width: "min(720px, 100%)",
          maxHeight: "min(86vh, 900px)",
          display: "flex", flexDirection: "column",
          boxShadow: "0 16px 48px rgba(0,0,0,0.45)",
          overflow: "hidden",
        }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "12px 18px",
          borderBottom: "1px solid var(--color-border)",
          background: "var(--color-bg)",
        }}>
          <strong style={{ fontSize: "0.95rem" }}>{title}</strong>
          <div style={{ flex: 1 }} />
          <button type="button" onClick={onClose}
            aria-label="닫기"
            style={{
              background: "none", border: "none",
              fontSize: "1.2rem", lineHeight: 1, cursor: "pointer",
              color: "var(--color-text-light)", padding: "2px 6px",
            }}>
            ✕
          </button>
        </div>
        <div style={{ padding: "16px 18px", overflowY: "auto", flex: 1 }}>
          {children}
        </div>
        {footer && (
          <div style={{
            display: "flex", gap: 8, padding: "12px 18px",
            borderTop: "1px solid var(--color-border)",
            background: "var(--color-bg)",
          }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}


/* ── All Deploys list (Deploy 페이지 메인 화면) ─────────── */

function AllDeploysList({ deploys, loading, runs, canDeploy, onStartNew, onResume, onRefresh, onGoToPlan }) {
  const runMap = Object.fromEntries((runs || []).map(r => [r.run_id, r]));

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <strong style={{ fontSize: "0.95rem" }}>📦 배포 이력</strong>
        <span style={{ color: "var(--color-text-light)", fontSize: "0.78rem" }}>
          {loading ? "로드 중…" : `${deploys.length}건`}
        </span>
        <button type="button" onClick={onRefresh}
          style={{
            background: "none", border: "none",
            color: "var(--color-text-light)", cursor: "pointer",
            fontSize: "0.78rem",
          }}>
          ↻ 새로고침
        </button>
        <div style={{ flex: 1 }} />
        {runs.length === 0 ? (
          <button type="button" onClick={onGoToPlan}
            className="tab action-btn action-btn--secondary"
            style={{ minHeight: 34, padding: "0 16px" }}>
            ➜ Plan 단계로 이동 (배포 가능한 Plan 없음)
          </button>
        ) : (
          <button type="button" onClick={onStartNew}
            disabled={!canDeploy}
            className="run-btn action-btn"
            style={{ minHeight: 36, padding: "0 22px" }}>
            🚀 배포 & 데이터 이전 시작
          </button>
        )}
      </div>

      {loading && (
        <div style={{ padding: 16, fontSize: "0.78rem", color: "var(--color-text-light)" }}>
          <span className="spinner" /> 조회 중…
        </div>
      )}

      {!loading && deploys.length === 0 && (
        <div style={{
          padding: "24px 16px", textAlign: "center",
          background: "var(--color-bg)", border: "1px dashed var(--color-border)",
          borderRadius: "var(--radius-sm)",
          fontSize: "0.85rem", color: "var(--color-text-light)",
        }}>
          아직 배포가 없습니다 — 위의 <strong>"🚀 배포 시작"</strong> 버튼으로 첫 배포를 만드세요.
        </div>
      )}

      {!loading && deploys.length > 0 && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 0,
          border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)",
          overflow: "hidden",
        }}>
          {deploys.map(d => {
            const meta = PHASE_BADGE[d.phase] || { color: "#6b7280", label: d.phase };
            const isTerminal = ["complete", "failed", "cancelled"].includes(d.phase);
            const runInfo = runMap[d.run_id];
            return (
              <div key={d.deploy_id}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 14px",
                  borderBottom: "1px solid var(--color-border)",
                  fontSize: "0.82rem",
                }}>
                <span style={{
                  fontSize: "0.72rem", fontWeight: 600,
                  padding: "3px 10px", borderRadius: 99,
                  color: meta.color, border: `1px solid ${meta.color}`,
                  whiteSpace: "nowrap",
                }}>
                  {meta.label}
                </span>
                <div style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <code style={{ fontSize: "0.74rem", color: "var(--color-text)" }}>
                      {d.deploy_id.slice(0, 12)}…
                    </code>
                    {runInfo
                      ? <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
                          Plan: <code>{d.run_id}</code>
                        </span>
                      : <span style={{ fontSize: "0.74rem", color: "#d97706" }}>
                          (Plan {d.run_id} — 출력 없음)
                        </span>
                    }
                  </div>
                  <div style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
                    시작 {_formatRelative(d.started_at)}
                    {d.error && (
                      <span style={{ color: "#dc2626", marginLeft: 8 }} title={d.error}>
                        · {String(d.error).slice(0, 100)}
                      </span>
                    )}
                  </div>
                </div>
                <button type="button" onClick={() => onResume(d.deploy_id)}
                  className="tab action-btn action-btn--secondary"
                  style={{ minHeight: 30, padding: "0 14px", fontSize: "0.78rem" }}>
                  {isTerminal ? "📂 결과 보기" : "▶ 이어서 진행"}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


/* ── Existing Deploys panel (1 Plan : N Deploys) ─────────── */

const PHASE_BADGE = {
  preflight:        { color: "#60a5fa", label: "사전 점검" },
  plan_running:     { color: "#60a5fa", label: "Plan 중" },
  plan_ready:       { color: "#a78bfa", label: "Plan 대기" },
  apply_running:    { color: "#a78bfa", label: "Apply 중" },
  auto_fixing:      { color: "#d97706", label: "자동 수정 중" },
  apply_failed:     { color: "#dc2626", label: "Apply 실패" },
  applied:          { color: "#10b981", label: "Apply 성공" },
  data_migration:   { color: "#a78bfa", label: "데이터 이전" },
  validating:       { color: "#60a5fa", label: "검증 중" },
  complete:         { color: "#16a34a", label: "완료" },
  failed:           { color: "#dc2626", label: "실패" },
  cancelled:        { color: "#6b7280", label: "취소됨" },
};

function _formatRelative(ts) {
  if (!ts) return "?";
  const diff = Math.max(0, Date.now() / 1000 - ts);
  if (diff < 60)        return `${Math.floor(diff)}초 전`;
  if (diff < 3600)      return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400)     return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

function ScopeCheckPanel({ runId, subscriptionId, region }) {
  const [busy, setBusy]     = useState(false);
  const [error, setError]   = useState(null);
  const [result, setResult] = useState(null);

  const run = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const r = await checkDeployScope({ runId, subscriptionId, region });
      setResult(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const sevColor = (s) => s === "deny" ? "#dc2626" : s === "warn" ? "#d97706" : "#16a34a";
  const sevLabel = (s) => s === "deny" ? "DENY" : s === "warn" ? "WARN" : "OK";

  if (!subscriptionId || !region) {
    return (
      <div style={{
        marginTop: 8, padding: "8px 12px",
        background: "var(--color-bg)", border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-sm)", fontSize: "0.78rem",
        color: "var(--color-text-light)",
      }}>
        🔍 scope 호환성 검사 — Connect 단계에서 Azure subscription / region 을 먼저 선택하세요.
      </div>
    );
  }

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
        <strong style={{ fontSize: "0.82rem" }}>🔍 scope 호환성 검사</strong>
        <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
          subscription / region 의 정책 · SKU 가용성 · quota 를 plan 의 리소스와 매핑
        </span>
        <div style={{ flex: 1 }} />
        <button type="button" onClick={run} disabled={busy}
          className="tab action-btn action-btn--secondary"
          style={{ minHeight: 30, padding: "0 14px", fontSize: "0.78rem" }}>
          {busy ? <><span className="spinner" />검사 중…</> : (result ? "↻ 다시 검사" : "▶ 검사 실행")}
        </button>
      </div>

      {error && <div className="form-error" style={{ marginBottom: 6 }}>{error}</div>}

      {result && (
        <div style={{
          border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)",
          background: "var(--color-bg)", overflow: "hidden",
        }}>
          {/* Summary */}
          <div style={{
            padding: "8px 12px", fontSize: "0.78rem",
            borderBottom: "1px solid var(--color-border)",
            display: "flex", gap: 12, flexWrap: "wrap",
          }}>
            <span>VM 리소스 <strong>{result.vm_resource_count}</strong>개 (sizes: {(result.vm_sizes_wanted || []).join(", ") || "—"})</span>
            <span>· 활성 정책 <strong>{(result.policies || []).length}</strong>개</span>
            <span>· quota 항목 <strong>{(result.quotas || []).length}</strong>개</span>
          </div>

          {/* Issues */}
          {(result.issues || []).length === 0 ? (
            <div style={{ padding: "10px 12px", fontSize: "0.82rem", color: "#16a34a" }}>
              ✓ 명확한 deny / warn 이 발견되지 않았습니다 (단, 이름 충돌 / 정책 평가 같은 동적 제약은 apply 해야 알 수 있음)
            </div>
          ) : (
            <div style={{ padding: 4 }}>
              {(result.issues || []).map((iss, i) => (
                <div key={i} style={{
                  display: "flex", gap: 8, alignItems: "flex-start",
                  padding: "6px 10px", fontSize: "0.78rem",
                  borderBottom: "1px solid var(--color-border)",
                }}>
                  <span style={{
                    fontSize: "0.66rem", fontWeight: 700,
                    padding: "2px 6px", borderRadius: 4,
                    color: "#fff", background: sevColor(iss.severity),
                    whiteSpace: "nowrap",
                  }}>{sevLabel(iss.severity)}</span>
                  <span style={{ color: "var(--color-text-light)", whiteSpace: "nowrap" }}>{iss.category}</span>
                  <code style={{ fontSize: "0.74rem", color: "var(--color-text)" }}>{iss.resource}</code>
                  <span style={{ flex: 1 }}>{iss.detail}</span>
                </div>
              ))}
            </div>
          )}

          {/* Active policies (collapsed) */}
          {(result.policies || []).length > 0 && (
            <details style={{ borderTop: "1px solid var(--color-border)" }}>
              <summary style={{ padding: "6px 12px", fontSize: "0.76rem", cursor: "pointer", color: "var(--color-text-light)" }}>
                활성 정책 목록 ({result.policies.length}개)
              </summary>
              <div style={{ padding: "6px 12px", maxHeight: 180, overflowY: "auto", fontSize: "0.74rem" }}>
                {result.policies.map((p, i) => (
                  <div key={i} style={{ marginBottom: 4 }}>
                    <code>{p.display_name || p.name}</code>
                    {p.enforcement && <span style={{ marginLeft: 6, color: "var(--color-text-light)" }}>· {p.enforcement}</span>}
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Errors during az calls */}
          {result.errors && Object.entries(result.errors).some(([_, v]) => v) && (
            <details style={{ borderTop: "1px solid var(--color-border)", background: "rgba(220,38,38,0.04)" }}>
              <summary style={{ padding: "6px 12px", fontSize: "0.74rem", cursor: "pointer", color: "#dc2626" }}>
                ⚠ 일부 az 호출 실패 — 검사 결과가 불완전할 수 있음
              </summary>
              <div style={{ padding: "6px 12px", fontSize: "0.72rem", color: "var(--color-text-light)" }}>
                {Object.entries(result.errors).map(([k, v]) => v ? <div key={k}><code>{k}</code>: {v}</div> : null)}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}


function ExistingDeploysPanel({ deploys, loading, onResume, onRefresh }) {
  if (loading) {
    return (
      <div style={{ marginTop: 8, fontSize: "0.78rem", color: "var(--color-text-light)" }}>
        <span className="spinner" /> 이 Plan 의 기존 배포 조회 중…
      </div>
    );
  }
  if (!deploys || deploys.length === 0) {
    return (
      <div style={{
        marginTop: 8, padding: "8px 12px",
        background: "var(--color-bg)", border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-sm)", fontSize: "0.78rem",
        color: "var(--color-text-light)",
      }}>
        이 Plan 으로 시작된 배포가 없습니다 — 아래 "🚀 배포 시작" 으로 새 배포를 만드세요.
      </div>
    );
  }
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 6 }}>
        <strong style={{ fontSize: "0.82rem" }}>
          이 Plan 의 배포 이력 ({deploys.length}건)
        </strong>
        <button type="button" onClick={onRefresh}
          style={{
            marginLeft: "auto", background: "none", border: "none",
            color: "var(--color-text-light)", cursor: "pointer",
            fontSize: "0.74rem",
          }}>
          ↻ 새로고침
        </button>
      </div>
      <div style={{
        display: "flex", flexDirection: "column", gap: 4,
        maxHeight: 220, overflowY: "auto",
        border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)",
      }}>
        {deploys.map(d => {
          const meta = PHASE_BADGE[d.phase] || { color: "#6b7280", label: d.phase };
          const isTerminal = ["complete", "failed", "cancelled"].includes(d.phase);
          return (
            <div key={d.deploy_id}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "8px 12px",
                borderBottom: "1px solid var(--color-border)",
                fontSize: "0.78rem",
              }}>
              <span style={{
                fontSize: "0.7rem", fontWeight: 600,
                padding: "2px 8px", borderRadius: 99,
                color: meta.color, border: `1px solid ${meta.color}`,
                whiteSpace: "nowrap",
              }}>
                {meta.label}
              </span>
              <code style={{ fontSize: "0.72rem", color: "var(--color-text-light)" }}>
                {d.deploy_id.slice(0, 8)}…
              </code>
              <span style={{ color: "var(--color-text-light)", fontSize: "0.74rem" }}>
                시작 {_formatRelative(d.started_at)}
              </span>
              {d.error && (
                <span style={{ color: "#dc2626", fontSize: "0.72rem", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  title={d.error}>
                  · {d.error}
                </span>
              )}
              {!d.error && <span style={{ flex: 1 }} />}
              <button type="button" onClick={() => onResume(d.deploy_id)}
                className="tab action-btn action-btn--secondary"
                style={{ minHeight: 28, padding: "0 12px", fontSize: "0.74rem" }}>
                {isTerminal ? "📂 결과 보기" : "▶ 이어서 진행"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}


/* ── Variables form (배포 시작 전 사용자 입력) ──────────────── */

function VariablesForm({ variables, values, onChange }) {
  if (!variables || variables.length === 0) {
    return (
      <div style={{ fontSize: "0.78rem", color: "var(--color-text-light)" }}>
        이 모듈에는 사용자 입력 변수가 없습니다.
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {variables.map(v => {
        const cur = values[v.name];
        const isMap = v.default_kind === "map";
        const isSensitive = !!v.sensitive;
        const placeholder = isSensitive ? "(자동 생성됨 — 입력 시 override)" : "";
        return (
          <div key={v.name} style={{
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-sm)",
            padding: "10px 12px",
          }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
              <code style={{ fontSize: "0.82rem", fontWeight: 600 }}>{v.name}</code>
              {v.type && (
                <span style={{ fontSize: "0.7rem", color: "var(--color-text-light)", fontFamily: "monospace" }}>
                  {v.type}
                </span>
              )}
              {isSensitive && (
                <span style={{ fontSize: "0.68rem", color: "#d97706", padding: "1px 6px", border: "1px solid #d97706", borderRadius: 99 }}>
                  sensitive
                </span>
              )}
            </div>
            {v.description && (
              <div style={{ fontSize: "0.74rem", color: "var(--color-text-light)", marginBottom: 6 }}>
                {v.description}
              </div>
            )}
            {isMap ? (
              <textarea
                value={cur ?? JSON.stringify(v.default || {}, null, 2)}
                onChange={e => onChange(v.name, e.target.value, "map")}
                placeholder='{"key": "value"}'
                rows={3}
                style={{
                  width: "100%", padding: "6px 8px",
                  background: "var(--color-bg)",
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--color-text)", fontSize: "0.78rem", fontFamily: "monospace",
                  boxSizing: "border-box", resize: "vertical",
                }}
              />
            ) : (
              <input
                type={isSensitive ? "password" : "text"}
                value={cur ?? (v.default !== null && v.default !== undefined ? String(v.default) : "")}
                onChange={e => onChange(v.name, e.target.value, v.default_kind)}
                placeholder={placeholder}
                style={{
                  width: "100%", padding: "6px 8px",
                  background: "var(--color-bg)",
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--color-text)", fontSize: "0.82rem",
                  boxSizing: "border-box",
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── Apply 실패 → 수정 → 재시도 패널 ────────────────────────── */

function ApplyFailedPanel({ deploy, onAiFix, onApplyFix, onRetry, onAbandon, onDestroyRestart, onRefreshStatus }) {
  const [aiBusy, setAiBusy]       = useState(false);
  const [aiError, setAiError]     = useState(null);
  const [retrying, setRetrying]   = useState(false);
  const [destroying, setDestroying] = useState(false);
  // editingFiles is the live editor state. originalFiles is the on-disk
  // content the editor was loaded from (used to mark "modified by user").
  const [editingFiles, setEditingFiles] = useState(null);
  const [originalFiles, setOriginalFiles] = useState({});
  const [aiTouched, setAiTouched]       = useState({});  // {filename: change_summary} from AI proposal
  const [selectedFile, setSelectedFile] = useState(null);
  const [filesError, setFilesError]     = useState(null);
  // Lifted shell input state — lets the AI command suggestions push commands
  // straight into the terminal input below.
  const [shellCmd, setShellCmd]         = useState("");
  const shellSectionRef = useRef(null);

  const fix = deploy?.latest_ai_fix;

  // Auto-load files when the panel mounts (apply_failed entered)
  useEffect(() => {
    if (editingFiles !== null || !deploy?.deploy_id) return;
    listDeployFiles(deploy.deploy_id)
      .then(data => {
        const files = data.files || {};
        setEditingFiles(files);
        setOriginalFiles({ ...files });
        const names = Object.keys(files).sort();
        setSelectedFile(prev => prev || names[0] || null);
      })
      .catch(e => setFilesError(e.message));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deploy?.deploy_id]);

  // AI 진단을 두 가지 모드 중 하나로 호출:
  //   "patch_and_retry"   — 현재 배포된 리소스 유지하며 패치
  //   "destroy_and_apply" — destroy 한 뒤 깨끗한 상태에서 재적용
  const [aiMode, setAiMode] = useState(null);  // which mode is currently busy
  const requestFix = async (strategy) => {
    setAiBusy(true); setAiMode(strategy); setAiError(null);
    try {
      await onAiFix(strategy);
      await onRefreshStatus();
    } catch (e) {
      setAiError(e.message);
    } finally {
      setAiBusy(false); setAiMode(null);
    }
  };

  // When latest_ai_fix changes (after onAiFix completes), merge the proposed
  // file contents into the editor as a preview.  User can review/modify.
  const lastFixIdRef = useRef(null);
  useEffect(() => {
    if (!fix || !fix.fixes || fix.fixes.length === 0) return;
    const fixId = JSON.stringify(fix.fixes.map(f => [f.filename, (f.content || "").length]));
    if (fixId === lastFixIdRef.current) return;
    lastFixIdRef.current = fixId;
    setEditingFiles(prev => {
      const next = { ...(prev || {}) };
      const touched = {};
      for (const f of fix.fixes) {
        next[f.filename] = f.content;
        touched[f.filename] = f.change_summary || "AI 수정 제안";
      }
      setAiTouched(touched);
      return next;
    });
    // Auto-select first AI-touched file so user lands on the change
    if (fix.fixes[0]?.filename) setSelectedFile(fix.fixes[0].filename);
  }, [fix]);

  const saveAndRetry = async () => {
    if (!editingFiles) return;
    setFilesError(null); setRetrying(true);
    try {
      // Only send files that actually differ from disk (avoid no-op writes)
      const list = Object.entries(editingFiles)
        .filter(([fn, content]) => originalFiles[fn] !== content)
        .map(([filename, content]) => ({ filename, content }));
      if (list.length === 0) {
        // Nothing to apply — just retry as-is
        await onRetry();
        return;
      }
      const writeResult = await onApplyFix(list);
      const wrote = (writeResult?.written || []).length;
      const skipped = (writeResult?.skipped || []).length;
      if (wrote === 0) {
        setFilesError(`파일이 하나도 적용되지 않았습니다 (skipped ${skipped}개). 로그에서 사유를 확인하세요.`);
        return;
      }
      // Update originalFiles so edits become the new baseline
      setOriginalFiles({ ...editingFiles });
      setAiTouched({});
      await onRetry();
    } catch (e) {
      setFilesError(e.message);
    } finally {
      setRetrying(false);
    }
  };

  const fileTags = (fname) => {
    const tags = [];
    if (aiTouched[fname]) tags.push({ label: "AI", color: "#a78bfa" });
    if (originalFiles[fname] !== undefined && editingFiles?.[fname] !== originalFiles[fname]) {
      tags.push({ label: "수정됨", color: "#d97706" });
    }
    return tags;
  };

  return (
    <div>
      {/* Quarantine — destroy 도 실패해서 이 deploy 폴더는 더 이상 진행 불가 */}
      {deploy.quarantined && (
        <div style={{
          marginBottom: 12, padding: "12px 14px",
          background: "rgba(220,38,38,0.08)",
          border: "1px solid #dc2626",
          borderRadius: "var(--radius-sm)",
        }}>
          <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#dc2626", marginBottom: 6 }}>
            🔒 이 배포는 격리되었습니다 (Quarantined)
          </div>
          <div style={{ fontSize: "0.8rem", color: "var(--color-text-light)", lineHeight: 1.5 }}>
            apply 실패 후 자동 롤백 destroy 도 실패했습니다. state 가 회복 불가능한 상태로 추정되니
            <strong> 새 배포를 시작</strong>하거나 아래 셸에서 직접 정리하세요.
            기존 deploy 폴더는 그대로 보존되니 디버깅에 사용 가능합니다.
          </div>
        </div>
      )}

      {/* AI 진단 버튼 — 두 모드 중 사용자 선택 */}
      <div style={{
        display: "flex", flexDirection: "column", gap: 8, marginBottom: 12,
        padding: "10px 14px",
        background: "var(--color-bg)", border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-sm)",
      }}>
        <div style={{ fontSize: "0.78rem", fontWeight: 600 }}>
          🤖 AI 진단 — 두 가지 모드 중 선택
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button"
            onClick={() => requestFix("patch_and_retry")}
            disabled={aiBusy || destroying || retrying}
            className="tab action-btn action-btn--secondary"
            style={{ minHeight: 36, padding: "0 18px", flex: 1, minWidth: 240 }}
            title="현재 부분 배포된 리소스를 그대로 두고 코드 패치로 apply 가 통과되도록 진단합니다.">
            {aiBusy && aiMode === "patch_and_retry"
              ? <><span className="spinner" />진단 중…</>
              : "↻ 현재 state 유지하며 패치"}
          </button>
          <button type="button"
            onClick={() => requestFix("destroy_and_apply")}
            disabled={aiBusy || destroying || retrying}
            className="tab action-btn action-btn--secondary"
            style={{
              minHeight: 36, padding: "0 18px", flex: 1, minWidth: 240,
              borderColor: "#d97706", color: "#d97706",
            }}
            title="terraform destroy 로 부분 배포된 리소스를 모두 삭제한 뒤, 깨끗한 상태에서 다시 apply 하는 전제로 진단합니다.">
            {aiBusy && aiMode === "destroy_and_apply"
              ? <><span className="spinner" />진단 중…</>
              : "🗑 destroy 후 처음부터 진단"}
          </button>
        </div>
      </div>

      {/* 실행 액션 — 진단 결과의 strategy 에 맞춰 primary 가 결정됨 */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {fix?.strategy === "destroy_and_apply" ? (
          <button type="button"
            onClick={async () => {
              if (!confirm(
                "[destroy 모드] AI 진단을 받았습니다.\n\n" +
                "1. terraform destroy 로 부분 배포된 리소스 삭제\n" +
                "   (원본 코드 기준 — state 와 일치해야 destroy 가 통과)\n" +
                "2. destroy 성공 후 코드 패치 적용\n" +
                "3. state/캐시 정리\n" +
                "4. terraform init + plan 으로 plan_ready 진입\n\n" +
                "계속할까요?",
              )) return;
              setDestroying(true);
              try {
                // 코드 패치를 미리 저장하면 destroy 가 패치된 코드 기준으로 동작해서
                // state mismatch 에러가 남.  그래서 pendingFixes 로 넘겨 destroy
                // **이후에** 적용되도록 한다.
                const pendingFixes = Object.entries(editingFiles || {})
                  .filter(([fn, content]) => originalFiles[fn] !== content)
                  .map(([filename, content]) => ({ filename, content }));
                await onDestroyRestart({ preserveCode: true, pendingFixes });
                // 백엔드가 destroy 성공 후 디스크에 패치를 기록하므로,
                // 프론트의 originalFiles 도 그 시점에 동기화 (낙관적).
                setOriginalFiles({ ...editingFiles });
                setAiTouched({});
                await onRefreshStatus();
              } catch (e) {
                setFilesError(e.message);
              } finally {
                setDestroying(false);
              }
            }}
            disabled={destroying || retrying || aiBusy}
            className="run-btn action-btn"
            style={{ minHeight: 36, padding: "0 22px", background: "#d97706" }}
            title="원본 코드로 destroy → 그 후 코드 패치 적용 → init + plan">
            {destroying ? <><span className="spinner" />destroy 중…</> : "🗑 destroy → 수정 코드로 처음부터"}
          </button>
        ) : (
          <button type="button" onClick={saveAndRetry} disabled={retrying || destroying || aiBusy}
            className="run-btn action-btn"
            style={{ minHeight: 36, padding: "0 22px" }}
            title="진단 모드대로: 현재 에디터의 코드를 저장하고 terraform apply 를 다시 실행">
            {retrying ? <><span className="spinner" />적용 중…</> : "↻ 적용 후 재시도"}
          </button>
        )}

        <div style={{ flex: 1 }} />
        <button type="button" onClick={onAbandon} disabled={destroying || retrying}
          style={{
            background: "none", border: "1px solid var(--color-border)",
            color: "var(--color-text-light)", borderRadius: "var(--radius-sm)",
            padding: "5px 14px", fontSize: "0.82rem", cursor: "pointer",
          }}>
          포기
        </button>
      </div>

      {aiError && <div className="form-error" style={{ marginBottom: 10 }}>{aiError}</div>}
      {filesError && <div className="form-error" style={{ marginBottom: 10 }}>{filesError}</div>}

      {/* AI 진단 텍스트 배너 */}
      {fix && (
        <div style={{
          marginBottom: 12, padding: "10px 14px",
          background: "var(--color-bg)", border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-sm)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
            <strong style={{ fontSize: "0.85rem" }}>🤖 AI 진단</strong>
            {fix.strategy && (
              <span style={{
                fontSize: "0.7rem", fontWeight: 700, padding: "2px 9px",
                borderRadius: 99,
                color: "#fff",
                background: fix.strategy === "destroy_and_apply" ? "#d97706" : "#2563eb",
              }}
              title={fix.strategy === "destroy_and_apply"
                ? "destroy 후 깨끗한 상태에서 다시 apply 하는 전제로 작성된 수정안"
                : "현재 배포된 리소스를 유지한 채 코드를 패치하는 전제로 작성된 수정안"
              }>
                {fix.strategy === "destroy_and_apply" ? "🗑 destroy 모드" : "↻ 현재 state 유지 모드"}
              </span>
            )}
            {fix.fixes?.length > 0 && (
              <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
                · 제안된 수정 {fix.fixes.length}개 파일 (아래 에디터에 미리보기로 로드됨)
              </span>
            )}
            {fix.commands?.length > 0 && (
              <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
                · 실행 시퀀스 {fix.commands.length}단계
              </span>
            )}
          </div>
          <p style={{ margin: 0, fontSize: "0.82rem", lineHeight: 1.5 }}>
            {fix.diagnosis}
          </p>
          {fix.user_action && (
            <div style={{
              marginTop: 8, padding: "8px 12px",
              background: "rgba(217,119,6,0.08)", border: "1px solid #d97706",
              borderRadius: "var(--radius-sm)", fontSize: "0.8rem",
            }}>
              <strong>사용자 액션 필요 (셸에서 수동 처리 가능):</strong> {fix.user_action}
            </div>
          )}
          {fix.fixes?.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ fontSize: "0.76rem", color: "var(--color-text-light)", cursor: "pointer" }}>
                파일별 변경 요약 ({fix.fixes.length}개)
              </summary>
              <ul style={{ margin: "6px 0 0 18px", padding: 0, fontSize: "0.78rem" }}>
                {fix.fixes.map((f, i) => (
                  <li key={i}><code>{f.filename}</code> — {f.change_summary}</li>
                ))}
              </ul>
            </details>
          )}
          {/* AI 가 제시한 실행 시퀀스 — fixes 적용 후 순서대로 실행 */}
          {fix.commands?.length > 0 && (
            <CommandRunbook
              key={lastFixIdRef.current /* reset state when a new diagnosis arrives */}
              deployId={deploy.deploy_id}
              commands={fix.commands}
            />
          )}
        </div>
      )}

      {/* 코드 에디터 — 항상 표시 */}
      {editingFiles && (
        <FileBrowserEditor
          files={editingFiles}
          selected={selectedFile}
          onSelect={setSelectedFile}
          onChange={(fname, content) => setEditingFiles(prev => ({ ...prev, [fname]: content }))}
          filesError={null}
          tagsFor={fileTags}
        />
      )}

      {/* Shell 터미널 — 항상 표시 */}
      <div ref={shellSectionRef} style={{ marginTop: 14 }}>
        <div style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: 6 }}>
          🖥️ 작업 디렉토리 셸
        </div>
        <ShellTerminal
          deployId={deploy.deploy_id}
          cmd={shellCmd}
          onCmdChange={setShellCmd}
        />
      </div>
    </div>
  );
}

/* ── File browser editor ──────────────────────────────────── */

function FileBrowserEditor({ files, selected, onSelect, onChange, filesError, tagsFor }) {
  const names = Object.keys(files).sort();
  const current = selected && files[selected] != null ? selected : names[0];
  const content = current ? (files[current] ?? "") : "";

  return (
    <div>
      {filesError && <div className="form-error" style={{ marginBottom: 8 }}>{filesError}</div>}
      <div style={{
        display: "grid", gridTemplateColumns: "260px 1fr", gap: 0,
        border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)",
        overflow: "hidden", height: 480,
      }}>
        {/* 왼쪽: 파일 리스트 */}
        <div style={{
          background: "var(--color-bg)", borderRight: "1px solid var(--color-border)",
          overflowY: "auto",
        }}>
          {names.map(fname => {
            const isSel = fname === current;
            const tags  = tagsFor ? tagsFor(fname) : [];
            return (
              <div key={fname}
                onClick={() => onSelect(fname)}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "6px 10px", cursor: "pointer",
                  fontFamily: "monospace", fontSize: "0.74rem",
                  background: isSel ? "var(--color-primary, #2563eb)" : "transparent",
                  color: isSel ? "#fff" : "var(--color-text)",
                  borderBottom: "1px solid var(--color-border)",
                }}
                title={fname}>
                <span style={{
                  flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{fname}</span>
                {tags.map((t, i) => (
                  <span key={i} style={{
                    fontSize: "0.62rem", fontWeight: 700,
                    padding: "1px 5px", borderRadius: 4,
                    color: "#fff", background: t.color,
                    whiteSpace: "nowrap",
                  }}>
                    {t.label}
                  </span>
                ))}
              </div>
            );
          })}
        </div>
        {/* 오른쪽: 본문 에디터 */}
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div style={{
            padding: "5px 10px", borderBottom: "1px solid var(--color-border)",
            fontFamily: "monospace", fontSize: "0.74rem",
            background: "var(--color-bg)", color: "var(--color-text-light)",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <span style={{ flex: 1 }}>{current || "(파일 없음)"}</span>
            {(tagsFor ? tagsFor(current) : []).map((t, i) => (
              <span key={i} style={{
                fontSize: "0.65rem", fontWeight: 700,
                padding: "1px 6px", borderRadius: 4,
                color: "#fff", background: t.color,
              }}>{t.label}</span>
            ))}
          </div>
          <textarea
            key={current}
            value={content}
            onChange={e => current && onChange(current, e.target.value)}
            spellCheck={false}
            disabled={!current}
            style={{
              flex: 1, padding: "10px 12px",
              background: "#0d1117", color: "#00d4aa",
              border: "none",
              fontFamily: "monospace", fontSize: "0.76rem",
              resize: "none", boxSizing: "border-box", outline: "none",
            }}
          />
        </div>
      </div>
    </div>
  );
}

/* ── Command runbook (AI 가 만든 실행 시퀀스) ───────────── */

function CommandRunbook({ deployId, commands }) {
  // results[i] = { status: "pending"|"running"|"done"|"failed",
  //                stdout, stderr, exit_code, error }
  const [results, setResults] = useState(() => commands.map(() => ({ status: "pending" })));
  const [busy, setBusy]       = useState(false);
  const [stopOnFail, setStopOnFail] = useState(true);

  const runOne = async (i) => {
    setResults(prev => {
      const next = [...prev];
      next[i] = { status: "running" };
      return next;
    });
    try {
      const r = await execInDeployWorkdir(deployId, commands[i].cmd);
      const ok = r.exit_code === 0;
      setResults(prev => {
        const next = [...prev];
        next[i] = {
          status: ok ? "done" : "failed",
          exit_code: r.exit_code,
          stdout:    r.stdout,
          stderr:    r.stderr,
        };
        return next;
      });
      return ok;
    } catch (e) {
      setResults(prev => {
        const next = [...prev];
        next[i] = { status: "failed", error: e.message };
        return next;
      });
      return false;
    }
  };

  const runAll = async () => {
    if (busy) return;
    setBusy(true);
    try {
      for (let i = 0; i < commands.length; i++) {
        const ok = await runOne(i);
        if (!ok && stopOnFail) break;
      }
    } finally {
      setBusy(false);
    }
  };

  const runFrom = async (start) => {
    if (busy) return;
    setBusy(true);
    try {
      for (let i = start; i < commands.length; i++) {
        const ok = await runOne(i);
        if (!ok && stopOnFail) break;
      }
    } finally {
      setBusy(false);
    }
  };

  const reset = () => setResults(commands.map(() => ({ status: "pending" })));

  const STATUS_META = {
    pending: { color: "#6b7280", label: "대기" },
    running: { color: "#60a5fa", label: "실행 중" },
    done:    { color: "#16a34a", label: "✓"     },
    failed:  { color: "#dc2626", label: "✗"     },
  };

  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--color-border)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <strong style={{ fontSize: "0.82rem" }}>
          🛠️ 실행 시퀀스 ({commands.length}단계)
        </strong>
        <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
          fixes 적용 후 위에서 아래로 차례로 실행
        </span>
        <div style={{ flex: 1 }} />
        <label style={{ fontSize: "0.74rem", color: "var(--color-text-light)", display: "flex", alignItems: "center", gap: 4 }}>
          <input type="checkbox" checked={stopOnFail} onChange={e => setStopOnFail(e.target.checked)} />
          실패 시 중단
        </label>
        <button type="button" onClick={runAll} disabled={busy}
          className="run-btn action-btn"
          style={{ minHeight: 30, padding: "0 14px", fontSize: "0.78rem" }}>
          {busy ? <><span className="spinner" />실행 중…</> : "▶ 모두 순서대로 실행"}
        </button>
        <button type="button" onClick={reset} disabled={busy}
          style={{
            background: "none", border: "1px solid var(--color-border)",
            color: "var(--color-text-light)", borderRadius: "var(--radius-sm)",
            padding: "3px 10px", fontSize: "0.72rem", cursor: "pointer",
          }}>
          ↻ 초기화
        </button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {commands.map((c, i) => {
          const r = results[i] || { status: "pending" };
          const meta = STATUS_META[r.status] || STATUS_META.pending;
          return (
            <div key={i} style={{
              padding: "8px 10px",
              background: "#0d1117",
              border: `1px solid ${r.status === "failed" ? "#dc2626" : "var(--color-border)"}`,
              borderLeft: `3px solid ${meta.color}`,
              borderRadius: "var(--radius-sm)",
              opacity: busy && r.status === "pending" ? 0.7 : 1,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  minWidth: 20, height: 20, borderRadius: "50%",
                  background: meta.color, color: "#fff",
                  fontSize: "0.7rem", fontWeight: 700,
                }}>
                  {r.status === "running" ? <span className="spinner" /> : (i + 1)}
                </span>
                <span style={{ fontSize: "0.74rem", color: "#94a3b8", flex: 1 }}>
                  {c.purpose}
                </span>
                <span style={{ fontSize: "0.7rem", color: meta.color, fontWeight: 600 }}>
                  {meta.label}
                </span>
                <button type="button"
                  onClick={() => runOne(i)} disabled={busy}
                  className="tab action-btn action-btn--secondary"
                  style={{ minHeight: 24, padding: "0 8px", fontSize: "0.7rem" }}
                  title="이 단계만 단독 실행">
                  ▶
                </button>
                <button type="button"
                  onClick={() => runFrom(i)} disabled={busy}
                  className="tab action-btn action-btn--secondary"
                  style={{ minHeight: 24, padding: "0 8px", fontSize: "0.7rem" }}
                  title="이 단계부터 끝까지 실행">
                  ▶▶
                </button>
                <button type="button"
                  onClick={() => navigator.clipboard?.writeText(c.cmd)}
                  style={{
                    background: "none", border: "1px solid var(--color-border)",
                    color: "var(--color-text-light)", borderRadius: "var(--radius-sm)",
                    padding: "1px 6px", fontSize: "0.7rem", cursor: "pointer",
                  }}
                  title="클립보드 복사">
                  📋
                </button>
              </div>
              <code style={{
                display: "block",
                fontFamily: "monospace", fontSize: "0.74rem",
                color: "#7ee787",
                whiteSpace: "pre-wrap", wordBreak: "break-all",
              }}>
                $ {c.cmd}
              </code>
              {r.stdout && (
                <pre style={{
                  margin: "6px 0 0", padding: "6px 8px",
                  background: "#000", borderRadius: 3,
                  fontSize: "0.72rem", fontFamily: "monospace",
                  color: "#e6edf3",
                  whiteSpace: "pre-wrap", wordBreak: "break-all",
                  maxHeight: 200, overflow: "auto",
                }}>{r.stdout}</pre>
              )}
              {(r.stderr || r.error) && (
                <pre style={{
                  margin: "6px 0 0", padding: "6px 8px",
                  background: "rgba(220,38,38,0.08)", borderRadius: 3,
                  fontSize: "0.72rem", fontFamily: "monospace",
                  color: "#ff7b72",
                  whiteSpace: "pre-wrap", wordBreak: "break-all",
                  maxHeight: 200, overflow: "auto",
                }}>{r.stderr || r.error}</pre>
              )}
              {r.exit_code != null && r.exit_code !== 0 && (
                <div style={{ fontSize: "0.7rem", color: "#ff7b72", marginTop: 2 }}>
                  exit code {r.exit_code}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}


/* ── Shell terminal ───────────────────────────────────────── */

function ShellTerminal({ deployId, cmd: cmdProp, onCmdChange }) {
  // Controlled/uncontrolled hybrid: if parent passes cmd+onCmdChange, the
  // input is controlled (so AI suggestions can prefill it); otherwise the
  // terminal manages its own input state.
  const [cmdLocal, setCmdLocal] = useState("");
  const cmd    = cmdProp != null ? cmdProp : cmdLocal;
  const setCmd = onCmdChange     ? onCmdChange : setCmdLocal;

  const [history, setHistory] = useState([]); // [{cmd, exit_code, stdout, stderr}]
  const [busy, setBusy] = useState(false);
  const [histIdx, setHistIdx] = useState(-1); // for ↑↓ navigation
  const inputRef = useRef(null);
  const outRef = useRef(null);

  // Auto-focus the input when the parent prefills via cmdProp (so user can
  // immediately Enter to run, or edit further).
  useEffect(() => {
    if (cmdProp && inputRef.current) inputRef.current.focus();
  }, [cmdProp]);

  useEffect(() => {
    if (outRef.current) outRef.current.scrollTop = outRef.current.scrollHeight;
  }, [history, busy]);

  const run = async () => {
    const trimmed = cmd.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    const entry = { cmd: trimmed, exit_code: null, stdout: "", stderr: "" };
    setHistory(prev => [...prev, entry]);
    setCmd(""); setHistIdx(-1);
    try {
      const result = await execInDeployWorkdir(deployId, trimmed);
      setHistory(prev => {
        const copy = [...prev];
        copy[copy.length - 1] = { cmd: trimmed, ...result };
        return copy;
      });
    } catch (e) {
      setHistory(prev => {
        const copy = [...prev];
        copy[copy.length - 1] = { cmd: trimmed, exit_code: -1, stdout: "", stderr: e.message };
        return copy;
      });
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      run();
    } else if (e.key === "ArrowUp") {
      const cmds = history.map(h => h.cmd);
      if (cmds.length === 0) return;
      e.preventDefault();
      const ni = histIdx < 0 ? cmds.length - 1 : Math.max(0, histIdx - 1);
      setHistIdx(ni);
      setCmd(cmds[ni] || "");
    } else if (e.key === "ArrowDown") {
      const cmds = history.map(h => h.cmd);
      if (histIdx < 0) return;
      e.preventDefault();
      const ni = histIdx + 1;
      if (ni >= cmds.length) { setHistIdx(-1); setCmd(""); }
      else { setHistIdx(ni); setCmd(cmds[ni] || ""); }
    }
  };

  const SUGGESTIONS = [
    "terraform validate",
    "terraform fmt -check",
    "terraform plan -no-color",
    "terraform state list",
    "ls -la",
    "az account show",
    "az vm list-skus --location koreacentral --resource-type virtualMachines --output table",
  ];

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: "0.72rem", color: "var(--color-text-light)", marginBottom: 6 }}>
        모든 셸 명령 허용 — 파이프 / 리다이렉션 / 임의 바이너리 모두 동작합니다. cwd = 이 deploy 의 작업 디렉토리.
      </div>
      <div ref={outRef} style={{
        background: "#0d1117", color: "#e6edf3",
        padding: "10px 12px", borderRadius: "var(--radius-sm)",
        fontFamily: "monospace", fontSize: "0.74rem",
        height: 280, overflowY: "auto",
        border: "1px solid var(--color-border)",
      }}>
        {history.length === 0 && (
          <div style={{ color: "#6e7681" }}>
            $ &nbsp;명령을 입력하세요. 예시:
            {SUGGESTIONS.map((s, i) => (
              <div key={i}>
                <button type="button"
                  onClick={() => setCmd(s)}
                  style={{
                    background: "none", border: "none",
                    color: "#58a6ff", cursor: "pointer",
                    fontFamily: "monospace", fontSize: "0.74rem",
                    padding: 0, textAlign: "left",
                  }}>
                  {s}
                </button>
              </div>
            ))}
          </div>
        )}
        {history.map((h, i) => (
          <div key={i} style={{ marginBottom: 8 }}>
            <div style={{ color: "#7ee787" }}>$ {h.cmd}</div>
            {h.stdout && <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{h.stdout}</pre>}
            {h.stderr && <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all", color: "#ff7b72" }}>{h.stderr}</pre>}
            {h.exit_code !== null && h.exit_code !== 0 && (
              <div style={{ color: "#ff7b72", fontSize: "0.7rem" }}>[exit {h.exit_code}]</div>
            )}
          </div>
        ))}
        {busy && <div style={{ color: "#d2a8ff" }}><span className="spinner" /> 실행 중…</div>}
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <span style={{ alignSelf: "center", color: "#7ee787", fontFamily: "monospace" }}>$</span>
        <input
          ref={inputRef}
          type="text"
          value={cmd}
          onChange={e => setCmd(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="terraform validate"
          disabled={busy}
          spellCheck={false}
          style={{
            flex: 1, padding: "6px 10px",
            background: "#0d1117", color: "#e6edf3",
            border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)",
            fontFamily: "monospace", fontSize: "0.78rem",
          }}
        />
        <button type="button" onClick={run} disabled={busy || !cmd.trim()}
          className="run-btn action-btn"
          style={{ minHeight: 32, padding: "0 16px", fontSize: "0.78rem" }}>
          실행
        </button>
        {history.length > 0 && (
          <button type="button" onClick={() => { setHistory([]); setHistIdx(-1); }}
            className="tab action-btn action-btn--secondary"
            style={{ minHeight: 32, padding: "0 12px", fontSize: "0.74rem" }}
            title="콘솔 비우기">
            지우기
          </button>
        )}
      </div>
    </div>
  );
}

/* ── Validation summary ────────────────────────────────────── */

function ValidationPanel({ validation }) {
  if (!validation) return <div style={{ fontSize: "0.82rem", color: "var(--color-text-light)" }}>검증 진행 중…</div>;
  const total = (validation.resources || []).length;
  return (
    <div>
      <div style={{
        padding: "10px 14px", marginBottom: 10,
        background: "rgba(22,163,74,0.08)", border: "1px solid #16a34a",
        borderRadius: "var(--radius-sm)", fontSize: "0.85rem", fontWeight: 600,
      }}>
        ✓ Azure에서 확인된 리소스: <strong>{total}개</strong>
      </div>
      {validation.error && (
        <div className="form-error" style={{ fontSize: "0.78rem", marginBottom: 10 }}>
          ⚠ {validation.error}
        </div>
      )}
      {Object.entries(validation.by_type || {}).length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
          {Object.entries(validation.by_type).map(([t, n]) => (
            <span key={t} style={{
              fontSize: "0.72rem", padding: "3px 10px", borderRadius: 99,
              background: "rgba(0,212,170,0.06)", border: "1px solid var(--color-accent)",
              color: "var(--color-accent)",
            }}>
              {t.split("/").pop()} × {n}
            </span>
          ))}
        </div>
      )}
      <details>
        <summary style={{ fontSize: "0.78rem", cursor: "pointer", color: "var(--color-text-light)" }}>
          전체 리소스 목록 ({total})
        </summary>
        <ul style={{ marginTop: 8, paddingLeft: 18, fontSize: "0.78rem", lineHeight: 1.6 }}>
          {(validation.resources || []).map((r, i) => (
            <li key={i}>
              <code style={{ fontSize: "0.72rem" }}>{r.type}</code> · {r.name} · {r.location}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────── */

export default function DeployPage({ sessionId, sessionScope, onGoToPlan, onGoToConnect }) {
  // If we have at least scope info (e.g., from React state surviving a backend
  // reload), the deploy step is usable even when sessionId is invalid.
  const canDeploy = !!(sessionId || sessionScope?.azure_subscription_id);
  const [runs, setRuns]               = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [output, setOutput]           = useState(null);
  const [deploy, setDeploy]           = useState(null);
  const [logs, setLogs]               = useState([]);
  const [logOffset, setLogOffset]     = useState(0);
  const [error, setError]             = useState(null);
  const [starting, setStarting]       = useState(false);
  const [approving, setApproving]     = useState(false);
  const [variables, setVariables]     = useState([]);     // parsed variable defs
  const [varValues, setVarValues]     = useState({});     // user overrides keyed by variable name
  const [loadingVars, setLoadingVars] = useState(false);
  const [existingDeploys, setExistingDeploys] = useState([]); // deploys for selectedRunId
  const [loadingDeploys, setLoadingDeploys]   = useState(false);
  const [allDeploys, setAllDeploys]           = useState([]); // all deploys (landing list)
  const [loadingAllDeploys, setLoadingAllDeploys] = useState(false);
  const [showStartConfig, setShowStartConfig] = useState(false);
  const [autoRollback, setAutoRollback]       = useState(true);   // apply 실패 시 자동 destroy + re-plan
  const logBoxRef = useRef(null);

  // Load runs on mount
  useEffect(() => {
    fetchMigrationOutputs()
      .then(res => {
        const list = (res.runs || []).filter(r => r.has_terraform);
        setRuns(list);
        if (list.length > 0 && !selectedRunId) setSelectedRunId(list[0].run_id);
      })
      .catch(() => setRuns([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load output for the run we care about — either the dropdown selection
  // (new-deploy modal) OR the active deploy's run_id (when user resumed an
  // existing deploy via the cards).  Without this, data migration scripts
  // never appear because `output` stays null in the resume path.
  useEffect(() => {
    const rid = selectedRunId || deploy?.run_id;
    if (!rid) { setOutput(null); return; }
    fetchMigrationOutput(rid).then(setOutput).catch(() => setOutput(null));
  }, [selectedRunId, deploy?.run_id]);

  // Load variables.tf definitions when a run is selected (so user can override)
  useEffect(() => {
    if (!selectedRunId) { setVariables([]); setVarValues({}); return; }
    setLoadingVars(true);
    getRunVariables(selectedRunId)
      .then(res => setVariables(res.variables || []))
      .catch(() => setVariables([]))
      .finally(() => setLoadingVars(false));
    setVarValues({});   // reset user overrides on run change
  }, [selectedRunId]);

  // Load existing Deploys for the selected Plan (1 Plan : N Deploys)
  const refreshExistingDeploys = async (runId) => {
    if (!runId) { setExistingDeploys([]); return; }
    setLoadingDeploys(true);
    try {
      const res = await listDeploysForRun(runId);
      setExistingDeploys(res.deploys || []);
    } catch {
      setExistingDeploys([]);
    } finally {
      setLoadingDeploys(false);
    }
  };
  useEffect(() => { refreshExistingDeploys(selectedRunId); }, [selectedRunId]);

  // Load all Deploys for the landing list
  const refreshAllDeploys = async () => {
    setLoadingAllDeploys(true);
    try {
      const res = await listAllDeploys();
      setAllDeploys(res.deploys || []);
    } catch {
      setAllDeploys([]);
    } finally {
      setLoadingAllDeploys(false);
    }
  };
  useEffect(() => { refreshAllDeploys(); }, []);

  // After a deploy enters a terminal state, refresh both lists so the user
  // can see "성공" / "실패" status and start another deploy from the same Plan.
  useEffect(() => {
    const TERMINAL = new Set(["complete", "failed", "cancelled"]);
    if (deploy?.phase && TERMINAL.has(deploy.phase)) {
      refreshExistingDeploys(selectedRunId);
      refreshAllDeploys();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deploy?.phase]);

  // Poll deploy status
  useEffect(() => {
    if (!deploy?.deploy_id) return undefined;
    const TERMINAL = new Set(["complete", "failed", "cancelled"]);
    if (TERMINAL.has(deploy.phase)) return undefined;

    let cancelled = false;
    let offset = logOffset;

    const tick = async () => {
      try {
        const next = await getDeployV2Status(deploy.deploy_id, offset);
        if (cancelled) return;
        if (Array.isArray(next.log_lines) && next.log_lines.length > 0) {
          setLogs(prev => [...prev, ...next.log_lines]);
          offset = next.log_total ?? offset + next.log_lines.length;
          setLogOffset(offset);
        } else if (typeof next.log_total === "number") {
          offset = next.log_total;
          setLogOffset(offset);
        }
        setDeploy(cur => cur ? { ...cur, ...next, log_lines: undefined } : cur);
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      }
    };

    const interval = setInterval(tick, 1500);
    tick();
    return () => { cancelled = true; clearInterval(interval); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deploy?.deploy_id, deploy?.phase]);

  // Auto-scroll logs
  useEffect(() => {
    const el = logBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  // Build the tfvars payload — only include user-edited values (defaults stay in .tf).
  const buildTfvars = () => {
    const out = {};
    for (const [name, val] of Object.entries(varValues)) {
      if (val === undefined || val === "" || val === null) continue;
      const v = variables.find(x => x.name === name);
      if (!v) continue;
      // Skip if value equals the default (avoid noise)
      if (v.default_kind === "map") {
        try {
          const parsed = JSON.parse(val);
          if (JSON.stringify(parsed) === JSON.stringify(v.default || {})) continue;
          out[name] = parsed;
        } catch {
          out[name] = val;   // user typed invalid JSON — pass through, terraform will complain
        }
      } else if (v.default_kind === "bool") {
        out[name] = val === "true" || val === true;
      } else if (v.default_kind === "number") {
        const n = Number(val);
        if (!Number.isNaN(n)) out[name] = n;
      } else {
        // string / unknown / sensitive
        if (String(v.default ?? "") === String(val)) continue;
        out[name] = val;
      }
    }
    return Object.keys(out).length > 0 ? out : null;
  };

  const startDeploy = async () => {
    if (!selectedRunId) { setError("Plan 결과를 먼저 선택하세요"); return; }
    if (!sessionId && !sessionScope?.azure_subscription_id) {
      setError("Connect 단계에서 Azure 자격증명을 먼저 연결하세요 (또는 Subscription ID 정보 필요)");
      return;
    }
    setStarting(true); setError(null); setLogs([]); setLogOffset(0);
    let tfvars = null;
    try {
      tfvars = buildTfvars();
    } catch (e) {
      setError(`변수 처리 중 오류: ${e.message}`);
      setStarting(false);
      return;
    }
    try {
      const res = await startDeployV2({
        runId: selectedRunId,
        sessionId,
        // Always send scope as a fallback so deploy works even after backend
        // reload (when the in-memory session is gone).
        azureSubscriptionId:   sessionScope?.azure_subscription_id,
        azureSubscriptionName: sessionScope?.azure_subscription_name,
        azureRegion:           sessionScope?.azure_region,
        awsAccountId:          sessionScope?.aws_account_id,
        awsRegion:             sessionScope?.aws_region,
        tfvars,
        autoRollback,
      });
      setDeploy(res);
      // Collapse the start-config panel — user lands on the deploy progress view
      setShowStartConfig(false);
      refreshAllDeploys();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setStarting(false);
    }
  };

  const approve = async () => {
    if (!deploy?.deploy_id) return;
    setApproving(true); setError(null);
    try {
      await approveDeployV2Plan(deploy.deploy_id);
    } catch (e) {
      setError(e.message);
    } finally {
      setApproving(false);
    }
  };

  const cancel = async () => {
    if (!deploy?.deploy_id) return;
    try { await cancelDeployV2(deploy.deploy_id); } catch (e) { setError(e.message); }
  };

  const completeStep = async (idx) => {
    if (!deploy?.deploy_id) return;
    try { await completeDataMigrationStep(deploy.deploy_id, idx); } catch (e) { setError(e.message); }
  };

  const skipDM = async () => {
    if (!deploy?.deploy_id) return;
    try { await skipDataMigration(deploy.deploy_id); } catch (e) { setError(e.message); }
  };

  const phase = deploy?.phase;
  // Live `/migration/run` result wraps the v2 plan inside `json_data.v2`,
  // but the persisted `agent_output.json` reloaded via `/outputs/{run_id}`
  // has the plan flattened directly into `json_data`.  Support both shapes.
  const fullScripts = (
    output?.json_data?.v2?.data_migrations
    || output?.json_data?.data_migrations
    || []
  );

  return (
    <section className="page-section">
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ margin: "0 0 4px", fontSize: "1.2rem", fontWeight: 700 }}>
          배포 & 데이터 이전
        </h2>
        <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--color-text-light)" }}>
          이전 단계에서 생성된 Terraform 모듈을 Azure에 배포하고, 데이터 이전 스크립트 진행 상황을 추적합니다.
        </p>
      </div>

      {/* ── 1. Run 선택 + 시작 ── */}
      {!deploy && (
        <div style={{
          padding: "16px 20px",
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-sm)",
          marginBottom: 16,
        }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 700, marginBottom: 12 }}>
            <span style={{ color: "#00d4aa" }}>●</span> 배포 시작
          </div>

          {!sessionId && sessionScope?.azure_subscription_id && (
            <div style={{
              padding: "8px 12px", marginBottom: 10,
              background: "rgba(217,119,6,0.06)", border: "1px solid #d97706",
              borderRadius: "var(--radius-sm)", fontSize: "0.82rem", color: "#d97706",
            }}>
              ⚠ 백엔드 세션이 만료되었습니다 ({sessionScope.azure_subscription_id} 정보로 진행 가능).
              완전한 자격증명 검증을 원하면 <a href="#" onClick={e => { e.preventDefault(); onGoToConnect?.(); }}
                style={{ color: "#d97706", textDecoration: "underline" }}>Connect 단계</a>에서 재연결하세요.
            </div>
          )}
          {!sessionId && !sessionScope?.azure_subscription_id && (
            <div className="form-error" style={{ marginBottom: 10 }}>
              ⚠ Connect 단계에서 Azure 자격증명을 먼저 연결하세요.
            </div>
          )}

          {error && (
            <div className="form-error" style={{ marginBottom: 10 }}>
              <strong>배포 시작 실패:</strong> {error}
            </div>
          )}

          {/* 메인 화면: 기존 Deploy 리스트 + 배포 시작 CTA (항상 표시) */}
          <AllDeploysList
            deploys={allDeploys}
            loading={loadingAllDeploys}
            runs={runs}
            canDeploy={canDeploy}
            onStartNew={() => setShowStartConfig(true)}
            onResume={async (deployId) => {
              setError(null);
              try {
                const status = await getDeployV2Status(deployId, 0);
                setLogs(status.log_lines || []);
                setLogOffset(status.log_total ?? 0);
                setDeploy({ ...status, deploy_id: deployId, log_lines: undefined });
              } catch (e) {
                setError(e.message || String(e));
              }
            }}
            onRefresh={refreshAllDeploys}
            onGoToPlan={onGoToPlan}
          />

          {/* 배포 시작 팝업 — "🚀 배포 시작" CTA 클릭 시 모달로 표시 */}
          {showStartConfig && (
            <Modal
              title="🚀 새 배포 시작"
              onClose={() => setShowStartConfig(false)}
              footer={runs.length > 0 ? (
                <>
                  <button type="button" onClick={() => setShowStartConfig(false)}
                    className="tab action-btn action-btn--secondary"
                    style={{ minHeight: 36, padding: "0 18px" }}>
                    취소
                  </button>
                  <div style={{ flex: 1 }} />
                  <button type="button" onClick={startDeploy}
                    disabled={starting || !canDeploy || !selectedRunId}
                    className="run-btn action-btn"
                    style={{ minHeight: 36, padding: "0 22px" }}>
                    {starting ? <><span className="spinner" />실행 중…</> : "실행"}
                  </button>
                </>
              ) : null}
            >
              {runs.length === 0 ? (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: 16, color: "var(--color-text-light)" }}>
                  <p style={{ margin: "0 0 12px" }}>배포 가능한 Plan 결과가 없습니다.</p>
                  <button type="button" onClick={onGoToPlan}
                    className="tab action-btn action-btn--secondary">
                    ➜ Plan 단계로 이동
                  </button>
                </div>
              ) : (
                <>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
                    <label style={{ fontSize: "0.82rem", color: "var(--color-text-light)" }}>Plan 결과 선택</label>
                    <select value={selectedRunId || ""} onChange={e => setSelectedRunId(e.target.value)}
                      style={{
                        flex: 1, minWidth: 240,
                        padding: "5px 8px", borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--color-border)",
                        background: "var(--color-surface)", color: "var(--color-text)",
                        fontSize: "0.82rem",
                      }}>
                      {runs.map(r => (
                        <option key={r.run_id} value={r.run_id}>
                          {r.run_id} {r.has_terraform ? `· tf ${r.terraform_file_count}` : ""}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* scope 호환성 검사 */}
                  {selectedRunId && (
                    <ScopeCheckPanel
                      runId={selectedRunId}
                      subscriptionId={sessionScope?.azure_subscription_id}
                      region={sessionScope?.azure_region}
                    />
                  )}

                  {/* 실패 처리 옵션 */}
                  {selectedRunId && (
                    <div style={{
                      display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
                      marginBottom: 12, padding: "8px 12px",
                      background: "var(--color-bg)",
                      border: "1px solid var(--color-border)",
                      borderRadius: "var(--radius-sm)",
                      fontSize: "0.78rem",
                    }}>
                      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontWeight: 600 }}>
                        <input type="checkbox" checked={autoRollback}
                          onChange={e => setAutoRollback(e.target.checked)} />
                        <span>↻ apply 실패 시 자동 롤백</span>
                      </label>
                      <span style={{ color: "var(--color-text-light)", fontWeight: 400 }}>
                        — refresh + destroy 로 부분 배포된 리소스 정리 후 plan_ready 로 복귀
                        {autoRollback ? " (state 누적 방지)" : " (꺼짐 — apply_failed 상태에서 직접 디버깅)"}
                      </span>
                    </div>
                  )}

                  {/* 이 Plan 으로 시작된 기존 Deploys (1 Plan : N Deploys) */}
                  {selectedRunId && (
                    <ExistingDeploysPanel
                      deploys={existingDeploys}
                      loading={loadingDeploys}
                      onResume={async (deployId) => {
                        setError(null);
                        try {
                          const status = await getDeployV2Status(deployId, 0);
                          setLogs(status.log_lines || []);
                          setLogOffset(status.log_total ?? 0);
                          setDeploy({ ...status, deploy_id: deployId, log_lines: undefined });
                          setShowStartConfig(false);
                        } catch (e) {
                          setError(e.message || String(e));
                        }
                      }}
                      onRefresh={() => refreshExistingDeploys(selectedRunId)}
                    />
                  )}

                  {/* 변수 설정 */}
                  {selectedRunId && (
                    <div style={{ marginTop: 14 }}>
                      <div style={{ fontSize: "0.82rem", fontWeight: 600, marginBottom: 8 }}>
                        {loadingVars
                          ? "변수 로드 중…"
                          : `변수 설정${variables.length > 0 ? ` (${variables.length}개 — 기본값 사용 또는 override)` : " (없음)"}`}
                      </div>
                      <VariablesForm
                        variables={variables}
                        values={varValues}
                        onChange={(name, val) => setVarValues(prev => ({ ...prev, [name]: val }))}
                      />
                    </div>
                  )}
                </>
              )}
            </Modal>
          )}
        </div>
      )}

      {/* ── 2. 진행 중인 deploy ── */}
      {deploy && (
        <>
          {/* 다른 배포로 전환 (현재 배포는 백그라운드에서 계속 동작) */}
          <div style={{
            display: "flex", alignItems: "center", gap: 10,
            marginBottom: 10, fontSize: "0.78rem",
          }}>
            <button type="button"
              onClick={() => {
                setDeploy(null); setLogs([]); setLogOffset(0); setError(null);
                refreshExistingDeploys(selectedRunId);
              }}
              style={{
                background: "none", border: "1px solid var(--color-border)",
                color: "var(--color-text-light)", borderRadius: "var(--radius-sm)",
                padding: "4px 12px", fontSize: "0.78rem", cursor: "pointer",
              }}
              title="배포 자체는 그대로 두고 목록 화면으로 돌아가기 — 다른 배포를 보거나 새 배포를 시작할 수 있습니다">
              ← 다른 배포 / 새 배포 선택
            </button>
            <span style={{ color: "var(--color-text-light)" }}>
              현재: <code>{deploy.deploy_id?.slice(0, 8)}…</code>
            </span>
          </div>

          <PhaseStepper phase={phase} />

          {/* Phase별 패널 */}
          <div style={{
            padding: "16px 20px", marginBottom: 16,
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-sm)",
          }}>
            <div style={{ fontSize: "0.8rem", fontWeight: 700, marginBottom: 12 }}>
              {phase === "preflight"      && <span><span style={{ color: "#60a5fa" }}>●</span> 사전 점검</span>}
              {phase === "plan_running"   && <span><span style={{ color: "#60a5fa" }}>●</span> Plan 생성 중…</span>}
              {phase === "plan_ready"     && <span><span style={{ color: "var(--color-accent)" }}>●</span> Plan 완료 — 승인 대기</span>}
              {phase === "apply_running"  && <span><span style={{ color: "#60a5fa" }}>●</span> Apply 진행 중…</span>}
              {phase === "auto_fixing"    && <span><span style={{ color: "#a78bfa" }}>●</span> 🤖 AI 자동 수정 중… (최대 {3}회 재시도)</span>}
              {phase === "apply_failed"   && <span><span style={{ color: "#dc2626" }}>●</span> Apply 실패 — 수정 후 재시도 가능</span>}
              {phase === "applied"        && <span><span style={{ color: "#16a34a" }}>●</span> Apply 완료</span>}
              {phase === "data_migration" && <span><span style={{ color: "#d97706" }}>●</span> 데이터 이전</span>}
              {phase === "validating"     && <span><span style={{ color: "#60a5fa" }}>●</span> Azure 검증 중…</span>}
              {phase === "complete"       && <span><span style={{ color: "#16a34a" }}>●</span> ✓ 마이그레이션 완료</span>}
              {phase === "failed"         && <span><span style={{ color: "#dc2626" }}>●</span> 실패</span>}
              {phase === "cancelled"      && <span><span style={{ color: "#94a3b8" }}>●</span> 취소됨</span>}
            </div>

            {phase === "preflight" && deploy.preflight_result && (
              <PreflightPanel result={deploy.preflight_result} />
            )}

            {(phase === "plan_running") && (
              <div style={{ fontSize: "0.85rem", color: "var(--color-text-light)" }}>
                <span className="spinner" /> terraform init + plan 실행 중…
              </div>
            )}

            {phase === "plan_ready" && (
              <>
                {/* 자동 롤백 후 다시 plan_ready 진입 — 이전 실패 사유 알림 */}
                {deploy.last_apply_failure && (
                  <div style={{
                    marginBottom: 12, padding: "10px 14px",
                    background: "rgba(217,119,6,0.08)",
                    border: "1px solid #d97706",
                    borderRadius: "var(--radius-sm)",
                  }}>
                    <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "#d97706", marginBottom: 4 }}>
                      ⚠ 이전 apply 실패 후 자동 롤백되었습니다
                    </div>
                    <div style={{ fontSize: "0.78rem", color: "var(--color-text-light)" }}>
                      exit code {deploy.last_apply_failure.exit_code} · 부분 배포된 리소스는 destroy 됨.
                      그대로 다시 Apply 하면 같은 실패가 날 가능성이 큽니다 — 코드를 수정하거나 AI 진단을 먼저 받으세요.
                    </div>
                  </div>
                )}
                <PlanPreview
                  planOutput={deploy.plan_output}
                  onApprove={approve}
                  onCancel={cancel}
                  applying={approving}
                />
              </>
            )}

            {(phase === "apply_running" || phase === "applied" || phase === "validating" || phase === "auto_fixing") && (
              <div style={{ fontSize: "0.85rem", color: "var(--color-text-light)" }}>
                <span className="spinner" />
                {phase === "apply_running" && "terraform apply 진행 중…"}
                {phase === "auto_fixing"   && "AI가 코드를 분석하고 자동 수정 중… 실시간 로그에서 진행 상황 확인 가능"}
                {phase === "validating"    && "Azure 리소스 확인 중…"}
                {phase === "applied"       && "다음 단계 준비 중…"}
              </div>
            )}

            {phase === "data_migration" && (
              <DataMigrationChecklist
                deployId={deploy.deploy_id}
                scripts={deploy.data_migration_status || []}
                fullScripts={fullScripts}
                onComplete={completeStep}
                onSkip={skipDM}
              />
            )}

            {phase === "apply_failed" && (
              <ApplyFailedPanel
                deploy={{ ...deploy, logs }}
                onAiFix={async (strategy) => {
                  await requestAiFix(deploy.deploy_id, { strategy });
                }}
                onApplyFix={async (filesArr) => {
                  return await applyFix(deploy.deploy_id, filesArr);
                }}
                onRetry={async () => {
                  await retryDeployApply(deploy.deploy_id);
                }}
                onAbandon={async () => {
                  await abandonDeploy(deploy.deploy_id);
                }}
                onDestroyRestart={async (opts) => {
                  await destroyAndRestart(deploy.deploy_id, opts);
                }}
                onRefreshStatus={async () => {
                  // Force a status fetch so latest_ai_fix appears
                  const next = await getDeployV2Status(deploy.deploy_id, logOffset);
                  setDeploy(cur => cur ? { ...cur, ...next, log_lines: undefined } : cur);
                  if (Array.isArray(next.log_lines) && next.log_lines.length > 0) {
                    setLogs(prev => [...prev, ...next.log_lines]);
                    setLogOffset(next.log_total ?? logOffset + next.log_lines.length);
                  }
                }}
              />
            )}

            {phase === "complete" && (
              <ValidationPanel validation={deploy.validation} />
            )}
          </div>

          {/* 실시간 로그 */}
          <details style={{ marginBottom: 16 }} open={!["complete"].includes(phase)}>
            <summary style={{ cursor: "pointer", fontSize: "0.82rem", color: "var(--color-text-light)" }}>
              실시간 로그 ({logs.length} 줄)
            </summary>
            <div ref={logBoxRef} style={{
              marginTop: 8, padding: "10px 12px",
              background: "#0d1117", border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-sm)", maxHeight: 360, overflow: "auto",
              fontSize: "0.74rem", fontFamily: "monospace",
              whiteSpace: "pre-wrap",
            }}>
              {logs.join("\n") || "(아직 로그 없음)"}
            </div>
          </details>

          {/* 새 deploy 시작 버튼 (terminal 상태일 때만) */}
          {(phase === "complete" || phase === "failed" || phase === "cancelled") && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" onClick={() => { setDeploy(null); setLogs([]); setError(null); }}
                className="tab action-btn action-btn--secondary"
                style={{ minHeight: 36, padding: "0 18px" }}>
                ↻ 목록으로 돌아가기
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
