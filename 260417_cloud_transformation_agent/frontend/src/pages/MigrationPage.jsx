import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  startMigrationPlan,
  getMigrationStatus,
  getActiveMigrationJob,
  fetchAzureMappings,
  fetchMigrationOutputs,
  discoverRelevantPolicies,
  addPolicyGuidanceEntry,
  updatePolicyGuidanceEntry,
  deletePolicyGuidanceEntry,
  draftPolicyGuidance,
  setPolicyGuidanceSelected,
  listGeneralGuidance,
  addGeneralGuidance,
  updateGeneralGuidance,
  deleteGeneralGuidance,
  deletePlanOutput,
  generateDataMigrationScripts,
  listSelectedPlans,
  getSelectedPlan,
  updateSelectedPlan,
  deleteSelectedPlan,
  bulkDeleteSelectedPlans,
} from "../api/apiClient";
import Pagination, { usePagination } from "../components/Pagination";
import TerraformViewer from "../components/TerraformViewer";

/* ── 데이터 이전 스크립트 섹션 ────────────────────────────────────────
   scopedRows에 RDS / S3 / ElastiCache 가 포함되어 있으면 자동으로
   해당 데이터 이전 커맨드(pg_dump, AzCopy, redis RDB 등)를 표시한다.
   Plan 결과 옆에 독립 블록으로 항상 표시.
─────────────────────────────────────────────────────────────────── */

const DATA_RESOURCE_TYPES = new Set(["rds", "s3", "elasticache"]);

function DataMigrationSection({ scopedRows, azureRegion }) {
  const [scripts, setScripts] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  const dataResources = useMemo(() =>
    (scopedRows || [])
      .filter(r => DATA_RESOURCE_TYPES.has((r._type || r.service || "").toLowerCase()))
      .map(r => ({
        _type:    (r._type || r.service || "").toLowerCase(),
        id:       r.id,
        name:     r.name,
        arn:      r.arn,
        engine:   r.details?.engine,
        endpoint: r.details?.endpoint,
        runtime:  r.details?.runtime,
      })),
    [scopedRows]
  );

  // 리소스가 변경되면 자동 재실행
  useEffect(() => {
    if (!dataResources.length) {
      setScripts(null);
      return;
    }
    setLoading(true); setError(null);
    generateDataMigrationScripts({ resources: dataResources, azureRegion })
      .then(setScripts)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [dataResources, azureRegion]);

  if (!dataResources.length) return null;

  return (
    <details className="result-details" open>
      <summary>
        🟡 데이터 이전 스크립트 ({dataResources.length}개 리소스 · Terraform 적용 후 별도 실행)
        {loading && <span className="spinner" style={{ marginLeft: 8, width: 12, height: 12 }} />}
      </summary>

      {error && <div className="form-error" style={{ margin: "8px 0" }}>{error}</div>}

      {!loading && !error && scripts?.scripts?.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 8 }}>
          {scripts.scripts.map((s, i) => (
            <div key={i} style={{
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-sm)",
              overflow: "hidden",
            }}>
              <div style={{
                padding: "9px 14px",
                background: "rgba(217,119,6,0.08)",
                borderBottom: "1px solid var(--color-border)",
                fontSize: "0.85rem", fontWeight: 600,
              }}>
                {s.title}
                <span style={{
                  marginLeft: 8, fontWeight: 400,
                  color: "var(--color-text-light)", fontSize: "0.78rem",
                }}>
                  — {s.resource}
                </span>
              </div>

              <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
                {s.steps.map((step, si) => (
                  <div key={si}>
                    <div style={{ fontSize: "0.74rem", color: "var(--color-text-light)", marginBottom: 4 }}>
                      {step.label}
                    </div>
                    <pre style={{
                      margin: 0, padding: "8px 12px",
                      background: "#0d1117", borderRadius: "var(--radius-sm)",
                      fontSize: "0.78rem", fontFamily: "monospace",
                      color: "#00d4aa", overflowX: "auto",
                      whiteSpace: "pre-wrap", wordBreak: "break-all",
                    }}>
                      {step.command}
                    </pre>
                  </div>
                ))}
                {s.notes && (
                  <div style={{
                    fontSize: "0.76rem", color: "var(--color-text-light)",
                    borderLeft: "2px solid var(--color-accent)", paddingLeft: 10,
                    marginTop: 4,
                  }}>
                    💡 {s.notes}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

export function MappingSummaryTable({ mappings }) {
  const rows = (mappings || []).filter(Boolean);
  const tco = useMemo(() => {
    let aws = 0, azure = 0, withPrices = 0;
    for (const m of rows) {
      const a = m?.aws_price?.monthly_usd;
      const z = m?.azure_price?.monthly_usd;
      if (typeof a === "number" && typeof z === "number") {
        aws += a; azure += z; withPrices += 1;
      }
    }
    return { aws, azure, withPrices, delta: azure - aws };
  }, [rows]);

  if (!rows.length) return null;

  const fmt = (n) => typeof n === "number"
    ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : "—";

  return (
    <div style={{
      marginBottom: 12, padding: "12px 14px",
      background: "var(--color-bg)", border: "1px solid var(--color-border)",
      borderRadius: "var(--radius-sm)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
        <strong style={{ fontSize: "0.9rem" }}>🔁 리소스 매핑 ({rows.length}개)</strong>
        {tco.withPrices > 0 && (
          <>
            <span style={{ fontSize: "0.78rem", color: "var(--color-text-light)" }}>
              월 비용 추정 (가격 비교 가능 {tco.withPrices}개): AWS <strong>{fmt(tco.aws)}</strong> →
              Azure <strong>{fmt(tco.azure)}</strong> · 차이 <strong style={{
                color: tco.delta < 0 ? "#16a34a" : tco.delta > 0 ? "#d97706" : "var(--color-text)",
              }}>{tco.delta >= 0 ? "+" : ""}{fmt(tco.delta)}</strong>
            </span>
          </>
        )}
      </div>
      <div style={{
        border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)",
        overflow: "auto", maxHeight: 380,
      }}>
        <table style={{
          width: "100%", borderCollapse: "collapse", fontSize: "0.78rem",
        }}>
          <thead style={{ background: "var(--color-surface)", position: "sticky", top: 0 }}>
            <tr>
              <th style={_th}>AWS</th>
              <th style={_th}>Type</th>
              <th style={_th}>스펙</th>
              <th style={_th}>→ Azure</th>
              <th style={_th}>Resource</th>
              <th style={_th}>SKU</th>
              <th style={{..._th, textAlign:"right"}}>AWS / 월</th>
              <th style={{..._th, textAlign:"right"}}>Azure / 월</th>
              <th style={{..._th, textAlign:"right"}}>차이</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m, i) => {
              const aws = m?.aws_price?.monthly_usd;
              const az  = m?.azure_price?.monthly_usd;
              const delta = (typeof aws === "number" && typeof az === "number") ? az - aws : null;
              return (
                <tr key={i} style={{ borderTop: "1px solid var(--color-border)" }}>
                  <td style={_td} title={m?.aws_key}>{m?.aws_name || m?.aws_key || "—"}</td>
                  <td style={_td}>{m?.aws_type || "—"}</td>
                  <td style={{..._td, color:"var(--color-text-light)"}}>
                    {m?.aws_spec ? Object.entries(m.aws_spec).slice(0,2).map(([k,v]) => `${k}:${v}`).join(", ") : "—"}
                  </td>
                  <td style={_td}>{m?.azure_service || "—"}</td>
                  <td style={{..._td, fontFamily:"monospace", fontSize:"0.74rem"}}>{m?.azure_resource_type || "—"}</td>
                  <td style={{..._td, fontFamily:"monospace", fontSize:"0.74rem"}}>{m?.azure_sku_suggestion || "—"}</td>
                  <td style={{..._td, textAlign:"right"}}>{fmt(aws)}</td>
                  <td style={{..._td, textAlign:"right"}}>{fmt(az)}</td>
                  <td style={{..._td, textAlign:"right",
                    color: delta == null ? "var(--color-text-light)"
                      : delta < 0 ? "#16a34a" : delta > 0 ? "#d97706" : "var(--color-text)",
                    fontWeight: delta != null ? 600 : 400,
                  }}>
                    {delta == null ? "—" : `${delta >= 0 ? "+" : ""}${fmt(delta)}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const _th = {
  textAlign: "left", padding: "6px 10px", fontSize: "0.72rem",
  color: "var(--color-text-light)", fontWeight: 700,
  borderBottom: "1px solid var(--color-border)",
  whiteSpace: "nowrap",
};
const _td = {
  padding: "6px 10px", fontSize: "0.78rem",
  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
  maxWidth: 220,
};


function PlanResultView({ result, runId, architecture, mappings, scopedRows, azureRegion, showExecutionLog = false }) {
  const jd = result?.json_data;
  const tfFiles = Array.isArray(jd?.terraform) ? jd.terraform : [];
  const v2      = jd?.v2;
  const validationPassed = result?.validation_passed ?? v2?.validation_passed;
  const pipeline = result?.pipeline || (v2 ? "v2" : "v1");

  const moduleNames = (v2?.terraform_modules || []).map(m => m.name).filter(Boolean);

  return (
    <div className="analysis-result-view">
      {/* 1. 출력 토폴로지 시각화 (Azure) */}
      {architecture && (
        <div style={{ marginBottom: 12, padding: "12px 14px", background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)" }}>
          <TopologyView architecture={architecture} mappings={mappings} side="azure" title="🟦 Azure 토폴로지 (Terraform 적용 결과)" />
        </div>
      )}

      {/* 2. 매핑 결과 (가격 비교) */}
      <MappingSummaryTable mappings={mappings} />

      {/* 3. Terraform 코드 — file browser (validation 배너는 viewer 헤더 아래) */}
      {tfFiles.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <TerraformViewer
            files={tfFiles}
            runId={runId}
            validationPassed={pipeline === "v2" ? validationPassed : null}
            moduleNames={moduleNames}
          />
        </div>
      )}

      {/* 4. 데이터 이전 스크립트 */}
      <DataMigrationSection scopedRows={scopedRows} azureRegion={azureRegion} />

      {showExecutionLog && result?.execution_log && (
        <details className="result-details" style={{ marginTop: 8 }}>
          <summary>실행 로그</summary>
          <pre className="log-pre">
            {Array.isArray(result.execution_log)
              ? result.execution_log.join("\n")
              : result.execution_log}
          </pre>
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
          color: "var(--color-text)",
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
            color: "var(--color-text)",
            background: "var(--color-surface)",
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
export function useAzureMapping(rows, azureRegion, sourceAwsRegion, targetSubscriptionId = "", seedMappingsRef = null) {
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
  // If a one-shot seedMappingsRef has been pre-loaded by the caller (e.g. when
  // restoring a saved plan from DB), populate mapByKey from it instead of
  // clearing — this is what makes the Mapping/Plan-수립 buttons usable after a
  // browser refresh.  The ref is consumed (set to null) so the next sig change
  // doesn't re-seed stale data.
  useEffect(() => {
    setError(null);
    setPhase("idle");
    setInFlightIndices(new Set());
    pauseRequestedRef.current = false;
    sigRef.current = "";

    const seed = seedMappingsRef?.current;
    if (seed && seed.length) {
      seedMappingsRef.current = null;  // consume
      const next = {};
      for (const m of seed) {
        if (m && m.aws_key) next[m.aws_key] = m;
      }
      setMapByKey(next);
      mapByKeyRef.current = next;
      setPhase((rows?.length || 0) > 0 && Object.keys(next).length === rows.length ? "complete" : "idle");
    } else {
      setMapByKey({});
      mapByKeyRef.current = {};
    }
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
            targetSubscriptionId,
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
/* ── Cost insight helpers ─────────────────────────────────────────── */

const COST_CAT_META = {
  savings:       { color: "#16a34a", bg: "rgba(22,163,74,0.10)",  border: "#16a34a", icon: "💰", label: "절감" },
  premium:       { color: "#d97706", bg: "rgba(217,119,6,0.10)",  border: "#d97706", icon: "📈", label: "추가 비용" },
  neutral:       { color: "#94a3b8", bg: "rgba(148,163,184,0.08)",border: "var(--color-border)", icon: "≈",  label: "동등" },
  "usage-based": { color: "#60a5fa", bg: "rgba(96,165,250,0.08)", border: "var(--color-border)", icon: "📊", label: "종량제" },
  free:          { color: "var(--color-text-light)", bg: "transparent", border: "var(--color-border)", icon: "○", label: "무료" },
};

/** Aggregate TCO from accumulated mappings (matches backend _compute_tco_summary). */
function computeTcoSummary(mappings) {
  let totalAws = 0, totalAzure = 0;
  let totalAzure1yr = 0, totalAzure3yr = 0;
  let hasRi1yr = false, hasRi3yr = false;
  let compared = 0, usageBased = 0, freeCount = 0;
  const savingsNames = [], premiumNames = [];
  const tipsAccum = [];

  for (const m of mappings || []) {
    if (!m) continue;
    const a = m.aws_price?.monthly_usd;
    const z = m.azure_price?.monthly_usd;
    const z1 = m.azure_price?.monthly_1yr_ri_usd;
    const z3 = m.azure_price?.monthly_3yr_ri_usd;

    if (typeof a === "number" && typeof z === "number") {
      totalAws += a;
      totalAzure += z;
      // RI fallback to on-demand if SKU has no RI price
      if (typeof z1 === "number") { totalAzure1yr += z1; hasRi1yr = true; } else { totalAzure1yr += z; }
      if (typeof z3 === "number") { totalAzure3yr += z3; hasRi3yr = true; } else { totalAzure3yr += z; }

      if (a === 0 && z === 0) {
        freeCount++;
      } else {
        compared++;
        const cat = m.cost_insight?.category;
        const name = m.aws_name || m.aws_key || "";
        if (cat === "savings") savingsNames.push(name);
        else if (cat === "premium") premiumNames.push(name);
      }
    } else {
      usageBased++;
    }

    for (const tip of (m.cost_tips || [])) {
      if (tip && !tipsAccum.includes(tip)) tipsAccum.push(tip);
    }
  }

  const monthlySave    = totalAws - totalAzure;
  const monthlySave1yr = totalAws - totalAzure1yr;
  const monthlySave3yr = totalAws - totalAzure3yr;
  const pct    = totalAws > 0 ? (monthlySave    / totalAws) * 100 : 0;
  const pct1yr = totalAws > 0 ? (monthlySave1yr / totalAws) * 100 : 0;
  const pct3yr = totalAws > 0 ? (monthlySave3yr / totalAws) * 100 : 0;

  return {
    totalAws, totalAzure, totalAzure1yr, totalAzure3yr,
    monthlySave, monthlySave1yr, monthlySave3yr,
    pct, pct1yr, pct3yr,
    annualSave: monthlySave * 12,
    threeYrSave: monthlySave * 36,
    annualSave1yr: monthlySave1yr * 12,
    threeYrSave3yr: monthlySave3yr * 36,
    hasRi1yr, hasRi3yr,
    compared, usageBased, freeCount,
    total: mappings?.length || 0,
    savingsNames, premiumNames,
    aggregatedTips: tipsAccum.slice(0, 8),
  };
}

/** TCO summary banner — workload-wide cost comparison with RI scenarios. */
function TcoSummaryBanner({ summary }) {
  if (!summary || summary.compared === 0) return null;

  const isSavings  = summary.monthlySave > 0;
  const isPremium  = summary.monthlySave < 0;
  const accentCol  = isSavings ? "#16a34a" : isPremium ? "#d97706" : "#94a3b8";
  const headlineBg = isSavings ? "rgba(22,163,74,0.10)" : isPremium ? "rgba(217,119,6,0.10)" : "var(--color-surface)";

  return (
    <div style={{
      marginBottom: 12,
      border: `1px solid ${accentCol}`,
      borderRadius: "var(--radius-sm)",
      overflow: "hidden",
      background: headlineBg,
    }}>
      {/* Top headline — On-demand */}
      <div style={{ padding: "14px 18px 12px" }}>
        <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-light)", marginBottom: 6 }}>
          💰 마이그레이션 비용 분석 (On-Demand)
        </div>
        <div style={{
          display: "flex", alignItems: "baseline", gap: 14,
          fontSize: "1.5rem", fontWeight: 700, fontVariantNumeric: "tabular-nums",
        }}>
          <span style={{ color: "var(--color-text-light)", fontWeight: 500 }}>
            ${summary.totalAws.toFixed(2)}/월
          </span>
          <span style={{ fontSize: "1rem", color: "var(--color-text-light)" }}>→</span>
          <span style={{ color: accentCol }}>
            ${summary.totalAzure.toFixed(2)}/월
          </span>
          <span style={{
            fontSize: "0.78rem", fontWeight: 600, padding: "3px 10px",
            borderRadius: 99, background: accentCol, color: "#0d1117",
            marginLeft: 8,
          }}>
            {isSavings ? `▼ ${summary.pct.toFixed(1)}%` : isPremium ? `▲ ${Math.abs(summary.pct).toFixed(1)}%` : "동등"}
          </span>
        </div>
      </div>

      {/* On-demand stats grid */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        gap: 1, background: "var(--color-border)",
        borderTop: "1px solid var(--color-border)",
      }}>
        <Stat label="월 절감액"    value={isSavings ? `$${summary.monthlySave.toFixed(2)}` : isPremium ? `−$${Math.abs(summary.monthlySave).toFixed(2)}` : "$0.00"} accent={accentCol} />
        <Stat label="연 절감액"    value={isSavings ? `$${summary.annualSave.toFixed(0)}`  : isPremium ? `−$${Math.abs(summary.annualSave).toFixed(0)}`  : "$0"}    accent={accentCol} bold />
        <Stat label="3년 누적"     value={isSavings ? `$${summary.threeYrSave.toFixed(0)}` : isPremium ? `−$${Math.abs(summary.threeYrSave).toFixed(0)}` : "$0"}    accent={accentCol} />
        <Stat label="비교 가능"    value={`${summary.compared}/${summary.total}개`} />
      </div>

      {/* Reserved Instance scenarios (long-term commitment savings) */}
      {(summary.hasRi1yr || summary.hasRi3yr) && (
        <div style={{
          padding: "12px 18px",
          borderTop: "1px solid var(--color-border)",
          background: "rgba(0,212,170,0.04)",
        }}>
          <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-accent)", marginBottom: 8 }}>
            🎯 Reserved Instance 적용 시 추가 절감
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {summary.hasRi1yr && (
              <RiScenarioCard
                title="1년 약정"
                azure={summary.totalAzure1yr}
                monthly={summary.monthlySave1yr}
                annual={summary.annualSave1yr}
                pct={summary.pct1yr}
                aws={summary.totalAws}
              />
            )}
            {summary.hasRi3yr && (
              <RiScenarioCard
                title="3년 약정 (최대 절감)"
                azure={summary.totalAzure3yr}
                monthly={summary.monthlySave3yr}
                annual={summary.threeYrSave3yr}
                pct={summary.pct3yr}
                aws={summary.totalAws}
                highlight
              />
            )}
          </div>
        </div>
      )}

      {/* Aggregated cost-optimization tips */}
      {summary.aggregatedTips?.length > 0 && (
        <div style={{
          padding: "10px 18px",
          borderTop: "1px solid var(--color-border)",
          background: "rgba(96,165,250,0.05)",
        }}>
          <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#60a5fa", marginBottom: 6 }}>
            💡 추가 비용 최적화 옵션
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: "0.78rem", color: "var(--color-text)", lineHeight: 1.6 }}>
            {summary.aggregatedTips.map((tip, i) => <li key={i}>{tip}</li>)}
          </ul>
        </div>
      )}

      {/* Premium resources warning */}
      {summary.premiumNames.length > 0 && (
        <div style={{ padding: "8px 18px", fontSize: "0.78rem", color: "#d97706", borderTop: "1px solid var(--color-border)", background: "rgba(217,119,6,0.04)" }}>
          ⚠ Azure가 더 비싼 리소스: <strong>{summary.premiumNames.slice(0, 3).join(", ")}</strong>
          {summary.premiumNames.length > 3 && ` 외 ${summary.premiumNames.length - 3}개`}
        </div>
      )}
    </div>
  );
}

/** A small RI-scenario card showing monthly Azure cost + savings vs on-demand AWS. */
function RiScenarioCard({ title, azure, monthly, annual, pct, aws, highlight }) {
  const positive = monthly > 0;
  const accent = positive ? "#16a34a" : "#d97706";
  return (
    <div style={{
      padding: "10px 14px",
      background: highlight ? "rgba(22,163,74,0.08)" : "var(--color-surface)",
      border: highlight ? `1px solid ${accent}` : "1px solid var(--color-border)",
      borderRadius: "var(--radius-sm)",
    }}>
      <div style={{ fontSize: "0.72rem", fontWeight: 600, color: "var(--color-text-light)", marginBottom: 4 }}>
        {title}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 4 }}>
        <span style={{ fontSize: "1.1rem", fontWeight: 700, color: accent, fontVariantNumeric: "tabular-nums" }}>
          ${azure.toFixed(2)}/월
        </span>
        <span style={{ fontSize: "0.72rem", color: "var(--color-text-light)" }}>
          (vs ${aws.toFixed(2)} AWS)
        </span>
      </div>
      <div style={{ fontSize: "0.78rem", color: accent, fontWeight: 600 }}>
        {positive
          ? `▼ ${pct.toFixed(1)}% · 월 $${monthly.toFixed(2)} 절감`
          : `▲ ${Math.abs(pct).toFixed(1)}%`}
      </div>
      <div style={{ fontSize: "0.7rem", color: "var(--color-text-light)", marginTop: 2 }}>
        {title.includes("3년")
          ? `3년 누적 $${annual.toFixed(0)}`
          : `연 $${annual.toFixed(0)} 절감`}
      </div>
    </div>
  );
}

function Stat({ label, value, accent, bold }) {
  return (
    <div style={{
      padding: "10px 14px",
      background: "var(--color-surface)",
      display: "flex", flexDirection: "column", gap: 3,
    }}>
      <div style={{ fontSize: "0.7rem", color: "var(--color-text-light)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}
      </div>
      <div style={{
        fontSize: bold ? "1.1rem" : "0.95rem", fontWeight: 700, fontVariantNumeric: "tabular-nums",
        color: accent || "var(--color-text)",
      }}>
        {value}
      </div>
    </div>
  );
}

/** Inline cost-insight badge shown next to the price, in MappingDetail. */
function CostInsightBadge({ insight }) {
  if (!insight?.headline) return null;
  const meta = COST_CAT_META[insight.category] || COST_CAT_META.neutral;
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 10px", borderRadius: 99,
      background: meta.bg, border: `1px solid ${meta.border}`,
      fontSize: "0.78rem", fontWeight: 600, color: meta.color,
    }}>
      <span>{meta.icon}</span>
      <span>{insight.headline}</span>
    </div>
  );
}


/* ── Topology visualization ──────────────────────────────────────
   AWS 아키텍처(입력)와 Azure 아키텍처(출력)를 동일한 트리 구조로 그립니다.
   리소스 매핑(SKU 등)은 Azure 트리에 함께 표시.
─────────────────────────────────────────────────────────────────── */

function _slug(s) {
  return (s || "").replace(/[^a-zA-Z0-9_]/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "").toLowerCase() || "x";
}
function _stgName(s) {
  return (s || "").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 24) || "stor";
}

const RES_ICON = {
  ec2: "🖥", rds: "🗄", elb: "⚖", lambda: "λ", s3: "🪣", ecs: "🧩",
  vm: "🖥", db: "🗄", lb: "⚖", fn: "λ", storage: "💾", aks: "🧩",
};

/** Convert a single AWS resource into an Azure equivalent (uses Mapping when available). */
function awsResourceToAzure(r, mappingByKey) {
  const m = mappingByKey.get(r.arn) || mappingByKey.get(r.id) || {};
  const t = (r._type || "").toLowerCase();
  if (t === "ec2") {
    return {
      kind: "vm",
      label: "VM",
      name: r.name || r.id,
      sub:  m.azure_sku_suggestion || (r.instance_type ? `Standard_B (mapping pending)` : "VM"),
      tfType: "azurerm_linux_virtual_machine",
    };
  }
  if (t === "rds") {
    const isMy = (r.engine || "").toLowerCase().includes("mysql");
    return {
      kind: "db",
      label: isMy ? "Azure DB MySQL" : "Azure DB PostgreSQL",
      name: r.id,
      sub:  m.azure_sku_suggestion || "B_Standard_B1ms",
      tfType: m.azure_resource_type || (isMy ? "azurerm_mysql_flexible_server" : "azurerm_postgresql_flexible_server"),
    };
  }
  if (t === "elb" || t === "elasticloadbalancing") {
    return { kind: "lb", label: "Application Gateway", name: r.name, sub: r.type || "ALB", tfType: "azurerm_application_gateway" };
  }
  if (t === "lambda") {
    return { kind: "fn", label: "Function App", name: r.name, sub: r.runtime || "linux", tfType: "azurerm_linux_function_app" };
  }
  if (t === "ecs") {
    return { kind: "aks", label: "Container App", name: r.name, sub: "container-app", tfType: "azurerm_container_app" };
  }
  return { kind: t || "res", label: m.azure_service || t.toUpperCase(), name: r.name || r.id, sub: m.azure_sku_suggestion || "" };
}

function buildAwsTree(arch) {
  if (!arch) return { vpcs: [], global: [] };
  const vpcs = (arch.networking || []).map(v => ({
    id: v.id, name: v.name || v.id, cidr: v.cidr,
    subnets: (v.subnets || []).map(s => ({
      id: s.id, name: s.name || s.id, cidr: s.cidr, az: s.az, public: !!s.public,
      resources: (s.resources || []).map(r => ({
        kind: (r._type || "res").toLowerCase(),
        label: (r._type || "RES").toUpperCase(),
        name:  r.name || r.id,
        sub:   r.instance_type || r.engine || r.runtime || r.type || "",
      })),
    })),
    direct: (v.direct_resources || []).map(r => ({
      kind: (r._type || "res").toLowerCase(),
      label: (r._type || "RES").toUpperCase(),
      name:  r.name || r.id,
      sub:   r.engine || r.type || r.runtime || "",
    })),
    sgs: (v.security_groups || []).map(sg => ({
      id: sg.id, name: sg.name, rules: (sg.ingress || []).length + (sg.egress || []).length,
    })),
  }));
  const global = [
    ...(arch.s3  || []).map(b => ({ kind: "s3",  label: "S3 Bucket", name: b.name })),
    ...(arch.ecs || []).map(c => ({ kind: "ecs", label: "ECS Cluster", name: c.name })),
  ];
  return { vpcs, global };
}

function buildAzureTree(arch, mappings) {
  if (!arch) return { vpcs: [], global: [] };
  const byKey = new Map();
  for (const m of mappings || []) {
    if (m.aws_key) byKey.set(m.aws_key, m);
  }
  const vpcs = (arch.networking || []).map(v => ({
    id: _slug(v.name || v.id),
    name: `${v.name || v.id}-vnet`,
    cidr: v.cidr,
    subnets: (v.subnets || []).map(s => ({
      id: _slug(s.name || s.id),
      name: s.name || s.id,
      cidr: s.cidr, az: s.az, public: !!s.public,
      resources: (s.resources || []).map(r => awsResourceToAzure(r, byKey)),
    })),
    direct: (v.direct_resources || []).map(r => awsResourceToAzure(r, byKey)),
    sgs: (v.security_groups || []).map(sg => ({
      id: _slug(sg.name || sg.id),
      name: `${sg.name}-nsg`,
      rules: (sg.ingress || []).length + (sg.egress || []).length,
    })),
  }));
  const global = [
    ...(arch.s3  || []).map(b => ({ kind: "storage", label: "Storage Account", name: _stgName(b.name), sourceName: b.name })),
    ...(arch.ecs || []).map(c => ({ kind: "aks",     label: "Container App",   name: c.name })),
  ];
  return { vpcs, global };
}

function ResChip({ item, side }) {
  const accent = side === "azure" ? "#00d4aa" : "#fb923c";
  const icon = RES_ICON[item.kind] || "•";
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 8px", borderRadius: "var(--radius-sm)",
      background: side === "azure" ? "rgba(0,212,170,0.06)" : "rgba(251,146,60,0.06)",
      border: `1px solid ${side === "azure" ? "rgba(0,212,170,0.3)" : "rgba(251,146,60,0.3)"}`,
      fontSize: "0.74rem", whiteSpace: "nowrap", maxWidth: "100%",
    }}>
      <span>{icon}</span>
      <span style={{ color: accent, fontWeight: 600, fontSize: "0.68rem", textTransform: "uppercase", letterSpacing: "0.03em" }}>{item.label}</span>
      <strong style={{ color: "var(--color-text)" }}>{item.name}</strong>
      {item.sub && <span style={{ color: "var(--color-text-light)", fontFamily: "monospace", fontSize: "0.7rem" }}>{item.sub}</span>}
    </div>
  );
}

function VpcDiagram({ vpc, side }) {
  const accent = side === "azure" ? "#00d4aa" : "#fb923c";
  const label  = side === "azure" ? "VNet" : "VPC";
  const totalRes =
    vpc.subnets.reduce((n, s) => n + (s.resources || []).length, 0)
    + (vpc.direct || []).length;

  return (
    <div style={{
      border: `1px solid ${accent}`,
      borderRadius: "var(--radius-sm)",
      background: side === "azure" ? "rgba(0,212,170,0.03)" : "rgba(251,146,60,0.03)",
      padding: "10px 12px", marginBottom: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.95rem" }}>🌐</span>
        <span style={{ fontSize: "0.7rem", fontWeight: 700, color: accent, letterSpacing: "0.05em", textTransform: "uppercase" }}>{label}</span>
        <strong style={{ fontSize: "0.85rem" }}>{vpc.name}</strong>
        {vpc.cidr && <code style={{ fontSize: "0.72rem", color: "var(--color-text-light)" }}>{vpc.cidr}</code>}
        <span style={{ marginLeft: "auto", fontSize: "0.72rem", color: "var(--color-text-light)" }}>{totalRes}개 리소스</span>
      </div>

      {/* Subnets with resources */}
      {vpc.subnets.filter(s => (s.resources || []).length > 0).map((s, i) => (
        <div key={i} style={{
          marginLeft: 12, paddingLeft: 12,
          borderLeft: `2px solid ${accent}40`,
          paddingTop: 4, paddingBottom: 4,
        }}>
          <div style={{ fontSize: "0.76rem", color: "var(--color-text-light)", marginBottom: 4 }}>
            📡 <strong style={{ color: "var(--color-text)" }}>{s.name}</strong>
            {s.cidr && <span style={{ marginLeft: 6, fontFamily: "monospace" }}>{s.cidr}</span>}
            {s.az && <span style={{ marginLeft: 6 }}>· {s.az}</span>}
            {" · "}
            <span style={{ color: s.public ? "#f59e0b" : "#94a3b8" }}>{s.public ? "PUBLIC" : "PRIVATE"}</span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, paddingLeft: 16 }}>
            {(s.resources || []).map((r, j) => <ResChip key={j} item={r} side={side} />)}
          </div>
        </div>
      ))}

      {/* VPC-level direct resources (RDS, ELB) */}
      {(vpc.direct || []).length > 0 && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px dashed ${accent}40` }}>
          <div style={{ fontSize: "0.7rem", color: "var(--color-text-light)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            VPC-level
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {vpc.direct.map((r, j) => <ResChip key={j} item={r} side={side} />)}
          </div>
        </div>
      )}

      {/* Security groups summary */}
      {(vpc.sgs || []).length > 0 && (
        <div style={{ marginTop: 6, fontSize: "0.7rem", color: "var(--color-text-light)" }}>
          🔒 {side === "azure" ? "NSG" : "Security Group"}: {vpc.sgs.map(sg => sg.name).join(", ")}
        </div>
      )}
    </div>
  );
}

export function TopologyView({ architecture, mappings, side, title }) {
  const tree = side === "azure"
    ? buildAzureTree(architecture, mappings)
    : buildAwsTree(architecture);

  if (!tree.vpcs.length && !tree.global.length) {
    return (
      <div style={{ padding: "20px", textAlign: "center", fontSize: "0.82rem", color: "var(--color-text-light)" }}>
        토폴로지 데이터가 없습니다.
      </div>
    );
  }

  return (
    <div>
      {title && (
        <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: side === "azure" ? "#00d4aa" : "#fb923c", marginBottom: 8 }}>
          {title}
        </div>
      )}
      {tree.vpcs.map((vpc, i) => <VpcDiagram key={i} vpc={vpc} side={side} />)}
      {tree.global.length > 0 && (
        <div style={{
          padding: "10px 12px",
          border: `1px dashed ${side === "azure" ? "#00d4aa" : "#fb923c"}40`,
          borderRadius: "var(--radius-sm)",
        }}>
          <div style={{ fontSize: "0.7rem", color: "var(--color-text-light)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            글로벌 리소스 (VPC 외부)
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {tree.global.map((r, j) => <ResChip key={j} item={r} side={side} />)}
          </div>
        </div>
      )}
    </div>
  );
}


function ScopeSummaryTable({
  rows,
  meta,
  mapping,
  architecture,
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
          리소스{" "}
          <strong style={{ color: "var(--color-text)" }}>{rows.length}</strong>
          개
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
            className="run-btn action-btn"
            onClick={runMapping}
            disabled={mappingLoading || mappingComplete}
            style={{ minHeight: 34, padding: "0 20px", fontSize: "0.82rem", fontWeight: 600 }}
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
              className="action-btn action-btn--secondary"
              onClick={pauseMapping}
              style={{ minHeight: 34, padding: "0 14px", fontSize: "0.82rem" }}
              title="현재 항목 처리가 끝나면 일시 중지합니다"
            >
              ⏸ Pause
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

      {/* 💰 워크로드 전체 TCO 요약 — 비교 가능한 매핑이 1개 이상일 때 표시 */}
      <TcoSummaryBanner summary={computeTcoSummary(mappings)} />

      {/* ── 입력 토폴로지 시각화 (AWS) ── */}
      {architecture && (
        <div style={{ marginTop: 12, marginBottom: 12, padding: "12px 14px", background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)" }}>
          <TopologyView architecture={architecture} side="aws" title="🟧 AWS 토폴로지 (Plan에 입력될 데이터)" />
        </div>
      )}

      {/* 리소스/매핑 상세 테이블은 보조 정보로 접어둔다 */}
      <details style={{ marginTop: 8 }}>
        <summary style={{ cursor: "pointer", fontSize: "0.8rem", color: "var(--color-text-light)", padding: "4px 0" }}>
          리소스별 매핑 상세 (가격·SKU·근거)
        </summary>
      <div className="table-wrapper analysis-result-table" style={{ marginTop: 8 }}>
        <table style={{ tableLayout: "fixed", width: "100%" }}>
          <colgroup>
            <col style={{ width: 36 }} />
            <col style={{ width: 120 }} />
            <col />
            <col />
            <col style={{ width: 140 }} />
          </colgroup>
          <thead>
            <tr>
              <th></th>
              <th>Service</th>
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
                    <td style={ELLIPSIS_CELL} title={r.service || r._type || ""}>
                      <strong>{(r._type || r.service || "—").toUpperCase()}</strong>
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
                        colSpan={5}
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
      </details>
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
      {/* Reserved Instance pricing (Azure only — AWS pricing path doesn't fetch RI here) */}
      {(price?.monthly_1yr_ri_usd != null || price?.monthly_3yr_ri_usd != null) && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px dashed var(--color-border)" }}>
          {price.monthly_1yr_ri_usd != null && (
            <div style={{ fontSize: "0.72rem", color: "var(--color-text-light)", display: "flex", justifyContent: "space-between" }}>
              <span>1y RI</span>
              <span style={{ color: "#16a34a", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                {formatUsd(price.monthly_1yr_ri_usd)} / mo
              </span>
            </div>
          )}
          {price.monthly_3yr_ri_usd != null && (
            <div style={{ fontSize: "0.72rem", color: "var(--color-text-light)", display: "flex", justifyContent: "space-between" }}>
              <span>3y RI</span>
              <span style={{ color: "#16a34a", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
                {formatUsd(price.monthly_3yr_ri_usd)} / mo
              </span>
            </div>
          )}
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
      {/* 💰 비용 인사이트 — 매핑별 절감 메시지 */}
      {mapping.cost_insight?.headline && (
        <div>
          <CostInsightBadge insight={mapping.cost_insight} />
        </div>
      )}
      {/* 💡 비용 최적화 팁 (per-resource) */}
      {(mapping.cost_tips || []).length > 0 && (
        <div style={{
          background: "rgba(96,165,250,0.06)",
          border: "1px solid rgba(96,165,250,0.3)",
          borderRadius: "var(--radius-sm)",
          padding: "8px 12px",
        }}>
          <div style={{ fontSize: "0.7rem", fontWeight: 700, color: "#60a5fa", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            💡 비용 최적화 팁
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: "0.8rem", color: "var(--color-text)", lineHeight: 1.6 }}>
            {mapping.cost_tips.map((tip, i) => <li key={i}>{tip}</li>)}
          </ul>
        </div>
      )}
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

/* ── Confirm modal (in-page, no browser confirm()) ──────── */

function ConfirmModal({ title, body, confirmLabel = "확인", cancelLabel = "취소",
                       danger = false, busy = false, onConfirm, onCancel }) {
  // Esc to cancel
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !busy) onCancel(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel, busy]);

  return (
    <div
      onClick={() => !busy && onCancel()}
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
          width: "min(540px, 100%)",
          boxShadow: "0 16px 48px rgba(0,0,0,0.45)",
          overflow: "hidden",
        }}>
        <div style={{
          padding: "12px 18px",
          borderBottom: "1px solid var(--color-border)",
          background: "var(--color-bg)",
          fontWeight: 700, fontSize: "0.95rem",
        }}>
          {title}
        </div>
        <div style={{ padding: "16px 18px", fontSize: "0.85rem", lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
          {body}
        </div>
        <div style={{
          display: "flex", gap: 8, padding: "12px 18px",
          borderTop: "1px solid var(--color-border)",
          background: "var(--color-bg)", justifyContent: "flex-end",
        }}>
          <button type="button" onClick={onCancel} disabled={busy}
            className="tab action-btn action-btn--secondary"
            style={{ minHeight: 34, padding: "0 18px" }}>
            {cancelLabel}
          </button>
          <button type="button" onClick={onConfirm} disabled={busy}
            className={danger ? undefined : "run-btn action-btn"}
            style={{
              minHeight: 34, padding: "0 18px",
              background: danger ? "#dc2626" : undefined,
              color: danger ? "#fff" : undefined,
              border: danger ? "1px solid #dc2626" : undefined,
              borderRadius: danger ? "var(--radius-sm)" : undefined,
              cursor: busy ? "not-allowed" : "pointer",
              fontSize: "0.85rem",
              fontWeight: 600,
            }}>
            {busy ? "처리 중…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}


/* ── Plans master-detail page ────────────────────────────── */

const SAVED_PLANS_KEY = "migrationPlans:v1";

function _loadSavedPlans() {
  try {
    const raw = localStorage.getItem(SAVED_PLANS_KEY);
    const arr = JSON.parse(raw || "[]");
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function _persistSavedPlans(plans) {
  try {
    localStorage.setItem(SAVED_PLANS_KEY, JSON.stringify(plans));
  } catch {
    /* quota / disabled storage — ignore */
  }
}

function _hashScope(scopedRows, scopedMeta) {
  // Cheap fingerprint to dedupe identical Discovery→Plan handoffs.
  const ids = (scopedRows || []).map(r => r.arn || `${r.service}:${r.id}`).sort().join(",");
  return `${scopedMeta?.account_id || ""}|${scopedMeta?.region || ""}|${ids}`;
}

const PLAN_STATUS_META = {
  selected: { color: "#d97706", label: "🟡 Selected",   hint: "Discovery 에서 선택만 됨 — 매핑 필요" },
  mapping:  { color: "#60a5fa", label: "🔁 Mapping",    hint: "리소스 매핑 진행 중" },
  mapped:   { color: "#3b82f6", label: "🟢 Mapped",     hint: "리소스 매핑 완료 — Plan 수립 가능" },
  planning: { color: "#a855f7", label: "⚙️ Planning",   hint: "Terraform 모듈 + 데이터 이전 스크립트 생성 중" },
  ready:    { color: "#16a34a", label: "✓ 수립 완료",   hint: "Terraform 모듈 + 스크립트 생성됨, Deploy 가능" },
};

function _formatRelative(ts) {
  if (!ts) return "?";
  const diff = Math.max(0, Date.now() / 1000 - ts);
  if (diff < 60)    return `${Math.floor(diff)}초 전`;
  if (diff < 3600)  return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

function _formatDate(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function _scanScopeLabel({ discovery_mode, resource_group, scoped_meta }) {
  // scoped_meta: { resourceGroup, mode, tagFilters? }
  const mode = discovery_mode || scoped_meta?.mode || "architecture";
  const rg   = resource_group || scoped_meta?.resourceGroup;
  if (rg) return `RG: ${rg}`;
  const tags = scoped_meta?.tagFilters || scoped_meta?.tag_filters;
  if (tags && typeof tags === "object") {
    const pairs = Object.entries(tags).map(([k, v]) => `${k}=${v}`).join(", ");
    if (pairs) return `Tag: ${pairs}`;
  }
  if (mode === "tag") return "Tag (전체)";
  return "전체 (architecture)";
}

function RowActionMenu({ items }) {
  // items = [{label, onClick, danger?, disabled?}]
  const [open, setOpen] = useState(false);
  const [pos, setPos]   = useState(null);    // {top, left} for portal-style placement
  const btnRef = useRef(null);
  const popRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e) => {
      if (popRef.current?.contains(e.target)) return;
      if (btnRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    const onScroll = () => setOpen(false);   // close on any scroll/resize
    document.addEventListener("mousedown", onClick);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("mousedown", onClick);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open]);

  const toggle = () => {
    if (open) { setOpen(false); return; }
    const r = btnRef.current?.getBoundingClientRect();
    if (!r) { setOpen(true); return; }
    const menuH = 36 * items.length + 8;
    const menuW = 160;
    // Flip up if not enough room below
    const top = (r.bottom + menuH > window.innerHeight - 8)
      ? Math.max(8, r.top - menuH - 4)
      : r.bottom + 4;
    const left = Math.max(8, Math.min(r.right - menuW, window.innerWidth - menuW - 8));
    setPos({ top, left });
    setOpen(true);
  };

  return (
    <>
      <button ref={btnRef} type="button" onClick={toggle}
        title="액션"
        style={{
          minHeight: 28, minWidth: 32, padding: "0 6px",
          background: open ? "var(--color-bg)" : "none",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-sm)",
          cursor: "pointer",
          fontSize: "1rem", lineHeight: 1, color: "var(--color-text)",
        }}>
        ⋯
      </button>
      {open && pos && (
        <div ref={popRef} style={{
          position: "fixed", top: pos.top, left: pos.left, zIndex: 1000,
          minWidth: 160,
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-sm)",
          boxShadow: "0 6px 18px rgba(0,0,0,0.35)",
          overflow: "hidden",
        }}>
          {items.map((it, i) => (
            <button key={i} type="button"
              onClick={() => { setOpen(false); if (!it.disabled) it.onClick(); }}
              disabled={it.disabled}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "8px 12px", border: "none", background: "transparent",
                color: it.disabled ? "var(--color-text-light)" : (it.danger ? "#dc2626" : "var(--color-text)"),
                fontSize: "0.8rem",
                cursor: it.disabled ? "not-allowed" : "pointer",
              }}
              onMouseEnter={(e) => { if (!it.disabled) e.currentTarget.style.background = "var(--color-bg)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
              {it.label}
            </button>
          ))}
        </div>
      )}
    </>
  );
}


function PlansListView({
  savedPlans,                // [{id, status, source_account, source_region, azure_region, resource_count, created_at, updated_at, name}]
  pastPlans,                 // [{run_id, has_terraform, terraform_file_count, ...}]
  loadingPast,
  activePlanId,              // id of the saved plan tied to the current Discover→Plan handoff
  mappingActive,             // bool — true while useAzureMapping is still running
  onOpenSaved,               // (planId) => void
  onDeleteSaved,             // (planId or [planIds]) => void
  onOpenPast,
  onDeletePast,              // (runId or [runIds]) => void
  onRefresh,
  onGoToDiscover,
}) {
  const savedRows = savedPlans || [];

  // Multi-select for bulk delete (savedPlans only — pastPlans dirs aren't
  // surfaced in this view, so they shouldn't be selectable either).
  const [selectedIds, setSelectedIds] = useState(new Set());

  // Drop selections that no longer exist after a refresh
  useEffect(() => {
    setSelectedIds(prev => {
      const valid = new Set(savedRows.map(s => s.id));
      let changed = false;
      const next = new Set();
      for (const id of prev) {
        if (valid.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [savedRows]);

  const toggle = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const allItemIds = useMemo(
    () => savedRows.map(s => s.id),
    [savedRows],
  );

  const toggleAll = () => {
    setSelectedIds(prev => {
      if (prev.size === allItemIds.length && allItemIds.length > 0) return new Set();
      return new Set(allItemIds);
    });
  };
  const allChecked = allItemIds.length > 0 && selectedIds.size === allItemIds.length;
  const someChecked = selectedIds.size > 0 && !allChecked;

  const pagination = usePagination(pastPlans || [], 10);
  const { pageItems: visiblePastPlans } = pagination;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <strong style={{ fontSize: "0.95rem" }}>📋 마이그레이션 Plan 목록</strong>
        <span style={{ color: "var(--color-text-light)", fontSize: "0.78rem" }}>
          {loadingPast ? "로드 중…" : `${savedRows.length}건`}
        </span>
        <button type="button" onClick={onRefresh}
          style={{
            background: "none", border: "none",
            color: "var(--color-text-light)", cursor: "pointer", fontSize: "0.78rem",
          }}>
          ↻ 새로고침
        </button>
        <div style={{ flex: 1 }} />
        {selectedIds.size > 0 && (
          <button type="button"
            onClick={() => onDeletePast(Array.from(selectedIds))}
            style={{
              minHeight: 32, padding: "0 14px", fontSize: "0.8rem",
              background: "#dc2626", color: "#fff", border: "1px solid #dc2626",
              borderRadius: "var(--radius-sm)", cursor: "pointer", fontWeight: 600,
            }}>
            🗑 선택 {selectedIds.size}개 삭제
          </button>
        )}
        <button type="button" onClick={onGoToDiscover}
          className="run-btn action-btn"
          style={{ minHeight: 34, padding: "0 20px", fontSize: "0.82rem", fontWeight: 600 }}>
          ➕ Plan 생성
        </button>
      </div>

      <div style={{
        display: "flex", flexDirection: "column", gap: 0,
        border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)",
        overflow: "visible",   // dropdown menus from rows must render outside
      }}>
        {/* Header row */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "32px 120px 1.6fr 1fr 1fr 1.4fr 0.7fr 130px",
          gap: 8, padding: "8px 14px",
          background: "var(--color-bg)",
          borderBottom: "1px solid var(--color-border)",
          fontSize: "0.74rem", fontWeight: 700, color: "var(--color-text-light)",
        }}>
          <span style={{ display: "flex", alignItems: "center" }}>
            <input
              type="checkbox"
              checked={allChecked}
              ref={el => { if (el) el.indeterminate = someChecked; }}
              onChange={toggleAll}
              disabled={allItemIds.length === 0}
              title="모든 Plan 선택/해제"
            />
          </span>
          <span>상태</span>
          <span>이름</span>
          <span>계정</span>
          <span>리전</span>
          <span>스캔 범위</span>
          <span>리소스</span>
          <span>생성</span>
        </div>

        {/* In-progress 행은 표시하지 않음 — Discovery → Plan handoff 시 자동으로
            backend selected_plans 에 저장되므로 saved 행으로 즉시 보임. */}

        {/* Saved Selected/Mapped plans (DB-backed) */}
        {savedRows.map(s => {
          const checked = selectedIds.has(s.id);
          // Override the DB-stored status to "🔁 Mapping" while this row's
          // mapping is still in flight (only for the currently-active row).
          const effectiveStatus = (mappingActive && s.id === activePlanId) ? "mapping" : s.status;
          const meta = PLAN_STATUS_META[effectiveStatus] || PLAN_STATUS_META.selected;
          return (
            <div key={s.id}
              onClick={() => onOpenSaved?.(s.id)}
              style={{
                display: "grid",
                gridTemplateColumns: "32px 120px 1.6fr 1fr 1fr 1.4fr 0.7fr 130px",
                gap: 8, padding: "10px 14px",
                borderBottom: "1px solid var(--color-border)",
                background: checked ? "rgba(220,38,38,0.04)" : "transparent",
                fontSize: "0.8rem", alignItems: "center",
                cursor: "pointer",
              }}>
              <span style={{ display: "flex", alignItems: "center" }} onClick={e => e.stopPropagation()}>
                <input type="checkbox" checked={checked} onChange={() => toggle(s.id)} />
              </span>
              <span title={meta.hint} style={{
                fontSize: "0.72rem", fontWeight: 700, color: meta.color,
              }}>
                {meta.label}
              </span>
              <span>
                <strong>{s.name || `Plan-${(s.id || "").slice(0, 8)}`}</strong>
              </span>
              <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
                {s.source_account || "—"}
              </span>
              <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
                {s.source_region || "—"}
              </span>
              <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
                {_scanScopeLabel({
                  discovery_mode: s.discovery_mode,
                  resource_group: s.resource_group,
                  scoped_meta:    s.scoped_meta,
                })}
              </span>
              <span style={{ fontSize: "0.74rem" }}>
                {s.resource_count ?? 0}개
              </span>
              <span style={{ fontSize: "0.72rem", color: "var(--color-text-light)" }}>
                {_formatDate(s.updated_at || s.created_at)}
              </span>
            </div>
          );
        })}

        {/* Past plans from disk are intentionally hidden — savedPlans is the
            canonical source of truth and shows the same rows with live status. */}

        {!loadingPast && savedRows.length === 0 && (
          <div style={{
            padding: "24px 16px", textAlign: "center",
            fontSize: "0.85rem", color: "var(--color-text-light)",
          }}>
            아직 Plan 이 없습니다. Discover 단계에서 리소스를 선택해서 시작하세요.
          </div>
        )}
      </div>

      {(pastPlans || []).length > 10 && (
        <div style={{ marginTop: 10 }}>
          <Pagination {...pagination} />
        </div>
      )}
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
  architecture,
  onGoToDiscover,
  mapping,
  onPlanCompleted,
  targetSubscriptionId = "",
  currentPlanId = null,
  setScopedRows,
  setScopedMeta,
  setArchitecture,
  setCurrentPlanId,
  seedMappingsRef,
  shouldAutoResumeRef,
}) {
  // viewMode: "list" (default) | "detail"
  // selectedRunId: when set, detail view shows that past plan (read-only); else
  // the in-progress (current scope) plan workflow.
  const [viewMode, setViewMode] = useState("list");
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [openPlanLabel, setOpenPlanLabel] = useState(null);   // human-readable name for detail header

  const [pastPlans, setPastPlans] = useState([]);
  const [loadingPast, setLoadingPast] = useState(false);
  const [savedPlans, setSavedPlans] = useState([]);

  // Confirm-delete modal state — pendingDelete can mix sentinel +
  // saved-plan ids (uuid) + past run_ids (timestamp).
  const [pendingDelete, setPendingDelete] = useState(null);
  const [deleteBusy, setDeleteBusy]       = useState(false);
  const [deleteError, setDeleteError]     = useState(null);

  const refreshPastPlans = useCallback(async () => {
    setLoadingPast(true);
    try {
      const res = await fetchMigrationOutputs();
      setPastPlans(res.runs || []);
    } catch {
      setPastPlans([]);
    } finally {
      setLoadingPast(false);
    }
  }, []);

  const refreshSavedPlans = useCallback(async () => {
    try {
      const res = await listSelectedPlans();
      setSavedPlans(res.plans || []);
    } catch {
      setSavedPlans([]);
    }
  }, []);

  useEffect(() => { refreshPastPlans(); }, [refreshPastPlans]);
  useEffect(() => { refreshSavedPlans(); }, [refreshSavedPlans]);

  // Plan creation only happens at the Discover→Plan handoff (handled in
  // App.jsx).  Re-entering the Plan page just refreshes the saved-plans
  // list — it never creates a new row.

  return (
    <section className="page-section">
      {/* ─── Header ─── */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: "0 0 4px", fontSize: "1.2rem", fontWeight: 700 }}>
          마이그레이션 계획
        </h2>
        <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--color-text-light)" }}>
          Discover에서 선택한 리소스를 Azure로 매핑하고, Terraform 모듈과 데이터 이전 스크립트를 생성합니다.
        </p>
      </div>

      {viewMode === "list" && (
        <PlansListView
          savedPlans={savedPlans}
          pastPlans={pastPlans}
          loadingPast={loadingPast}
          activePlanId={currentPlanId}
          mappingActive={!!mapping?.loading}
          onRefresh={() => { refreshPastPlans(); refreshSavedPlans(); }}
          onGoToDiscover={onGoToDiscover}
          onOpenSaved={async (planId) => {
            const sp = savedPlans.find(s => s.id === planId);
            setSelectedRunId(null);
            setOpenPlanLabel(sp?.name || `Plan-${(planId || "").slice(0, 8)}`);
            setViewMode("detail");
            // Hydrate App.jsx state from the persisted plan so useAzureMapping
            // sees rows + seeded mappings.  This is what makes Mapping / Plan
            // 수립 buttons usable after a browser refresh, AND lets the same
            // mapping object continue running in the background as the user
            // navigates between steps.
            try {
              const res = await getSelectedPlan(planId);
              const plan = res?.plan || res || null;
              if (plan) {
                // 1. Pre-load the seed BEFORE rows update, so the hook's
                //    reset effect can consume it on the same render cycle.
                if (seedMappingsRef) seedMappingsRef.current = plan.mappings || null;
                // 2. If DB says mapping was in progress, ask App.jsx to
                //    auto-resume the run() once rows are visible to the hook.
                if (shouldAutoResumeRef) {
                  const total = (plan.scoped_rows || []).length;
                  const done  = (plan.mappings || []).length;
                  shouldAutoResumeRef.current = (plan.status === "mapping" && done < total);
                }
                if (plan.azure_region && setAzureRegion) setAzureRegion(plan.azure_region);
                if (setScopedMeta)   setScopedMeta(plan.scoped_meta || null);
                if (setArchitecture) setArchitecture(plan.architecture || null);
                if (setScopedRows)   setScopedRows(plan.scoped_rows || []);
                if (setCurrentPlanId) setCurrentPlanId(plan.id);
                // 3. If Plan 수립 has already produced an output dir for this
                //    plan (status="ready"), point RunMigrationForm at it via
                //    preloadedRunId so the result panel renders immediately.
                if (plan.plan_run_id) {
                  setSelectedRunId(plan.plan_run_id);
                }
              }
            } catch { /* fall back to whatever React state already has */ }
          }}
          onDeleteSaved={(ids) => {
            const arr = Array.isArray(ids) ? ids : [ids];
            setPendingDelete(arr);
            setDeleteError(null);
          }}
          onOpenPast={(runId) => {
            setSelectedRunId(runId);
            setOpenPlanLabel(`Plan-${runId.slice(-6)}`);
            setViewMode("detail");
          }}
          onDeletePast={(runIds) => {
            const ids = Array.isArray(runIds) ? runIds : [runIds];
            setPendingDelete(ids);
            setDeleteError(null);
          }}
        />
      )}

      {pendingDelete && pendingDelete.length > 0 && (() => {
        const savedIdSet = new Set(savedPlans.map(s => s.id));
        const savedIds   = pendingDelete.filter(id => savedIdSet.has(id));
        const totalCount = savedIds.length;
        return (
          <ConfirmModal
            title={totalCount === 1 ? "Plan 삭제" : `${totalCount}개 Plan 삭제`}
            danger
            busy={deleteBusy}
            confirmLabel={totalCount === 1 ? "삭제" : `${totalCount}개 모두 삭제`}
            body={
              <>
                {savedIds.length > 0 && (
                  <>
                    <div style={{ marginBottom: 8 }}>
                      다음 Plan 을 삭제합니다:
                    </div>
                    <ul style={{ margin: "6px 0 10px 18px", padding: 0, fontFamily: "monospace", fontSize: "0.78rem" }}>
                      {savedIds.map(id => {
                        const p = savedPlans.find(s => s.id === id);
                        return <li key={id}>{p?.name || id.slice(0, 8)}</li>;
                      })}
                    </ul>
                  </>
                )}
                <div style={{ fontSize: "0.78rem", color: "var(--color-text-light)", lineHeight: 1.5 }}>
                  • Plan 메타데이터 + 매핑 결과 + 생성된 terraform 모듈 / 데이터 이전 스크립트가 모두 제거됩니다.<br/>
                  • 이 Plan 으로 이미 시작한 Deploy 는 그대로 유지됩니다.
                </div>
                {deleteError && (
                  <div className="form-error" style={{ marginTop: 10 }}>
                    {deleteError}
                  </div>
                )}
              </>
            }
            onCancel={() => { setPendingDelete(null); setDeleteError(null); }}
            onConfirm={async () => {
              setDeleteBusy(true); setDeleteError(null);
              const failed = [];
              if (savedIds.length > 0) {
                try { await bulkDeleteSelectedPlans(savedIds); }
                catch (e) { failed.push(`(saved bulk): ${e.message || e}`); }
              }
              await Promise.all([refreshPastPlans(), refreshSavedPlans()]);
              setDeleteBusy(false);
              if (failed.length === 0) {
                setPendingDelete(null);
              } else {
                setDeleteError(`일부 삭제 실패:\n${failed.join("\n")}`);
              }
            }}
          />
        );
      })()}

      {viewMode === "detail" && (
        <div>
          <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <button type="button"
              onClick={() => { setViewMode("list"); setSelectedRunId(null); setOpenPlanLabel(null); refreshPastPlans(); refreshSavedPlans(); }}
              style={{
                background: "none", border: "1px solid var(--color-border)",
                color: "var(--color-text-light)", borderRadius: "var(--radius-sm)",
                padding: "5px 14px", fontSize: "0.78rem", cursor: "pointer",
              }}>
              ← Plan 목록
            </button>
            <strong style={{ fontSize: "0.95rem" }}>
              📋 {openPlanLabel || "(이름 없음)"}
            </strong>
            {selectedRunId && (
              <span style={{ fontSize: "0.78rem", color: "var(--color-text-light)" }}>
                <code>{selectedRunId}</code> · 보기 모드
              </span>
            )}
          </div>
          <RunMigrationForm
            awsSpec={awsSpec}
            setAwsSpec={setAwsSpec}
            azureRegion={azureRegion}
            setAzureRegion={setAzureRegion}
            goals={goals}
            setGoals={setGoals}
            scopedRows={scopedRows}
            scopedMeta={scopedMeta}
            architecture={architecture}
            onGoToDiscover={onGoToDiscover}
            mapping={mapping}
            onPlanCompleted={() => {
              onPlanCompleted?.();
              refreshPastPlans();
              refreshSavedPlans();
            }}
            targetSubscriptionId={targetSubscriptionId}
            preloadedRunId={selectedRunId}
            currentPlanId={currentPlanId}
          />
        </div>
      )}
    </section>
  );
}

/** Gate panel between mapping and Plan 수립 — same panel shell as the
 *  "리소스 매핑" / "Plan 수립" panels.  User clicks "정책 조회" to fetch
 *  the subscription's enforced policies, picks which apply via checkbox,
 *  and writes guidance entries for each.  Plan 수립 button is gated until
 *  every *selected* policy has ≥1 entry. */
function PolicyGuidanceReview({ subscriptionId, mappings, mappingComplete, onReviewComplete }) {
  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);
  const [openPid, setOpenPid]   = useState(null);
  // Optimistic per-row selection — flips on click before server roundtrip.
  const [localSelected, setLocalSelected] = useState({});
  // Track in-flight toggles so user can spam checkboxes without race
  const [busyPids, setBusyPids] = useState(new Set());
  // General (cross-cutting) guidance entries
  const [generalEntries, setGeneralEntries] = useState([]);
  // Pagination state
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 10;

  const azureTypes = useMemo(() => {
    const set = new Set();
    for (const m of (mappings || [])) {
      const t = m?.azure_resource_type || m?.azure_type;
      if (t) set.add(t);
    }
    return Array.from(set).sort();
  }, [mappings]);

  const refresh = useCallback(async () => {
    if (!subscriptionId) return;
    setLoading(true); setError(null);
    try {
      const [res, gen] = await Promise.all([
        discoverRelevantPolicies({ subscriptionId, azureTypes }),
        listGeneralGuidance().catch(() => ({ entries: [] })),
      ]);
      setData(res);
      setGeneralEntries(gen.entries || []);
      setLocalSelected({});
      setPage(0);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [subscriptionId, azureTypes]);

  const refreshGeneral = useCallback(async () => {
    try {
      const gen = await listGeneralGuidance();
      setGeneralEntries(gen.entries || []);
    } catch { /* silent */ }
  }, []);

  // Reconcile server `selected` with optimistic local overrides.
  const policiesView = useMemo(() => {
    const items = data?.policies || [];
    return items.map(p => {
      const pid = p.policy_definition_id || "";
      const overridden = Object.prototype.hasOwnProperty.call(localSelected, pid);
      return { ...p, _pid: pid, selected: overridden ? localSelected[pid] : !!p.selected };
    });
  }, [data, localSelected]);

  const selectedCount      = policiesView.filter(p => p.selected).length;
  const selectedWithEntry  = policiesView.filter(p => p.selected && (p.entries || []).length > 0).length;
  const selectedMissing    = selectedCount - selectedWithEntry;
  const allReviewed        = !!data && (selectedCount === 0 || selectedMissing === 0);

  // Gate Plan 수립: as soon as the user has fetched the policy list, they're
  // free to proceed.  Selected-but-empty policies show a warning but don't
  // block — the codegen LLM still gets the raw policy info and can do its
  // best.  Mapping must be complete (codegen needs the mapped resources).
  useEffect(() => {
    if (!mappingComplete) { onReviewComplete?.(false); return; }
    onReviewComplete?.(!!data);
  }, [mappingComplete, data, onReviewComplete]);

  const toggleSelected = async (policy, next) => {
    const pid = policy.policy_definition_id || policy._pid || "";
    if (!pid) {
      setError(`policy_definition_id 가 없어 선택할 수 없는 정책: ${policy.policy_name}`);
      return;
    }
    // Optimistic update
    setLocalSelected(prev => ({ ...prev, [pid]: next }));
    setBusyPids(prev => { const n = new Set(prev); n.add(pid); return n; });
    try {
      await setPolicyGuidanceSelected(pid, next, policy.policy_name || "");
      // Reflect server state by re-fetching (cheap, no LLM).
      const res = await discoverRelevantPolicies({ subscriptionId, azureTypes });
      setData(res);
      // Keep this pid's override in case server hasn't fully synced; clear others.
      setLocalSelected(prev => ({ [pid]: prev[pid] !== undefined ? prev[pid] : next }));
    } catch (e) {
      setLocalSelected(prev => ({ ...prev, [pid]: !next }));
      setError(e.message || String(e));
    } finally {
      setBusyPids(prev => { const n = new Set(prev); n.delete(pid); return n; });
    }
  };

  // Header "전체 선택" tri-state checkbox
  const allSelectedNow   = policiesView.length > 0 && policiesView.every(p => p.selected);
  const someSelectedNow  = !allSelectedNow && policiesView.some(p => p.selected);
  const toggleAll = async () => {
    const next = !allSelectedNow;
    // Bulk optimistic update
    const optimistic = {};
    for (const p of policiesView) {
      const pid = p.policy_definition_id || "";
      if (pid) optimistic[pid] = next;
    }
    setLocalSelected(optimistic);
    // Fire all PUTs in parallel.  Don't await refresh between each — too slow.
    try {
      await Promise.all(policiesView
        .filter(p => p.policy_definition_id && p.selected !== next)
        .map(p => setPolicyGuidanceSelected(p.policy_definition_id, next, p.policy_name || "")));
      const res = await discoverRelevantPolicies({ subscriptionId, azureTypes });
      setData(res);
      setLocalSelected({});
    } catch (e) {
      setError(e.message || String(e));
    }
  };

  return (
    <div style={{
      padding: "16px 20px",
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: "var(--radius-sm)",
      marginBottom: 16,
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.8rem", fontWeight: 700, color: "var(--color-text)" }}>
          <span style={{ color: allReviewed ? "#16a34a" : "#a855f7" }}>●</span> 정책 지침 검토
          <span style={{ fontWeight: 400, fontSize: "0.78rem", color: "var(--color-text-light)" }}>
            — Plan 수립에 적용될 Azure Policy 선택 + 코드 생성 지침 작성
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {data && (
            <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>
              전체 {data.summary?.total ?? 0}개 · 선택 {selectedCount} · 지침 {selectedWithEntry}/{selectedCount}
            </span>
          )}
          <button
            className="run-btn action-btn"
            type="button"
            onClick={refresh}
            disabled={!mappingComplete || !subscriptionId || loading}
            style={{ minHeight: 34, padding: "0 20px", fontSize: "0.82rem", fontWeight: 600 }}
            title={
              !mappingComplete ? "먼저 Mapping 을 완료해주세요" :
              !subscriptionId  ? "Azure subscription 이 필요합니다" : ""
            }>
            {loading ? <><span className="spinner" />조회 중…</> : (data ? "↻ 정책 조회" : "🔎 정책 조회")}
          </button>
        </div>
      </div>

      {error && (
        <div className="form-error" style={{ marginBottom: 10, fontSize: "0.78rem" }}>{error}</div>
      )}

      {!mappingComplete && (
        <div style={{ fontSize: "0.8rem", color: "var(--color-text-light)" }}>
          먼저 위의 <strong>리소스 매핑</strong> 을 완료해주세요.
        </div>
      )}

      {mappingComplete && !subscriptionId && (
        <div className="form-error" style={{ fontSize: "0.78rem" }}>
          Azure subscription_id 가 비어있어 정책을 조회할 수 없습니다.  Connect 단계에서 Azure 계정을 선택해주세요.
        </div>
      )}

      {mappingComplete && subscriptionId && !data && !loading && (
        <div style={{ fontSize: "0.8rem", color: "var(--color-text-light)" }}>
          <strong>정책 조회</strong> 버튼을 눌러 구독의 enforced 정책 목록을 가져오세요.
        </div>
      )}

      {data && policiesView.length === 0 && (
        <div style={{ fontSize: "0.8rem", color: "var(--color-text-light)" }}>
          구독에 enforced 정책이 없습니다.  바로 Plan 수립으로 넘어가도 됩니다.
        </div>
      )}

      {data && (
        <>
          {/* 전역 지침 섹션 — 모든 정책 / 모든 plan 에 공통 주입 */}
          <GeneralGuidancePanel
            entries={generalEntries}
            onChange={refreshGeneral}
          />
        </>
      )}

      {data && policiesView.length > 0 && (
        <>
          <div style={{ fontSize: "0.78rem", color: "var(--color-text-light)", marginTop: 12, marginBottom: 8 }}>
            Plan 수립에 적용될 정책을 <strong>체크박스</strong> 로 선택하세요.  선택된 정책마다 지침이 있으면 코드 생성 정확도가 높아집니다.  지침이 없을 땐 ✨ AI 초안 생성으로 시작하면 빠릅니다.
          </div>
          {/* 전체 선택 / 헤더 row */}
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "6px 12px", marginBottom: 6,
            background: "var(--color-bg)", border: "1px solid var(--color-border)",
            borderRadius: 4, fontSize: "0.74rem", color: "var(--color-text-light)",
          }}>
            <input type="checkbox"
              checked={allSelectedNow}
              ref={el => { if (el) el.indeterminate = someSelectedNow; }}
              onChange={toggleAll} />
            <span style={{ flex: 1 }}>전체 선택/해제 ({selectedCount}/{policiesView.length})</span>
            {selectedMissing > 0 && (
              <span style={{ color: "#a855f7", fontWeight: 600 }}>
                지침 누락 {selectedMissing}건
              </span>
            )}
          </div>
          {/* Pagination — 10개 단위 */}
          {(() => {
            const totalPages = Math.max(1, Math.ceil(policiesView.length / PAGE_SIZE));
            const safePage   = Math.min(page, totalPages - 1);
            const pageItems  = policiesView.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);
            return (
              <>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {pageItems.map(p => (
                    <PolicyGuidanceRow key={p._pid || p.policy_name}
                      policy={p}
                      expanded={openPid === (p._pid || p.policy_name)}
                      azureTypes={azureTypes}
                      busy={p._pid && busyPids.has(p._pid)}
                      onToggle={() => setOpenPid(openPid === (p._pid || p.policy_name) ? null : (p._pid || p.policy_name))}
                      onChange={refresh}
                      onToggleSelected={(next) => toggleSelected(p, next)}
                    />
                  ))}
                </div>
                {totalPages > 1 && (
                  <div style={{
                    display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                    marginTop: 10, fontSize: "0.78rem",
                  }}>
                    <button type="button"
                      onClick={() => setPage(0)} disabled={safePage === 0}
                      style={_pagerBtnStyle(safePage === 0)}>«</button>
                    <button type="button"
                      onClick={() => setPage(p => Math.max(0, p - 1))} disabled={safePage === 0}
                      style={_pagerBtnStyle(safePage === 0)}>‹ 이전</button>
                    <span style={{ padding: "0 10px", color: "var(--color-text-light)" }}>
                      {safePage + 1} / {totalPages}
                    </span>
                    <button type="button"
                      onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={safePage >= totalPages - 1}
                      style={_pagerBtnStyle(safePage >= totalPages - 1)}>다음 ›</button>
                    <button type="button"
                      onClick={() => setPage(totalPages - 1)} disabled={safePage >= totalPages - 1}
                      style={_pagerBtnStyle(safePage >= totalPages - 1)}>»</button>
                  </div>
                )}
              </>
            );
          })()}
        </>
      )}
    </div>
  );
}

function _pagerBtnStyle(disabled) {
  return {
    minHeight: 26, padding: "0 10px", fontSize: "0.74rem",
    background: "transparent", color: disabled ? "var(--color-text-light)" : "var(--color-text)",
    border: "1px solid var(--color-border)", borderRadius: 3,
    cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
  };
}


/** 전역 (cross-cutting) 지침 — Plan 수립 시 모든 정책에 공통 주입.
 *  예: "모든 리소스에 tags = var.tags 적용", "naming 은 prefix + workload + env". */
function GeneralGuidancePanel({ entries, onChange }) {
  // Default collapsed when there are existing entries (panel might be tall),
  // expanded when empty so user notices the "+ 추가" call to action.
  const [open, setOpen]     = useState(entries.length === 0);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft]   = useState("");
  const [busy, setBusy]     = useState(false);
  const [error, setError]   = useState(null);

  const submitAdd = async () => {
    if (!draft.trim()) return;
    setBusy(true); setError(null);
    try {
      await addGeneralGuidance(draft);
      setDraft(""); setAdding(false);
      onChange?.();
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{
      marginBottom: 10, padding: "10px 12px",
      background: "rgba(168,85,247,0.04)",
      border: "1px solid rgba(168,85,247,0.4)",
      borderRadius: "var(--radius-sm)",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        cursor: "pointer",
      }} onClick={() => setOpen(o => !o)}>
        <span style={{ color: "#a855f7", fontSize: "0.78rem", width: 14 }}>{open ? "▾" : "▸"}</span>
        <strong style={{ fontSize: "0.82rem", color: "#a855f7" }}>📌 전역 지침</strong>
        <span style={{ fontSize: "0.72rem", color: "var(--color-text-light)" }}>
          모든 정책 / 모든 Plan 수립 에 공통으로 주입 · {entries.length} 건
        </span>
        <div style={{ flex: 1 }} />
        <button type="button"
          onClick={e => { e.stopPropagation(); setOpen(true); setAdding(a => !a); }}
          className="tab action-btn action-btn--secondary"
          style={{ minHeight: 28, padding: "0 12px", fontSize: "0.74rem" }}>
          {adding ? "취소" : "+ 추가"}
        </button>
      </div>
      {open && (
        <div style={{ marginTop: 8 }}>
          {adding && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
              <textarea value={draft} onChange={e => setDraft(e.target.value)}
                placeholder="새 전역 지침… (예: 모든 리소스에 var.tags 적용, naming 은 prefix-workload-env 형태)"
                disabled={busy}
                style={{
                  minHeight: 60, padding: "8px 10px", fontSize: "0.8rem",
                  fontFamily: "inherit",
                  background: "var(--color-bg)", color: "var(--color-text)",
                  border: "1px solid var(--color-border)", borderRadius: 4,
                }}/>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                <button type="button" onClick={submitAdd}
                  disabled={busy || !draft.trim()}
                  className="run-btn action-btn"
                  style={{ minHeight: 28, padding: "0 12px", fontSize: "0.74rem", fontWeight: 600 }}>
                  {busy ? "추가 중…" : "추가"}
                </button>
              </div>
              {error && <div className="form-error" style={{ fontSize: "0.74rem" }}>{error}</div>}
            </div>
          )}
          {entries.length === 0 ? (
            <div style={{ fontSize: "0.76rem", color: "var(--color-text-light)" }}>(전역 지침 없음)</div>
          ) : (
            <div style={{
              display: "flex", flexDirection: "column", gap: 6,
              maxHeight: 280, overflowY: "auto",
              paddingRight: 4,
            }}>
              {entries.map(e => (
                <GeneralGuidanceItem key={e.id} entry={e} onChange={onChange} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function GeneralGuidanceItem({ entry, onChange }) {
  const [editing, setEditing] = useState(false);
  const [text, setText]       = useState(entry.text || "");
  const [busy, setBusy]       = useState(false);
  const [error, setError]     = useState(null);

  const save = async () => {
    setBusy(true); setError(null);
    try {
      await updateGeneralGuidance(entry.id, text);
      setEditing(false);
      onChange?.();
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(false); }
  };
  const del = async () => {
    setBusy(true); setError(null);
    try {
      await deleteGeneralGuidance(entry.id);
      onChange?.();
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{
      padding: "6px 10px",
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: 3, fontSize: "0.8rem", lineHeight: 1.55,
    }}>
      {editing ? (
        <>
          <textarea value={text} onChange={e => setText(e.target.value)}
            disabled={busy}
            style={{
              width: "100%", minHeight: 60, padding: "6px 8px", fontSize: "0.8rem",
              fontFamily: "inherit",
              background: "var(--color-bg)", color: "var(--color-text)",
              border: "1px solid var(--color-border)", borderRadius: 3,
              boxSizing: "border-box",
            }}/>
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 4 }}>
            <button type="button" onClick={() => { setEditing(false); setText(entry.text || ""); setError(null); }}
              disabled={busy} className="tab action-btn action-btn--secondary"
              style={{ minHeight: 26, padding: "0 10px", fontSize: "0.72rem" }}>취소</button>
            <button type="button" onClick={save}
              disabled={busy || !text.trim()} className="run-btn action-btn"
              style={{ minHeight: 26, padding: "0 10px", fontSize: "0.72rem", fontWeight: 600 }}>
              {busy ? "저장…" : "저장"}
            </button>
          </div>
          {error && <div className="form-error" style={{ fontSize: "0.72rem", marginTop: 4 }}>{error}</div>}
        </>
      ) : (
        <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
          <div style={{ flex: 1, whiteSpace: "pre-wrap" }}>{entry.text}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.7rem" }}>
            <button type="button" onClick={() => setEditing(true)} disabled={busy}
              style={{ background: "none", border: "none", color: "var(--color-text-light)", cursor: "pointer", padding: 0 }}>✏️</button>
            <button type="button" onClick={del} disabled={busy}
              style={{ background: "none", border: "none", color: "#dc2626", cursor: "pointer", padding: 0 }}>🗑</button>
          </div>
        </div>
      )}
    </div>
  );
}


function PolicyGuidanceRow({ policy, expanded, azureTypes, busy, onToggle, onChange, onToggleSelected }) {
  const entries = policy.entries || [];
  const hasEntries = entries.length > 0;
  const isSelected = !!policy.selected;
  const hasPid = !!(policy.policy_definition_id || policy._pid);
  const borderColor = !isSelected ? "var(--color-border)"
    : hasEntries ? "rgba(22,163,74,0.4)"
    : "rgba(168,85,247,0.4)";
  const bgColor = !isSelected ? "transparent"
    : hasEntries ? "rgba(22,163,74,0.04)"
    : "rgba(168,85,247,0.04)";
  const effectMeta = policy.effect === "DENY"
    ? { color: "#dc2626", label: "DENY" }
    : { color: "#3b82f6", label: "MODIFY" };

  return (
    <div style={{
      border: `1px solid ${borderColor}`,
      background: bgColor,
      borderRadius: 4,
      opacity: isSelected ? 1 : 0.75,
    }}>
      <div style={{
        padding: "8px 12px", display: "flex", alignItems: "center", gap: 8,
        fontSize: "0.82rem",
      }}>
        <label style={{
          display: "inline-flex", alignItems: "center",
          cursor: hasPid && !busy ? "pointer" : "not-allowed",
        }}
          title={
            !hasPid ? "policy_definition_id 가 없어 선택 불가" :
            busy    ? "저장 중…" :
            "이 정책을 Plan 수립에 적용"
          }>
          <input type="checkbox"
            checked={isSelected}
            disabled={!hasPid || busy}
            onChange={e => onToggleSelected?.(e.target.checked)}
            style={{ cursor: "inherit" }} />
        </label>
        <span onClick={onToggle} style={{ width: 14, color: "var(--color-text-light)", cursor: "pointer" }}>
          {expanded ? "▾" : "▸"}
        </span>
        <span style={{
          fontSize: "0.66rem", padding: "1px 7px", borderRadius: 3,
          color: effectMeta.color, border: `1px solid ${effectMeta.color}`, whiteSpace: "nowrap",
        }}>{effectMeta.label}</span>
        <strong onClick={onToggle}
          style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", cursor: "pointer" }}>
          {policy.policy_name}
        </strong>
        <span style={{ fontSize: "0.72rem", color: "var(--color-text-light)" }}>
          {policy.azure_type}
        </span>
        {isSelected && (
          <span style={{
            fontSize: "0.7rem", padding: "1px 8px",
            background: hasEntries ? "rgba(22,163,74,0.10)" : "transparent",
            border: `1px solid ${hasEntries ? "#16a34a" : "#a855f7"}`,
            color: hasEntries ? "#16a34a" : "#a855f7",
            borderRadius: 3,
          }}>
            {hasEntries ? `${entries.length}개 지침` : "지침 없음"}
          </span>
        )}
        {busy && <span className="spinner" style={{ marginLeft: 4 }} />}
      </div>

      {expanded && (
        <div style={{ padding: "0 12px 12px 32px", display: "flex", flexDirection: "column", gap: 6 }}>
          {entries.length === 0 ? (
            <div style={{ fontSize: "0.76rem", color: "var(--color-text-light)" }}>
              아직 지침이 없습니다.  ✨ AI 초안 생성 또는 + 직접 추가로 시작하세요.
            </div>
          ) : entries.map(e => (
            <GuidanceEntryRow key={e.id}
              entry={e}
              policyDefinitionId={policy.policy_definition_id}
              onChange={onChange}
            />
          ))}
          <GuidanceEntryAdder
            policyDefinitionId={policy.policy_definition_id}
            policyName={policy.policy_name}
            rawPolicy={policy.raw}
            azureTypes={azureTypes}
            onChange={onChange}
          />
          {/* Raw policy JSON viewer — collapsed by default, scrollable. */}
          {policy.raw && (
            <details style={{ marginTop: 4 }}>
              <summary style={{
                cursor: "pointer", fontSize: "0.74rem", color: "var(--color-text-light)",
                padding: "4px 0",
              }}>
                📄 raw policy rule JSON 보기
              </summary>
              <pre style={{
                marginTop: 4, padding: "8px 10px",
                background: "#0d1117", color: "#c9d1d9",
                fontFamily: "monospace", fontSize: "0.72rem", lineHeight: 1.5,
                borderRadius: 4, whiteSpace: "pre-wrap", wordBreak: "break-word",
                maxHeight: 320, overflow: "auto",
              }}>{JSON.stringify(policy.raw, null, 2)}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}


function GuidanceEntryRow({ entry, policyDefinitionId, onChange }) {
  const [editing, setEditing] = useState(false);
  const [text, setText]       = useState(entry.text || "");
  const [busy, setBusy]       = useState(false);
  const [error, setError]     = useState(null);

  const sourceBadge = entry.source === "default" ? "📌 default"
    : entry.source === "ai_draft" ? "✨ AI"
    : "✏️ 사용자";

  const save = async () => {
    setBusy(true); setError(null);
    try {
      await updatePolicyGuidanceEntry(policyDefinitionId, entry.id, text);
      setEditing(false);
      onChange?.();
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(false); }
  };
  const del = async () => {
    setBusy(true); setError(null);
    try {
      await deletePolicyGuidanceEntry(policyDefinitionId, entry.id);
      onChange?.();
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{
      padding: "6px 10px",
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: 3, fontSize: "0.8rem", lineHeight: 1.55,
    }}>
      {editing ? (
        <>
          <textarea value={text} onChange={e => setText(e.target.value)}
            disabled={busy}
            style={{
              width: "100%", minHeight: 80, padding: "6px 8px", fontSize: "0.8rem",
              fontFamily: "inherit",
              background: "var(--color-bg)", color: "var(--color-text)",
              border: "1px solid var(--color-border)", borderRadius: 3,
              boxSizing: "border-box",
            }} />
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 4 }}>
            <button type="button" onClick={() => { setEditing(false); setText(entry.text || ""); setError(null); }}
              disabled={busy}
              className="tab action-btn action-btn--secondary"
              style={{ padding: "2px 10px", fontSize: "0.72rem" }}>취소</button>
            <button type="button" onClick={save}
              disabled={busy || !text.trim()}
              className="run-btn action-btn"
              style={{ padding: "2px 10px", fontSize: "0.72rem", fontWeight: 600 }}>
              {busy ? "저장…" : "저장"}
            </button>
          </div>
          {error && <div className="form-error" style={{ fontSize: "0.72rem", marginTop: 4 }}>{error}</div>}
        </>
      ) : (
        <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
          <div style={{ flex: 1, whiteSpace: "pre-wrap" }}>{entry.text}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.7rem", color: "var(--color-text-light)" }}>
            <span title="출처">{sourceBadge}</span>
            <button type="button" onClick={() => setEditing(true)} disabled={busy}
              style={{ background: "none", border: "none", color: "var(--color-text-light)", cursor: "pointer", padding: 0 }}>✏️</button>
            <button type="button" onClick={del} disabled={busy}
              style={{ background: "none", border: "none", color: "#dc2626", cursor: "pointer", padding: 0 }}>🗑</button>
          </div>
        </div>
      )}
    </div>
  );
}


function GuidanceEntryAdder({ policyDefinitionId, policyName, rawPolicy, azureTypes, onChange }) {
  const [adding, setAdding] = useState(false);
  const [text, setText]     = useState("");
  const [busy, setBusy]     = useState(false);
  const [error, setError]   = useState(null);
  const [drafting, setDrafting] = useState(false);

  const draft = async () => {
    if (!rawPolicy) return;
    setDrafting(true); setError(null);
    try {
      const r = await draftPolicyGuidance(policyDefinitionId, { rawPolicy, scopeResourceTypes: azureTypes });
      setText(r.draft || "");
      setAdding(true);
    } catch (e) { setError(e.message || String(e)); }
    finally { setDrafting(false); }
  };
  const save = async () => {
    if (!text.trim()) return;
    setBusy(true); setError(null);
    try {
      await addPolicyGuidanceEntry(policyDefinitionId, {
        text,
        source: drafting ? "ai_draft" : "user",
        policyName,
      });
      setText("");
      setAdding(false);
      onChange?.();
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(false); }
  };

  if (!adding) {
    return (
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <button type="button" onClick={() => setAdding(true)}
          className="tab action-btn action-btn--secondary"
          style={{ minHeight: 30, padding: "0 14px", fontSize: "0.78rem" }}>
          + 지침 추가
        </button>
        <button type="button" onClick={draft} disabled={drafting || !rawPolicy}
          style={{
            minHeight: 30, padding: "0 14px", fontSize: "0.78rem",
            background: "transparent", color: "#a855f7",
            border: "1px solid #a855f7", borderRadius: "var(--radius-sm)",
            cursor: drafting || !rawPolicy ? "not-allowed" : "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
          {drafting ? <><span className="spinner" />초안 생성 중…</> : "✨ AI 초안 생성"}
        </button>
        {error && <div className="form-error" style={{ fontSize: "0.72rem", flex: 1 }}>{error}</div>}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <textarea value={text} onChange={e => setText(e.target.value)}
        placeholder="이 정책에 대한 자연어 지침을 적어주세요…"
        disabled={busy}
        style={{
          minHeight: 80, padding: "6px 8px", fontSize: "0.8rem", fontFamily: "inherit",
          background: "var(--color-bg)", color: "var(--color-text)",
          border: "1px solid var(--color-border)", borderRadius: 3,
        }} />
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <button type="button" onClick={() => { setAdding(false); setText(""); setError(null); }}
          disabled={busy} className="tab action-btn action-btn--secondary"
          style={{ padding: "2px 10px", fontSize: "0.72rem" }}>취소</button>
        <button type="button" onClick={save}
          disabled={busy || !text.trim()}
          className="run-btn action-btn"
          style={{ padding: "2px 10px", fontSize: "0.72rem", fontWeight: 600 }}>
          {busy ? "저장…" : "저장"}
        </button>
      </div>
      {error && <div className="form-error" style={{ fontSize: "0.72rem" }}>{error}</div>}
    </div>
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
  architecture,
  onGoToDiscover,
  mapping,
  onPlanCompleted,
  targetSubscriptionId = "",
  preloadedRunId = null,
  currentPlanId = null,
}) {
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [prepMessage, setPrepMessage] = useState(null);
  // True once the user has at least one guidance entry per relevant policy
  // (or there are no policies in scope).  Plan 수립 button is gated on this.
  const [guidanceReviewComplete, setGuidanceReviewComplete] = useState(false);

  // Latest onPlanCompleted via ref so pollStatus doesn't re-create each render
  // (which would re-fire the [jobId, pollStatus] effect into an infinite poll).
  const onPlanCompletedRef = useRef(onPlanCompleted);
  useEffect(() => { onPlanCompletedRef.current = onPlanCompleted; }, [onPlanCompleted]);
  // Track which jobIds we've already notified completion for, so the
  // refresh→re-poll cycle doesn't spam the parent's onPlanCompleted.
  const completedNotifiedRef = useRef(new Set());

  const pollStatus = useCallback(() => {
    if (!jobId) return;
    getMigrationStatus(jobId)
      .then((res) => {
        setStatus(res);
        setError(null);  // a successful poll clears any stale error
        if (res.status === "pending" || res.status === "running") {
          setTimeout(pollStatus, 2000);
          return;
        }
        if (res.status === "completed" && !completedNotifiedRef.current.has(jobId)) {
          completedNotifiedRef.current.add(jobId);
          // Persist final status on the saved-plan row (best-effort)
          if (currentPlanId) {
            updateSelectedPlan(currentPlanId, { status: "ready" }).catch(() => {});
          }
          onPlanCompletedRef.current?.();
        }
      })
      .catch((e) => {
        // Job already cleaned up by the backend (e.g. after completion) is
        // an expected 404 — don't surface it as a user-visible error.
        const msg = (e?.message || "").toLowerCase();
        if (msg.includes("not found") || msg.includes("404")) return;
        setError("상태 갱신에 실패했습니다");
      });
  // Intentionally NOT depending on onPlanCompleted — see ref above.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, currentPlanId]);

  useEffect(() => {
    if (jobId) pollStatus();
  // Only re-trigger when the job id itself changes — pollStatus identity is
  // already keyed off jobId via useCallback.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  // Preloaded view-only mode: when the user clicks "📂 보기" on a past plan
  // in the list, fetch its persisted output and render it as a completed run.
  useEffect(() => {
    if (!preloadedRunId) return;
    setJobId(null); setError(null); setPrepMessage(null);
    import("../api/apiClient").then(({ fetchMigrationOutput }) =>
      fetchMigrationOutput(preloadedRunId)
    ).then((data) => {
      // Wrap so PlanResultView can consume the same shape as live status.
      // Carry the persisted mappings + architecture through so the detail
      // view can render the mapping comparison + topology even though no
      // live React state is available.
      setStatus({
        status: "completed",
        result: {
          ...data,
          json_data: data.json_data,
          execution_log: data.execution_log,
          artifacts: { run_id: preloadedRunId },
          persisted_mappings: data.azure_mappings || [],
          persisted_architecture: data.architecture || null,
        },
      });
    }).catch((e) => setError(`Plan 로드 실패: ${e.message || e}`));
  }, [preloadedRunId]);

  // Skip the "active job" auto-resume in preloaded mode (we already loaded
  // the past plan's static output).
  useEffect(() => {
    if (preloadedRunId) return;
    getActiveMigrationJob()
      .then((res) => {
        if (res.job_id) setJobId(res.job_id);
      })
      .catch(() => {});
  }, [preloadedRunId]);

  const isRunning =
    !!jobId && status?.status !== "completed" && status?.status !== "failed";

  const handleRun = async () => {
    if (isRunning) return;
    setError(null);
    setStatus(null);
    setPrepMessage(null);

    // Eagerly persist "planning" intent BEFORE any awaits — so even an
    // immediate refresh after click leaves the DB row showing "⚙️ Planning"
    // in the Plan list.  PATCH uses keepalive so it survives page unload.
    if (currentPlanId) {
      updateSelectedPlan(currentPlanId, { status: "planning" }).catch(() => {});
    }

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
        architecture,                          // ← v2 pipeline 입력 (있으면 자동 v2)
        target_azure_region: azureRegion.trim() || "eastus",
        target_subscription_id: targetSubscriptionId,
        migration_goals: goals.trim(),
        azure_mappings: mappingsForPlanner,
        // Backend uses this to authoritatively flip the savedPlan row to
        // "planning" (on start) and "ready" (on completion) — independent
        // of the frontend polling state.  Survives page refresh.
        selected_plan_id: currentPlanId,
      });
      setJobId(res.job_id);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div>
      {/* ─── 리소스 매핑 Panel ─── */}
      <div style={{
        padding: "16px 20px",
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-sm)",
        marginBottom: 16,
      }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 12,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.8rem", fontWeight: 700, color: "var(--color-text)" }}>
            <span style={{ color: "#00d4aa" }}>●</span> 리소스 매핑
            <span style={{ fontWeight: 400, fontSize: "0.78rem", color: "var(--color-text-light)" }}>
              — AWS → Azure 대상 매핑
            </span>
          </div>
        </div>

        <ScopeSummaryTable
          rows={scopedRows}
          meta={scopedMeta}
          mapping={mapping}
          architecture={architecture}
          onGoToDiscover={onGoToDiscover}
          azureRegion={azureRegion}
          setAzureRegion={setAzureRegion}
        />
        <p style={{
          marginTop: 8, marginBottom: 0,
          fontSize: "0.78rem", color: "var(--color-text-light)",
        }}>
          위 내용은 사전 Azure Mapping 결과입니다. Plan 시 결과가 달라질 수 있습니다.
        </p>
      </div>

      {error && <div className="form-error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ─── 정책 지침 검토 Panel ─── 매핑 완료 후, Plan 수립 전 gate.
          Plan 이 완료된 후에도 표시 — 사용자가 지침을 수정하고 다시 수립할 수 있도록. */}
      <PolicyGuidanceReview
        subscriptionId={targetSubscriptionId}
        mappings={mapping?.mappings || []}
        mappingComplete={!!mapping?.mappingComplete}
        onReviewComplete={setGuidanceReviewComplete}
      />

      {/* ─── Plan 실행 Panel ─── 항상 표시.  수립 완료 후에도 동일 scope 로
          다시 수립할 수 있게 버튼을 유지. */}
      {true && (
      <div style={{
        padding: "16px 20px",
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-sm)",
        marginBottom: 16,
      }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 12,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.8rem", fontWeight: 700, color: "var(--color-text)" }}>
            <span style={{ color: "#60a5fa" }}>●</span> Plan 수립
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {prepMessage && !isRunning && (
              <span style={{ fontSize: "0.78rem", color: "var(--color-text-light)" }}>
                {prepMessage}
              </span>
            )}
            <button
              className="run-btn action-btn"
              type="button"
              onClick={handleRun}
              disabled={isRunning || !awsSpec.trim() || !mapping.mappingComplete || !guidanceReviewComplete}
              style={{ minHeight: 34, padding: "0 20px", fontSize: "0.82rem", fontWeight: 600 }}
              title={
                !mapping.mappingComplete ? "먼저 Mapping 을 완료해주세요" :
                !guidanceReviewComplete  ? "정책 지침 검토를 먼저 완료해주세요 (위 패널)" : ""
              }
            >
              {isRunning ? (
                <><span className="spinner" />{status?.status === "running" ? "수립 중…" : "시작 중…"}</>
              ) : !mapping.mappingComplete ? (
                <>🚀 Plan 수립</>
              ) : !guidanceReviewComplete ? (
                <>🚀 Plan 수립 (정책 지침 검토 필요)</>
              ) : status?.status === "completed" ? (
                <>🔄 Plan 다시 수립</>
              ) : (
                <>🚀 Plan 수립</>
              )}
            </button>
          </div>
        </div>

      </div>
      )}

      {/* ─── Plan 결과 Panel — Azure 토폴로지 + Terraform + 데이터 이전 스크립트 ─── */}
      {status?.status === "completed" && status?.result && (
        <div style={{
          padding: "16px 20px",
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-sm)",
          marginBottom: 16,
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8, marginBottom: 14,
            fontSize: "0.8rem", fontWeight: 700, color: "var(--color-text)",
          }}>
            <span style={{ color: "#16a34a" }}>●</span> Plan 결과
          </div>
          <PlanResultView
            result={status.result}
            runId={status.result?.artifacts?.run_id}
            architecture={status.result?.persisted_architecture || architecture}
            mappings={status.result?.persisted_mappings?.length
              ? status.result.persisted_mappings
              : (mapping?.mappings || [])}
            scopedRows={scopedRows}
            azureRegion={azureRegion}
            showExecutionLog
          />
        </div>
      )}

      {status?.status === "failed" && (
        <div className="form-error" style={{ marginBottom: 16 }}>
          <strong>Planning failed:</strong> {status.error}
        </div>
      )}
    </div>
  );
}

export default MigrationPage;
