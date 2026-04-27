import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  startMigrationPlan,
  getMigrationStatus,
  getActiveMigrationJob,
  fetchAzureMappings,
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
          <summary>전체 계획 (Markdown)</summary>
          <div className="result-summary markdown-body">
            {result.final_output.split("\n").map((line, i) => (
              <p key={i}>{line || "\u00A0"}</p>
            ))}
          </div>
        </details>
      )}
      {showExecutionLog && result?.execution_log && (
        <details className="result-details">
          <summary>실행 로그</summary>
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

const ELLIPSIS_CELL = {
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

/** Common Azure region IDs (API / ARM ``location`` ids) for mapping & plan. */
const AZURE_TARGET_REGIONS = [
  { id: "eastus", label: "East US" },
  { id: "eastus2", label: "East US 2" },
  { id: "westus", label: "West US" },
  { id: "westus2", label: "West US 2" },
  { id: "westus3", label: "West US 3" },
  { id: "centralus", label: "Central US" },
  { id: "northcentralus", label: "North Central US" },
  { id: "southcentralus", label: "South Central US" },
  { id: "westcentralus", label: "West Central US" },
  { id: "canadacentral", label: "Canada Central" },
  { id: "canadaeast", label: "Canada East" },
  { id: "brazilsouth", label: "Brazil South" },
  { id: "mexicocentral", label: "Mexico Central" },
  { id: "northeurope", label: "North Europe" },
  { id: "westeurope", label: "West Europe" },
  { id: "uksouth", label: "UK South" },
  { id: "ukwest", label: "UK West" },
  { id: "francecentral", label: "France Central" },
  { id: "germanywestcentral", label: "Germany West Central" },
  { id: "norwayeast", label: "Norway East" },
  { id: "polandcentral", label: "Poland Central" },
  { id: "swedencentral", label: "Sweden Central" },
  { id: "switzerlandnorth", label: "Switzerland North" },
  { id: "italynorth", label: "Italy North" },
  { id: "spaincentral", label: "Spain Central" },
  { id: "australiaeast", label: "Australia East" },
  { id: "australiasoutheast", label: "Australia Southeast" },
  { id: "australiacentral", label: "Australia Central" },
  { id: "japaneast", label: "Japan East" },
  { id: "japanwest", label: "Japan West" },
  { id: "koreacentral", label: "Korea Central" },
  { id: "southeastasia", label: "Southeast Asia" },
  { id: "eastasia", label: "East Asia" },
  { id: "centralindia", label: "Central India" },
  { id: "southindia", label: "South India" },
  { id: "westindia", label: "West India" },
  { id: "uaenorth", label: "UAE North" },
  { id: "southafricanorth", label: "South Africa North" },
  { id: "israelcentral", label: "Israel Central" },
];

const rowKeyOf = (r) => r.arn || `${r.service}:${r.id}`;

function buildMappingPayloadRow(r) {
  return {
    aws_key: rowKeyOf(r),
    service: r.serviceDisplay || r.service,
    type: r.type,
    name: r.name,
    id: r.id,
    arn: r.arn,
    region: r.region,
    details: r.details || {},
    tags: r.tags || {},
  };
}

function TargetRegionPicker({ azureRegion, setAzureRegion, disabled }) {
  const trimmed = (azureRegion ?? "").trim();
  const known = AZURE_TARGET_REGIONS.some((z) => z.id === trimmed);
  const selectValue = known ? trimmed : "__custom__";

  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        fontSize: "0.82rem",
        color: "var(--color-text)",
        flexWrap: "wrap",
      }}
    >
      <span
        style={{ color: "var(--color-text-light)", whiteSpace: "nowrap" }}
      >
        Target region
      </span>
      <select
        value={selectValue}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "__custom__") setAzureRegion("");
          else setAzureRegion(v);
        }}
        disabled={disabled}
        style={{
          minHeight: 34,
          padding: "4px 8px",
          fontSize: "0.82rem",
          borderRadius: "var(--radius-sm)",
          border: "1px solid var(--color-border)",
          background: "var(--color-surface)",
          maxWidth: 260,
        }}
        title="Azure region for mapping (Retail API prices) and migration plan / Terraform"
        aria-label="Target Azure region"
      >
        {AZURE_TARGET_REGIONS.map((z) => (
          <option key={z.id} value={z.id}>
            {z.label} ({z.id})
          </option>
        ))}
        <option value="__custom__">
          {trimmed && !known ? `Custom: ${trimmed}` : "Custom region…"}
        </option>
      </select>
      {selectValue === "__custom__" && (
        <input
          type="text"
          value={azureRegion}
          onChange={(e) => setAzureRegion(e.target.value)}
          placeholder="Region ID (예: qatarcentral)"
          disabled={disabled}
          style={{
            minHeight: 34,
            padding: "4px 8px",
            fontSize: "0.82rem",
            width: 200,
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--color-border)",
          }}
          aria-label="Custom Azure region id"
        />
      )}
    </label>
  );
}

/** Max parallel ``POST /migration/azure-mapping`` calls (single-resource body). */
const MAPPING_CONCURRENCY = 10;

/**
 * Shared mapping hook: **one API call per resource**, with up to
 * ``MAPPING_CONCURRENCY`` in flight.  Pause aborts all in-flight requests.
 */
export function useAzureMapping(rows, azureRegion, sourceAwsRegion) {
  /** aws_key → mapping row from the backend */
  const [mapByKey, setMapByKey] = useState({});
  /** idle | running | paused | complete */
  const [phase, setPhase] = useState("idle");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  /** 0-based row indices with an in-flight mapping request */
  const [inFlightIndices, setInFlightIndices] = useState(() => new Set());
  const abortControllersRef = useRef([]);
  const pauseRequestedRef = useRef(false);
  const mapByKeyRef = useRef({});
  const sigRef = useRef("");

  const sig = useMemo(() => (rows || []).map(rowKeyOf).join("|"), [rows]);

  useEffect(() => {
    mapByKeyRef.current = mapByKey;
  }, [mapByKey]);

  const orderedMappings = useMemo(() => {
    if (!rows?.length) return [];
    return rows.map((r) => mapByKey[rowKeyOf(r)]).filter(Boolean);
  }, [rows, mapByKey]);

  const progress = useMemo(() => {
    const total = rows?.length || 0;
    const done = rows
      ? rows.reduce((n, r) => (mapByKey[rowKeyOf(r)] ? n + 1 : n), 0)
      : 0;
    return { done, total };
  }, [rows, mapByKey]);

  const mappingComplete =
    (rows?.length || 0) > 0 && progress.done === progress.total;

  // Reset when scope or target Azure region changes (pricing / SKUs are region-specific).
  useEffect(() => {
    setMapByKey({});
    setError(null);
    setPhase("idle");
    setInFlightIndices(new Set());
    pauseRequestedRef.current = false;
    sigRef.current = "";
  }, [sig, azureRegion]);

  useEffect(() => {
    if (!loading) return undefined;
    const started = Date.now();
    setElapsed(0);
    const id = setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(id);
  }, [loading]);

  useEffect(() => {
    return () => {
      abortControllersRef.current.forEach((c) => {
        try {
          c.abort();
        } catch {
          /* ignore */
        }
      });
      abortControllersRef.current = [];
    };
  }, []);

  function abortAllInFlightMapping() {
    abortControllersRef.current.forEach((c) => {
      try {
        c.abort();
      } catch {
        /* ignore */
      }
    });
    abortControllersRef.current = [];
  }

  const runPool = useCallback(
    async (reset) => {
      if (!rows?.length) return [];
      let merged = reset ? {} : { ...mapByKeyRef.current };
      if (reset) {
        setMapByKey({});
        merged = {};
        setPhase("idle");
      }
      pauseRequestedRef.current = false;
      setError(null);
      sigRef.current = sig;
      const targetRegion = azureRegion || "eastus";
      const sourceRegion = sourceAwsRegion || "";

      const pending = [];
      for (let i = 0; i < rows.length; i++) {
        const key = rowKeyOf(rows[i]);
        if (!merged[key]) pending.push(i);
      }

      if (pending.length === 0) {
        setPhase("complete");
        return rows.map((r) => merged[rowKeyOf(r)]).filter(Boolean);
      }

      const queue = [...pending];
      setLoading(true);
      setPhase("running");
      setInFlightIndices(new Set());

      let hardFail = null;

      const doRow = async (i) => {
        if (pauseRequestedRef.current) return;
        const key = rowKeyOf(rows[i]);
        const ctrl = new AbortController();
        abortControllersRef.current.push(ctrl);
        setInFlightIndices((prev) => new Set(prev).add(i));

        try {
          const res = await fetchAzureMappings({
            resources: [buildMappingPayloadRow(rows[i])],
            targetAzureRegion: targetRegion,
            sourceAwsRegion: sourceRegion,
            signal: ctrl.signal,
          });
          const one = (res.mappings || [])[0];
          if (one) {
            setMapByKey((prev) => {
              const next = { ...prev, [key]: one };
              mapByKeyRef.current = next;
              return next;
            });
          }
        } catch (e) {
          if (e.name === "AbortError") {
            return;
          }
          hardFail = e;
          pauseRequestedRef.current = true;
          abortAllInFlightMapping();
          setError(e.message || "Mapping 실패");
          setPhase("paused");
        } finally {
          abortControllersRef.current = abortControllersRef.current.filter(
            (c) => c !== ctrl,
          );
          setInFlightIndices((prev) => {
            const n = new Set(prev);
            n.delete(i);
            return n;
          });
        }
      };

      const worker = async () => {
        while (queue.length > 0) {
          if (pauseRequestedRef.current) break;
          const i = queue.shift();
          if (i === undefined) break;
          await doRow(i);
          if (hardFail) break;
        }
      };

      const nWorkers = Math.min(MAPPING_CONCURRENCY, pending.length);
      await Promise.all(Array.from({ length: nWorkers }, () => worker()));

      setInFlightIndices(new Set());
      abortAllInFlightMapping();
      setLoading(false);

      if (pauseRequestedRef.current && !hardFail) {
        setPhase("paused");
        setError(null);
        return rows
          .map((r) => mapByKeyRef.current[rowKeyOf(r)])
          .filter(Boolean);
      }

      if (hardFail) {
        return rows
          .map((r) => mapByKeyRef.current[rowKeyOf(r)])
          .filter(Boolean);
      }

      const allDone = rows.every((r) => mapByKeyRef.current[rowKeyOf(r)]);
      if (allDone) {
        setPhase("complete");
      } else {
        setPhase("paused");
      }
      return rows.map((r) => mapByKeyRef.current[rowKeyOf(r)]).filter(Boolean);
    },
    [rows, azureRegion, sourceAwsRegion, sig],
  );

  /**
   * Smart start / resume: fresh batch when nothing mapped yet; resume after
   * pause or partial failure; remap is a separate ``remap`` export.
   */
  const run = useCallback(async () => {
    if (!rows?.length) return [];
    const resume =
      phase === "paused" ||
      (progress.done > 0 && progress.done < progress.total);
    return runPool(!resume);
  }, [rows, phase, progress, runPool]);

  const remap = useCallback(async () => {
    if (!rows?.length) return [];
    return runPool(true);
  }, [rows, runPool]);

  const pause = useCallback(() => {
    pauseRequestedRef.current = true;
    abortControllersRef.current.forEach((c) => {
      try {
        c.abort();
      } catch {
        /* ignore */
      }
    });
    abortControllersRef.current = [];
  }, []);

  const ensure = useCallback(async () => {
    if (!rows?.length) return [];
    const keys = rows.map(rowKeyOf);
    const allPresent = keys.every((k) => mapByKeyRef.current[k]);
    if (allPresent && sigRef.current === sig) {
      return keys.map((k) => mapByKeyRef.current[k]);
    }
    return runPool(false);
  }, [rows, sig, runPool]);

  return {
    mappings: orderedMappings,
    mapByKey,
    loading,
    error,
    elapsed,
    phase,
    progress,
    inFlightIndices,
    mappingConcurrency: MAPPING_CONCURRENCY,
    mappingComplete,
    run,
    remap,
    pause,
    ensure,
  };
}

/**
 * Scope summary with mapping progress (up to ``mappingConcurrency`` parallel).
 */
function ScopeSummaryTable({
  rows,
  meta,
  mapping,
  onGoToDiscover,
  azureRegion,
  setAzureRegion,
}) {
  const {
    mappings,
    loading: mappingLoading,
    error: mappingError,
    elapsed,
    run: runMapping,
    remap: remapMapping,
    pause: pauseMapping,
    phase: mappingPhase,
    progress: mappingProgress,
    inFlightIndices: mappingInFlightIndices,
    mappingConcurrency,
    mappingComplete,
  } = mapping;

  const [expanded, setExpanded] = useState(() => new Set());

  const sig = useMemo(() => (rows || []).map(rowKeyOf).join("|"), [rows]);
  useEffect(() => {
    setExpanded(new Set());
  }, [sig]);

  // Auto-expand rows as each mapping arrives (merge — keeps manual toggles).
  useEffect(() => {
    if (mappings.length === 0) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      for (const m of mappings) {
        if (m?.aws_key) next.add(m.aws_key);
      }
      return next;
    });
  }, [mappings]);

  const pagination = usePagination(rows || [], 20);
  const { pageItems, start: pageStart } = pagination;

  const byKey = useMemo(() => {
    const m = new Map();
    for (const x of mappings) {
      if (x?.aws_key) m.set(x.aws_key, x);
    }
    return m;
  }, [mappings]);

  const toggle = (key) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (!rows || rows.length === 0) {
    return (
      <div
        className="empty-state"
        style={{ padding: "28px 20px", marginTop: 4 }}
      >
        <div className="icon">🔎</div>
        <p style={{ marginBottom: 12 }}>
          아직 선택된 리소스가 없습니다. 먼저 Discover &amp; Select에서 범위를
          골라 주세요.
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
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 6,
        }}
      >
        <div
          style={{ color: "var(--color-text-light)", fontSize: "0.82rem" }}
        >
          Region:{" "}
          {meta?.region && (
            <strong style={{ color: "var(--color-text)" }}>
              {meta.region}
            </strong>
          )}
          {meta?.resourceGroup && (
            <>
              {" / "}
              <strong style={{ color: "var(--color-text)" }}>
                {meta.resourceGroup}
              </strong>
            </>
          )}
          {" — "} Resources: {" "}
          <strong style={{ color: "var(--color-text)" }}>{rows.length}</strong>
          {" "} items
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <TargetRegionPicker
            azureRegion={azureRegion}
            setAzureRegion={setAzureRegion}
            disabled={mappingLoading}
          />
          {(mappingLoading || mappingProgress.done > 0) && (
            <span
              style={{
                fontSize: "0.78rem",
                color: "var(--color-text-light)",
                fontVariantNumeric: "tabular-nums",
              }}
              title="Mapping 진행 상황"
            >
              {mappingProgress.done}/{mappingProgress.total}
              {mappingLoading &&
                mappingInFlightIndices?.size > 0 &&
                ` · 동시 ${mappingInFlightIndices.size}건 (≤${mappingConcurrency})`}
              {mappingLoading && (
                <span style={{ marginLeft: 8 }} title="경과 시간(초)">
                  {elapsed}s
                </span>
              )}
            </span>
          )}
          <button
            type="button"
            className="tab action-btn action-btn--secondary"
            onClick={runMapping}
            disabled={mappingLoading || mappingComplete}
            style={{ minHeight: 34, padding: "0 14px", fontSize: "0.82rem" }}
            title={
              mappingComplete
                ? "범위 내 리소스 Mapping이 모두 완료되었습니다"
                : "리소스별 Mapping 실행(일시 중지·재개 가능)"
            }
          >
            {mappingLoading ? (
              <>
                <span className="spinner" />
                Mapping…
              </>
            ) : mappingComplete ? (
              <>✓ Mapping complete</>
            ) : mappingPhase === "paused" && !mappingComplete ? (
              <>▶ Resume</>
            ) : (
              <>✨ Mapping</>
            )}
          </button>
          {mappingLoading && (
            <button
              type="button"
              className="tab action-btn action-btn--secondary"
              onClick={pauseMapping}
              style={{ minHeight: 34, padding: "0 14px", fontSize: "0.82rem" }}
              title="현재 항목 처리가 끝나면 일시 중지합니다"
            >
              ⏸ Pause
            </button>
          )}
          {mappingComplete && !mappingLoading && (
            <button
              type="button"
              className="tab action-btn action-btn--secondary"
              onClick={() => remapMapping()}
              style={{ minHeight: 34, padding: "0 14px", fontSize: "0.82rem" }}
              title="Mapping을 초기화하고 첫 리소스부터 다시 실행합니다"
            >
              ↻ Re-map
            </button>
          )}
        </div>
      </div>

      {mappingError && (
        <div
          className="form-error"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
            marginBottom: 8,
          }}
        >
          <span style={{ flex: 1, minWidth: 200 }}>{mappingError}</span>
          <button
            type="button"
            className="tab action-btn action-btn--secondary"
            onClick={runMapping}
            disabled={mappingLoading}
            style={{ minHeight: 30, padding: "0 12px", fontSize: "0.78rem" }}
          >
            ↻ Retry
          </button>
        </div>
      )}

      <div className="table-wrapper analysis-result-table">
        <table style={{ tableLayout: "fixed", width: "100%" }}>
          <colgroup>
            <col style={{ width: 36 }} />
            <col style={{ width: 140 }} />
            <col style={{ width: 150 }} />
            <col />
            <col />
            <col style={{ width: 140 }} />
          </colgroup>
          <thead>
            <tr>
              <th></th>
              <th>Service</th>
              <th>Type</th>
              <th>Name</th>
              <th>Identifier</th>
              <th>Region</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((r, idxOnPage) => {
              const key = rowKeyOf(r);
              const globalIdx = pageStart + idxOnPage;
              const rowMapping = byKey.get(key);
              const canExpand = !!rowMapping;
              const isOpen = canExpand && expanded.has(key);
              const rowInFlight =
                mappingLoading &&
                !rowMapping &&
                mappingInFlightIndices &&
                mappingInFlightIndices.has(globalIdx);
              return (
                <React.Fragment key={key}>
                  <tr
                    onClick={() => canExpand && toggle(key)}
                    style={{
                      cursor: canExpand ? "pointer" : "default",
                      background: isOpen
                        ? "var(--color-surface-hover)"
                        : rowInFlight
                          ? "rgba(59, 130, 246, 0.06)"
                          : undefined,
                    }}
                  >
                    <td
                      style={{
                        textAlign: "center",
                        color: "var(--color-text-light)",
                        userSelect: "none",
                      }}
                      aria-label={isOpen ? "collapse" : "expand"}
                    >
                      {rowInFlight ? (
                        <span className="spinner" title="Mapping…" />
                      ) : canExpand ? (
                        isOpen ? (
                          "▾"
                        ) : (
                          "▸"
                        )
                      ) : (
                        ""
                      )}
                    </td>
                    <td style={ELLIPSIS_CELL} title={r.serviceDisplay}>
                      <span style={{ marginRight: 6 }}>{r.icon}</span>
                      <strong>{r.serviceDisplay}</strong>
                    </td>
                    <td style={ELLIPSIS_CELL} title={r.type || ""}>
                      {r.type || "—"}
                    </td>
                    <td
                      style={{ ...ELLIPSIS_CELL, fontWeight: 500 }}
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
                        ...ELLIPSIS_CELL,
                        fontFamily: "monospace",
                        fontSize: "0.78rem",
                      }}
                      title={r.arn || r.id || ""}
                    >
                      {r.id || "—"}
                    </td>
                    <td
                      style={{
                        ...ELLIPSIS_CELL,
                        fontSize: "0.82rem",
                        color: "var(--color-text-light)",
                      }}
                      title={r.region || ""}
                    >
                      {r.region || "—"}
                    </td>
                  </tr>
                  {isOpen && rowMapping && (
                    <tr>
                      <td
                        colSpan={6}
                        style={{
                          background: "var(--color-bg)",
                          padding: "12px 20px 14px 44px",
                          borderTop: "1px solid var(--color-border)",
                        }}
                      >
                        <MappingDetail mapping={rowMapping} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
        <Pagination {...pagination} />
      </div>
    </div>
  );
}

function formatUsd(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (n === 0) return "$0.00";
  if (Math.abs(n) < 0.01) return `$${n.toFixed(4)}`;
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

function formatDelta(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${formatUsd(Math.abs(n))}`;
}

function PriceCell({ label, price }) {
  const missing = !price || price.monthly_usd === null || price.monthly_usd === undefined;
  return (
    <div
      style={{
        flex: "1 1 200px",
        minWidth: 180,
        padding: "10px 12px",
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-sm)",
      }}
    >
      <div
        style={{
          fontSize: "0.7rem",
          fontWeight: 600,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: "var(--color-text-light)",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: "1.05rem",
          fontWeight: 600,
          fontVariantNumeric: "tabular-nums",
          color: missing ? "var(--color-text-light)" : "var(--color-text)",
        }}
      >
        {missing ? "N/A" : `${formatUsd(price.monthly_usd)} / mo`}
      </div>
      {price?.sku_resolved && (
        <div
          style={{
            fontSize: "0.74rem",
            color: "var(--color-text-light)",
            marginTop: 2,
          }}
        >
          <code>{price.sku_resolved}</code>
          {price.region && ` · ${price.region}`}
        </div>
      )}
      {price?.hourly_usd != null && (
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--color-text-light)",
            marginTop: 2,
          }}
        >
          {formatUsd(price.hourly_usd)} / hr
        </div>
      )}
      {price?.note && (
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--color-text-light)",
            marginTop: 4,
            lineHeight: 1.3,
          }}
        >
          {price.note}
        </div>
      )}
    </div>
  );
}

function PricingBlock({ mapping }) {
  const aws = mapping.aws_price;
  const azure = mapping.azure_price;
  const delta =
    typeof mapping.monthly_delta_usd === "number"
      ? mapping.monthly_delta_usd
      : null;

  // Bail cleanly if we have nothing useful to show.
  if (!aws && !azure) return null;

  const assumptions = [];
  if (aws?.assumptions) assumptions.push(`AWS: ${aws.assumptions}`);
  if (azure?.assumptions) assumptions.push(`Azure: ${azure.assumptions}`);
  const asOf = aws?.as_of || azure?.as_of;

  return (
    <div>
      <div
        style={{
          fontSize: "0.72rem",
          fontWeight: 600,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: "var(--color-text-light)",
          marginBottom: 4,
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <span>월 예상 비용(PAYG)</span>
        {asOf && (
          <span
            style={{
              fontWeight: 400,
              textTransform: "none",
              letterSpacing: 0,
              color: "var(--color-text-light)",
              fontSize: "0.7rem",
            }}
            title={asOf}
          >
            · 기준일 {String(asOf).slice(0, 10)}
          </span>
        )}
      </div>
      <div
        style={{
          display: "flex",
          gap: 10,
          flexWrap: "wrap",
          alignItems: "stretch",
        }}
      >
        <PriceCell label="AWS (current)" price={aws} />
        <PriceCell label="Azure (target)" price={azure} />
        <div
          style={{
            flex: "0 0 160px",
            padding: "10px 12px",
            background:
              delta === null
                ? "var(--color-surface)"
                : delta > 0
                  ? "rgba(220, 38, 38, 0.06)"
                  : "rgba(22, 163, 74, 0.08)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          <div
            style={{
              fontSize: "0.7rem",
              fontWeight: 600,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              color: "var(--color-text-light)",
              marginBottom: 4,
            }}
          >
            월 차액
          </div>
          <div
            style={{
              fontSize: "1.05rem",
              fontWeight: 700,
              fontVariantNumeric: "tabular-nums",
              color:
                delta === null
                  ? "var(--color-text-light)"
                  : delta > 0
                    ? "#b91c1c"
                    : "#15803d",
            }}
          >
            {formatDelta(delta)}
          </div>
          <div
            style={{
              fontSize: "0.72rem",
              color: "var(--color-text-light)",
              marginTop: 2,
            }}
          >
            {delta === null
              ? "양쪽 가격이 모두 필요합니다"
              : delta > 0
                ? "Azure 비용이 더 큼"
                : delta < 0
                  ? "Azure가 더 저렴"
                  : "동일"}
          </div>
        </div>
      </div>
      {(assumptions.length > 0 || aws?.source || azure?.source) && (
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--color-text-light)",
            marginTop: 6,
            lineHeight: 1.4,
          }}
        >
          {assumptions.length > 0 && <div>가정 · {assumptions.join(" | ")}</div>}
          <div>
            Source ·{" "}
            {aws?.source && <code>{aws.source}</code>}
            {aws?.source && azure?.source && " + "}
            {azure?.source && <code>{azure.source}</code>}
          </div>
        </div>
      )}
    </div>
  );
}

function MappingDetail({ mapping }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div>
        <div
          style={{
            fontSize: "0.72rem",
            fontWeight: 600,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            color: "var(--color-text-light)",
            marginBottom: 4,
          }}
        >
          Azure target
        </div>
        <div style={{ fontSize: "0.9rem", fontWeight: 500 }}>
          {mapping.azure_service || "—"}
          {mapping.azure_resource_type && (
            <span
              style={{
                marginLeft: 8,
                fontFamily:
                  "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: "0.78rem",
                color: "var(--color-text-light)",
              }}
            >
              ({mapping.azure_resource_type})
            </span>
          )}
          {mapping.azure_sku_suggestion && (
            <span
              style={{
                marginLeft: 8,
                fontSize: "0.75rem",
                color: "var(--color-text-light)",
              }}
            >
              SKU: <code>{mapping.azure_sku_suggestion}</code>
            </span>
          )}
        </div>
      </div>
      <PricingBlock mapping={mapping} />
      <div>
        <div
          style={{
            fontSize: "0.72rem",
            fontWeight: 600,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            color: "var(--color-text-light)",
            marginBottom: 4,
          }}
        >
          선정 근거
        </div>
        <div
          style={{
            fontSize: "0.85rem",
            color: "var(--color-text)",
            lineHeight: 1.45,
          }}
        >
          {mapping.rationale || (
            <em style={{ color: "var(--color-text-light)" }}>
              근거 텍스트가 없습니다.
            </em>
          )}
        </div>
        {mapping.caveats && (
          <div
            style={{
              marginTop: 6,
              fontSize: "0.8rem",
              color: "var(--color-text-light)",
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderLeft: "3px solid var(--color-accent)",
              padding: "6px 10px",
              borderRadius: "var(--radius-sm)",
            }}
          >
            ⚠ {mapping.caveats}
          </div>
        )}
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
  mapping,
}) {
  return (
    <section className="page-section">
      <h2 className="page-title">🧭 Plan</h2>
      <p className="page-desc">
        Discover &amp; Select에서 고른 범위와 Target region을 확인한 뒤 제출하세요. 에이전트가
        구조화된 마이그레이션 계획과 바로 쓸 수 있는 Azure Terraform 모듈을 함께 반환하며,
        결과는 <code>backend/outputs/</code>에 저장됩니다.
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
        mapping={mapping}
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
  mapping,
}) {
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [prepMessage, setPrepMessage] = useState(null);

  const pollStatus = useCallback(() => {
    if (!jobId) return;
    getMigrationStatus(jobId)
      .then((res) => {
        setStatus(res);
        if (res.status === "pending" || res.status === "running") {
          setTimeout(pollStatus, 2000);
        }
      })
      .catch(() => setError("상태 갱신에 실패했습니다"));
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

  const handleRun = async () => {
    if (isRunning) return;
    setError(null);
    setStatus(null);
    setPrepMessage(null);

    // Step 1 — ensure per-resource AWS→Azure mappings exist for the current
    // scope.  This is the same call the "Mapping" button makes; we reuse the
    // cache if the user already ran it.  Feeding these to the planner keeps
    // the generated Terraform aligned with what the user reviewed on screen.
    let mappingsForPlanner = [];
    const hasScope = (scopedRows || []).length > 0;
    if (hasScope) {
      try {
        if (!mapping.mappingComplete) {
          setPrepMessage("리소스를 Azure 대상으로 Mapping 하는 중…");
        }
        mappingsForPlanner = await mapping.ensure();
      } catch (e) {
        if (e.name === "AbortError") {
          setPrepMessage(null);
          return;
        }
        setError(
          `Plan 전에 리소스 Mapping에 실패했습니다: ${e.message || e}. 위 표에서 Mapping을 다시 시도해 주세요.`,
        );
        setPrepMessage(null);
        return;
      }
    }

    setPrepMessage(null);

    try {
      const res = await startMigrationPlan({
        aws_resource_spec: awsSpec.trim(),
        target_azure_region: azureRegion.trim() || "eastus",
        migration_goals: goals.trim(),
        azure_mappings: mappingsForPlanner,
      });
      setJobId(res.job_id);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="run-analysis-form">
      <div className="form-section">
        <label>AWS resources and scope</label>
        <ScopeSummaryTable
          rows={scopedRows}
          meta={scopedMeta}
          mapping={mapping}
          onGoToDiscover={onGoToDiscover}
          azureRegion={azureRegion}
          setAzureRegion={setAzureRegion}
        />
        <p
          style={{
            marginTop: 8,
            fontSize: "0.78rem",
            color: "var(--color-text-light)",
          }}
        >
          위 내용은 사전 Azure Mapping 결과입니다. Plan 시 결과가 달라질 수 있습니다.
        </p>
      </div>

      {error && <div className="form-error">{error}</div>}

      <div className="action-bar">
        <button
          className="run-btn action-btn"
          type="button"
          onClick={handleRun}
          disabled={isRunning || mapping.loading || !awsSpec.trim()}
        >
          {mapping.loading && !isRunning ? (
            <>
              <span className="spinner" />
              Mapping Azure targets...
            </>
          ) : isRunning ? (
            <>
              <span className="spinner" />
              {status?.status === "running" ? "Planning..." : "Starting..."}
            </>
          ) : (
            <>🚀 Plan</>
          )}
        </button>
        {prepMessage && !isRunning && (
          <span
            style={{
              marginLeft: 12,
              fontSize: "0.82rem",
              color: "var(--color-text-light)",
            }}
          >
            {prepMessage}
          </span>
        )}
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
            Planner에 보낸 원문 스펙 보기
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
