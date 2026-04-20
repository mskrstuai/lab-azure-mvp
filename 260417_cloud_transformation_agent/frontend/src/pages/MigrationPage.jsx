import { useCallback, useEffect, useState } from "react";
import {
  startMigrationPlan,
  getMigrationStatus,
  getActiveMigrationJob,
} from "../api/apiClient";
import Pagination, { usePagination } from "../components/Pagination";
import TerraformViewer from "../components/TerraformViewer";

function PlanResultView({ result, runId, showExecutionLog = false }) {
  const jd = result?.json_data;
  const hasSteps = jd?.steps?.length > 0;
  const tfFiles = Array.isArray(jd?.terraform) ? jd.terraform : [];

  return (
    <div className="analysis-result-view">
      {tfFiles.length > 0 && <TerraformViewer files={tfFiles} runId={runId} />}
      {hasSteps && (
        <div className="result-section">
          <h3 className="result-section-title">Phases ({jd.steps.length})</h3>
          <div className="table-wrapper analysis-result-table">
            <table>
              <thead>
                <tr>
                  <th>Phase</th>
                  <th>Description</th>
                  <th>Azure targets</th>
                </tr>
              </thead>
              <tbody>
                {jd.steps.map((s, i) => (
                  <tr key={i}>
                    <td><strong>{s.phase}</strong></td>
                    <td>{s.description}</td>
                    <td>{(s.azure_targets || []).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {result?.final_output && (
        <details className="result-details" open>
          <summary>Full plan (markdown)</summary>
          <div className="result-summary markdown-body">
            {result.final_output.split("\n").map((line, i) => (
              <p key={i}>{line || "\u00A0"}</p>
            ))}
          </div>
        </details>
      )}
      {showExecutionLog && result?.execution_log && (
        <details className="result-details">
          <summary>Execution log</summary>
          <pre className="log-pre">
            {Array.isArray(result.execution_log)
              ? result.execution_log.join("\n")
              : result.execution_log}
          </pre>
        </details>
      )}
      {jd && !hasSteps && (
        <details className="result-details">
          <summary>Raw JSON</summary>
          <pre>{JSON.stringify(jd, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

/**
 * Compact, read-only summary of the rows pushed from Discover & Select.
 * Replaces the old free-form textarea: the planner still receives the text
 * spec (held in ``awsSpec``) — this table is just a visual confirmation of
 * what's in scope.
 */
function ScopeSummaryTable({ rows, meta, onGoToDiscover }) {
  const pagination = usePagination(rows || [], 20);
  const { pageItems, start } = pagination;

  if (!rows || rows.length === 0) {
    return (
      <div
        className="empty-state"
        style={{ padding: "28px 20px", marginTop: 4 }}
      >
        <div className="icon">🔎</div>
        <p style={{ marginBottom: 12 }}>
          No resources selected yet. Pick a scope on Discover &amp; Select
          first.
        </p>
        {onGoToDiscover && (
          <button
            type="button"
            className="tab action-btn action-btn--secondary"
            onClick={onGoToDiscover}
          >
            ➜ Go to Discover &amp; Select
          </button>
        )}
      </div>
    );
  }

  return (
    <div>
      <div
        style={{
          color: "var(--color-text-light)",
          fontSize: "0.82rem",
          marginBottom: 6,
        }}
      >
        Scope:{" "}
        {meta?.region && (
          <strong style={{ color: "var(--color-text)" }}>{meta.region}</strong>
        )}
        {meta?.resourceGroup && (
          <>
            {" / "}
            <strong style={{ color: "var(--color-text)" }}>
              {meta.resourceGroup}
            </strong>
          </>
        )}
        {" — "}
        <strong style={{ color: "var(--color-text)" }}>{rows.length}</strong>{" "}
        resource(s)
      </div>
      <div className="table-wrapper analysis-result-table">
        <table style={{ tableLayout: "fixed", width: "100%" }}>
          <colgroup>
            <col style={{ width: 140 }} />
            <col style={{ width: 150 }} />
            <col />
            <col />
            <col style={{ width: 140 }} />
          </colgroup>
          <thead>
            <tr>
              <th>Service</th>
              <th>Type</th>
              <th>Name</th>
              <th>Identifier</th>
              <th>Region</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((r, pi) => (
              <tr key={`${r.service}:${r.arn || r.id || start + pi}`}>
                <td
                  style={{
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={r.serviceDisplay}
                >
                  <span style={{ marginRight: 6 }}>{r.icon}</span>
                  <strong>{r.serviceDisplay}</strong>
                </td>
                <td
                  style={{
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={r.type || ""}
                >
                  {r.type || "—"}
                </td>
                <td
                  style={{
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    fontWeight: 500,
                  }}
                  title={r.name || ""}
                >
                  {r.name || (
                    <span
                      style={{
                        color: "var(--color-text-light)",
                        fontStyle: "italic",
                      }}
                    >
                      (not tagged)
                    </span>
                  )}
                </td>
                <td
                  style={{
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    fontFamily: "monospace",
                    fontSize: "0.78rem",
                  }}
                  title={r.arn || r.id || ""}
                >
                  {r.id || "—"}
                </td>
                <td
                  style={{
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    fontSize: "0.82rem",
                    color: "var(--color-text-light)",
                  }}
                  title={r.region || ""}
                >
                  {r.region || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination {...pagination} />
      </div>
    </div>
  );
}

function MigrationPage({
  awsSpec,
  setAwsSpec,
  azureRegion,
  setAzureRegion,
  goals,
  setGoals,
  scopedRows,
  scopedMeta,
  onGoToDiscover,
}) {
  return (
    <section className="page-section">
      <h2 className="page-title">🧭 Plan</h2>
      <p className="page-desc">
        Review the scope you picked on Discover &amp; Select, pick a target
        Azure region, and submit. The agent returns a structured migration
        plan <em>and</em> a ready-to-deploy Azure Terraform module, saved
        under <code>backend/outputs/</code>.
      </p>

      <RunMigrationForm
        awsSpec={awsSpec}
        setAwsSpec={setAwsSpec}
        azureRegion={azureRegion}
        setAzureRegion={setAzureRegion}
        goals={goals}
        setGoals={setGoals}
        scopedRows={scopedRows}
        scopedMeta={scopedMeta}
        onGoToDiscover={onGoToDiscover}
      />
    </section>
  );
}

function RunMigrationForm({
  awsSpec,
  setAwsSpec,
  azureRegion,
  setAzureRegion,
  goals,
  setGoals,
  scopedRows,
  scopedMeta,
  onGoToDiscover,
}) {
  const [outputFormat, setOutputFormat] = useState("json");
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  const pollStatus = useCallback(() => {
    if (!jobId) return;
    getMigrationStatus(jobId)
      .then((res) => {
        setStatus(res);
        if (res.status === "pending" || res.status === "running") {
          setTimeout(pollStatus, 2000);
        }
      })
      .catch(() => setError("Failed to poll status"));
  }, [jobId]);

  useEffect(() => {
    if (jobId) pollStatus();
  }, [jobId, pollStatus]);

  useEffect(() => {
    getActiveMigrationJob()
      .then((res) => {
        if (res.job_id) setJobId(res.job_id);
      })
      .catch(() => {});
  }, []);

  const isRunning =
    !!jobId && status?.status !== "completed" && status?.status !== "failed";

  const handleRun = () => {
    if (isRunning) return;
    setError(null);
    setStatus(null);
    startMigrationPlan({
      aws_resource_spec: awsSpec.trim(),
      target_azure_region: azureRegion.trim() || "eastus",
      migration_goals: goals.trim(),
      output_format: outputFormat,
    })
      .then((res) => setJobId(res.job_id))
      .catch((e) => setError(e.message));
  };

  return (
    <div className="run-analysis-form">
      <div className="form-section">
        <label>AWS resources and scope</label>
        <ScopeSummaryTable
          rows={scopedRows}
          meta={scopedMeta}
          onGoToDiscover={onGoToDiscover}
        />
      </div>
      <div className="form-row">
        <div className="form-field">
          <label>Target Azure region</label>
          <input
            type="text"
            value={azureRegion}
            onChange={(e) => setAzureRegion(e.target.value)}
            placeholder="eastus"
          />
        </div>
        <div className="form-field">
          <label>Output format</label>
          <select
            value={outputFormat}
            onChange={(e) => setOutputFormat(e.target.value)}
          >
            <option value="json">Markdown + structured JSON</option>
            <option value="plain_text">Plain narrative + JSON</option>
          </select>
        </div>
      </div>
      {error && <div className="form-error">{error}</div>}

      <div className="action-bar">
        <button
          className="run-btn action-btn"
          type="button"
          onClick={handleRun}
          disabled={isRunning || !awsSpec.trim()}
        >
          {isRunning ? (
            <>
              <span className="spinner" />
              {status?.status === "running" ? "Planning..." : "Starting..."}
            </>
          ) : (
            <>🚀 Run migration plan</>
          )}
        </button>
      </div>

      {/* Surface the raw spec (useful for debugging what's sent to the LLM)
          behind a collapsed details — keeps the page clean by default. */}
      {awsSpec?.trim() && (
        <details style={{ marginTop: 12 }}>
          <summary
            style={{
              cursor: "pointer",
              color: "var(--color-text-light)",
              fontSize: "0.82rem",
            }}
          >
            Show raw spec sent to the planner
          </summary>
          <pre
            style={{
              marginTop: 8,
              padding: 12,
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-sm)",
              fontSize: "0.78rem",
              whiteSpace: "pre-wrap",
              maxHeight: 240,
              overflow: "auto",
            }}
          >
            {awsSpec}
          </pre>
        </details>
      )}

      {status?.status === "completed" && status?.result && (
        <PlanResultView
          result={status.result}
          runId={status.result?.artifacts?.run_id}
        />
      )}
      {status?.status === "failed" && (
        <div className="form-error">
          <strong>Planning failed:</strong> {status.error}
        </div>
      )}
    </div>
  );
}

export default MigrationPage;
