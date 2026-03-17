import { useCallback, useEffect, useMemo, useState } from "react";
import {
  startRunAnalysis,
  getRunStatus,
  getActiveJob,
  fetchAnalysisOutputs,
  fetchAnalysisOutput,
  runSimulation,
} from "../api/apiClient";

const REGIONS = ["US-North", "US-South", "US-East", "US-West", "US-Midwest", "US-Northeast", "US-Southeast", "All"];
const DEFAULT_DATASET = "data/synthetic_promotions_snacks_bev.csv";

function formatNum(v) {
  if (v == null || (typeof v === "number" && Number.isNaN(v))) return "—";
  if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(v);
}

function AnalysisResultView({ result, showExecutionLog = false }) {
  const promotions = result?.json_data?.promotions;
  const hasPromotions = promotions?.length > 0;

  return (
    <div className="analysis-result-view">
      {hasPromotions && (
        <div className="result-section">
          <h3 className="result-section-title">
            📋 Recommended Promotions ({promotions.length})
          </h3>
          <PromotionsTable promotions={promotions} />
        </div>
      )}
      {result?.final_output && (
        <details className="result-details">
          <summary>Summary (markdown)</summary>
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
          <pre className="log-pre">{result.execution_log}</pre>
        </details>
      )}
      {result?.json_data && !hasPromotions && (
        <details className="result-details">
          <summary>Raw JSON</summary>
          <pre>{JSON.stringify(result.json_data, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

const SORTABLE_COLUMNS = [
  { key: "promo_event_id", label: "ID", type: "string" },
  { key: "market", label: "Market", type: "string" },
  { key: "retailer", label: "Retailer", type: "string" },
  { key: "brand", label: "Brand", type: "string" },
  { key: "category", label: "Category", type: "string" },
  { key: "offer_type", label: "Offer", type: "string" },
  { key: "discount_depth", label: "Discount", type: "number" },
  { key: "promo_start_date", label: "Dates", type: "string" },
  { key: "revenue", label: "Revenue", type: "number" },
  { key: "promo_uplift_pct", label: "Uplift", type: "number" },
  { key: "profit_roi", label: "ROI", type: "number" },
];

function getSortValue(p, key) {
  if (key === "revenue") {
    const vol = (p.baseline_volume || 0) + (p.incremental_volume || 0);
    return p.promo_unit_price != null && vol ? p.promo_unit_price * vol : 0;
  }
  const v = p[key];
  if (v == null) return key === "string" ? "" : 0;
  return v;
}

function PromotionsTable({ promotions }) {
  const [sortColumn, setSortColumn] = useState("profit_roi");
  const [sortAsc, setSortAsc] = useState(false);

  const handleSort = (key) => {
    setSortColumn(key);
    setSortAsc((prev) => (sortColumn === key ? !prev : true));
  };

  const sorted = useMemo(() => {
    if (!promotions?.length) return [];
    const col = SORTABLE_COLUMNS.find((c) => c.key === sortColumn);
    const type = col?.type || "string";
    return [...promotions].sort((a, b) => {
      const va = getSortValue(a, sortColumn);
      const vb = getSortValue(b, sortColumn);
      let cmp = 0;
      if (type === "number") cmp = (va || 0) - (vb || 0);
      else cmp = String(va || "").localeCompare(String(vb || ""));
      return sortAsc ? cmp : -cmp;
    });
  }, [promotions, sortColumn, sortAsc]);

  if (!promotions?.length) return null;
  return (
    <div className="table-wrapper analysis-result-table">
      <table>
        <thead>
          <tr>
            {SORTABLE_COLUMNS.map(({ key, label }) => (
              <th
                key={key}
                className="sortable"
                onClick={() => handleSort(key)}
              >
                {label}
                <span className={`sort-icon ${sortColumn === key ? "active" : ""}`}>
                  {sortColumn === key ? (sortAsc ? " ↑" : " ↓") : " ⇅"}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => (
            <tr key={p.promo_event_id}>
              <td><code>{p.promo_event_id}</code></td>
              <td>{p.market}</td>
              <td>{p.retailer}</td>
              <td>{p.brand}</td>
              <td>{p.category}</td>
              <td>{p.offer_type}</td>
              <td>{p.discount_depth != null ? `${(p.discount_depth * 100).toFixed(0)}%` : "—"}</td>
              <td className="date-cell">
                {p.promo_start_date} ~ {p.promo_end_date}
              </td>
              <td>
                {p.promo_unit_price != null && (p.baseline_volume != null || p.incremental_volume != null)
                  ? `$${formatNum(p.promo_unit_price * ((p.baseline_volume || 0) + (p.incremental_volume || 0)))}`
                  : "—"}
              </td>
              <td>{p.promo_uplift_pct != null ? `${(p.promo_uplift_pct * 100).toFixed(1)}%` : "—"}</td>
              <td>{p.profit_roi != null ? `${(p.profit_roi * 100).toFixed(1)}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const SIMULATE_COLUMNS = [
  { key: "promo_event_id", label: "ID", type: "string" },
  { key: "market", label: "Market", type: "string" },
  { key: "retailer", label: "Retailer", type: "string" },
  { key: "sku_id", label: "SKU", type: "string" },
  { key: "discount_depth", label: "Discount", type: "number" },
  { key: "promo_investment", label: "Investment", type: "number" },
  { key: "pred_incremental_volume", label: "Pred Vol", type: "number" },
  { key: "pred_incr_profit", label: "Pred Profit", type: "number" },
  { key: "pred_roi", label: "Pred ROI", type: "number" },
];

function SimulateTable({ promotions }) {
  const [sortColumn, setSortColumn] = useState("pred_roi");
  const [sortAsc, setSortAsc] = useState(false);

  const handleSort = (key) => {
    setSortColumn(key);
    setSortAsc((prev) => (sortColumn === key ? !prev : true));
  };

  const sorted = useMemo(() => {
    if (!promotions?.length) return [];
    const col = SIMULATE_COLUMNS.find((c) => c.key === sortColumn);
    const type = col?.type || "string";
    return [...promotions].sort((a, b) => {
      const va = a[sortColumn];
      const vb = b[sortColumn];
      let cmp = 0;
      if (type === "number") cmp = (va || 0) - (vb || 0);
      else cmp = String(va || "").localeCompare(String(vb || ""));
      return sortAsc ? cmp : -cmp;
    });
  }, [promotions, sortColumn, sortAsc]);

  return (
    <table>
      <thead>
        <tr>
          {SIMULATE_COLUMNS.map(({ key, label }) => (
            <th key={key} className="sortable" onClick={() => handleSort(key)}>
              {label}
              <span className={`sort-icon ${sortColumn === key ? "active" : ""}`}>
                {sortColumn === key ? (sortAsc ? " ↑" : " ↓") : " ⇅"}
              </span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((p, i) => (
          <tr key={i}>
            <td><code>{p.promo_event_id}</code></td>
            <td>{p.market}</td>
            <td>{p.retailer}</td>
            <td>{p.sku_id}</td>
            <td>{p.discount_depth != null ? `${(p.discount_depth * 100).toFixed(0)}%` : "—"}</td>
            <td>{p.promo_investment != null ? `$${Number(p.promo_investment).toFixed(0)}` : "—"}</td>
            <td>{p.pred_incremental_volume != null ? Number(p.pred_incremental_volume).toFixed(0) : "—"}</td>
            <td>{p.pred_incr_profit != null ? `$${Number(p.pred_incr_profit).toFixed(0)}` : "—"}</td>
            <td>{p.pred_roi != null ? (p.pred_roi * 100).toFixed(1) + "%" : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RunAnalysisPage() {
  const [subTab, setSubTab] = useState("run"); // run | outputs | simulate

  return (
    <section className="page-section">
      <h2 className="page-title">🔬 Run Analysis</h2>
      <p className="page-desc">
        Generate retail promotion recommendations using AI. Requires Azure OpenAI and Executor.
      </p>

      <div className="analysis-tabs">
        {[
          { key: "run", label: "Run analysis", icon: "🚀" },
          { key: "outputs", label: "Previous outputs", icon: "📁" },
          { key: "simulate", label: "Simulate output", icon: "📈" },
        ].map(({ key, label, icon }) => (
          <button
            key={key}
            className={`analysis-tab ${subTab === key ? "active" : ""}`}
            onClick={() => setSubTab(key)}
          >
            {icon} {label}
          </button>
        ))}
      </div>

      {subTab === "run" && <RunAnalysisForm />}
      {subTab === "outputs" && <PreviousOutputs />}
      {subTab === "simulate" && <SimulateOutput />}
    </section>
  );
}

function RunAnalysisForm() {
  const [instruction, setInstruction] = useState("Maximize volume uplift while maintaining positive ROI");
  const [numPromotions, setNumPromotions] = useState(15);
  const [minDiscount, setMinDiscount] = useState(10);
  const [regionFilter, setRegionFilter] = useState(["All"]);
  const [outputFormat, setOutputFormat] = useState("json");
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  const pollStatus = useCallback(() => {
    if (!jobId) return;
    getRunStatus(jobId)
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
    getActiveJob()
      .then((res) => {
        if (res.job_id) {
          setJobId(res.job_id);
        }
      })
      .catch(() => {});
  }, []);

  const isRunning = !!jobId && status?.status !== "completed" && status?.status !== "failed";

  const handleRun = () => {
    if (isRunning) return;
    setError(null);
    setStatus(null);
    startRunAnalysis({
      instruction: instruction.trim(),
      num_promotions: numPromotions,
      min_discount: minDiscount,
      region_filter: regionFilter,
      output_format: outputFormat,
    })
      .then((res) => {
        setJobId(res.job_id);
      })
      .catch((e) => setError(e.message));
  };

  const toggleRegion = (r) => {
    if (r === "All") {
      setRegionFilter(["All"]);
    } else {
      setRegionFilter((prev) => {
        const next = prev.filter((x) => x !== "All" && x !== r);
        if (prev.includes(r)) return next.length ? next : ["All"];
        next.push(r);
        return next;
      });
    }
  };

  return (
    <div className="run-analysis-form">
      <div className="form-section">
        <label>Business Objective</label>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={4}
          placeholder="Describe your business goal..."
        />
      </div>
      <div className="form-row">
        <div className="form-field">
          <label>Number of promotions</label>
          <input
            type="number"
            min={1}
            max={50}
            value={numPromotions}
            onChange={(e) => setNumPromotions(Number(e.target.value))}
          />
        </div>
        <div className="form-field">
          <label>Minimum discount (%)</label>
          <input
            type="number"
            min={0}
            max={100}
            value={minDiscount}
            onChange={(e) => setMinDiscount(Number(e.target.value))}
          />
        </div>
      </div>
      <div className="form-section">
        <label>Region(s)</label>
        <div className="region-chips">
          {REGIONS.map((r) => (
            <button
              key={r}
              type="button"
              className={`chip ${regionFilter.includes(r) ? "active" : ""}`}
              onClick={() => toggleRegion(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      <div className="form-section">
        <label>Output format</label>
        <select value={outputFormat} onChange={(e) => setOutputFormat(e.target.value)}>
          <option value="json">JSON</option>
          <option value="plain_text">Plain text</option>
        </select>
      </div>

      {error && <div className="form-error">{error}</div>}

      {isRunning && (
        <div className="run-loading-banner">
          <div className="spinner" />
          <span>
            {status?.status === "running" ? "Analysis running..." : "Starting analysis..."}
          </span>
        </div>
      )}

      <button
        className="run-btn"
        onClick={handleRun}
        disabled={isRunning}
      >
        {isRunning ? "⏳ Running..." : "🚀 Run Analysis"}
      </button>

      {status?.status === "completed" && status?.result && (
        <AnalysisResultView result={status.result} />
      )}
      {status?.status === "failed" && (
        <div className="form-error">
          <strong>Analysis failed:</strong> {status.error}
        </div>
      )}
    </div>
  );
}

function PreviousOutputs() {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [output, setOutput] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAnalysisOutputs()
      .then((res) => {
        const list = res.runs || [];
        setRuns(list);
        if (list.length > 0 && !selected) setSelected(list[0].run_id);
      })
      .catch(() => setRuns([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) {
      setOutput(null);
      return;
    }
    fetchAnalysisOutput(selected)
      .then(setOutput)
      .catch(() => setOutput(null));
  }, [selected]);

  if (loading) return <div className="loading"><div className="spinner" /><p>Loading...</p></div>;
  if (runs.length === 0) return <div className="empty-state"><div className="icon">📁</div><p>No previous runs. Run analysis first.</p></div>;

  return (
    <div className="outputs-panel">
      <div className="outputs-sidebar">
        <h3 className="sidebar-title">Previous runs</h3>
        <div className="run-list">
          {runs.map((r) => (
            <button
              key={r.run_id}
              type="button"
              className={`run-card ${selected === r.run_id ? "active" : ""}`}
              onClick={() => setSelected(r.run_id)}
            >
              <span className="run-id">{r.run_id}</span>
              <span className="run-badges">
                {r.has_summary && <span className="badge">MD</span>}
                {r.has_json && <span className="badge">JSON</span>}
              </span>
            </button>
          ))}
        </div>
      </div>
      {output && (
        <div className="outputs-content">
          <AnalysisResultView
            result={{
              final_output: output.summary,
              json_data: output.json_data,
              execution_log: output.execution_log,
            }}
            showExecutionLog
          />
        </div>
      )}
    </div>
  );
}

function SimulateOutput() {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [datasetPath, setDatasetPath] = useState(DEFAULT_DATASET);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [runsLoading, setRunsLoading] = useState(true);

  useEffect(() => {
    fetchAnalysisOutputs()
      .then((res) => setRuns((res.runs || []).filter((r) => r.has_json)))
      .catch(() => setRuns([]))
      .finally(() => setRunsLoading(false));
  }, []);

  const handleSimulate = () => {
    if (!selected) return;
    setLoading(true);
    setResult(null);
    runSimulation(selected, datasetPath)
      .then(setResult)
      .catch((e) => setResult({ error: e.message }))
      .finally(() => setLoading(false));
  };

  if (runsLoading) return <div className="loading"><div className="spinner" /><p>Loading...</p></div>;
  if (runs.length === 0) return <div className="empty-state"><div className="icon">📈</div><p>No runs with JSON output. Run analysis with JSON format first.</p></div>;

  return (
    <div className="simulate-panel">
      <div className="form-row">
        <div className="form-field">
          <label>Select run to simulate</label>
          <select value={selected || ""} onChange={(e) => setSelected(e.target.value || null)}>
            <option value="">-- Select --</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>{r.run_id}</option>
            ))}
          </select>
        </div>
        <div className="form-field">
          <label>Dataset path</label>
          <input
            type="text"
            value={datasetPath}
            onChange={(e) => setDatasetPath(e.target.value)}
            placeholder="data/synthetic_promotions_snacks_bev.csv"
          />
        </div>
      </div>
      <button className="run-btn" onClick={handleSimulate} disabled={!selected || loading}>
        {loading ? "⏳ Running..." : "▶ Run simulation"}
      </button>
      {result?.error && <div className="form-error">{result.error}</div>}
      {result?.summary && (
        <div className="sim-result">
          <h3>Simulation result</h3>
          <div className="sim-metrics">
            <span>Candidates: {result.summary.num_candidates_in}</span>
            <span>Scored: {result.summary.num_candidates_scored}</span>
            <span>ROI positive: {result.summary.pred_roi_positive_count}</span>
          </div>
          {result.scored_promotions?.length > 0 && (
            <div className="table-wrapper">
              <SimulateTable promotions={result.scored_promotions} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default RunAnalysisPage;
