const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export async function fetchPromotions(params = {}) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value != null && value !== "") searchParams.append(key, value);
  });
  const url = `${API_BASE}/promotions?${searchParams}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load promotions");
  return res.json();
}

export async function fetchPromotion(id) {
  const res = await fetch(`${API_BASE}/promotions/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error("Promotion not found");
  return res.json();
}

export async function fetchFilterOptions() {
  const res = await fetch(`${API_BASE}/promotions/filter-options`);
  if (!res.ok) throw new Error("Failed to load filter options");
  return res.json();
}

export async function fetchStats() {
  const res = await fetch(`${API_BASE}/promotions/stats`);
  if (!res.ok) throw new Error("Failed to load stats");
  return res.json();
}

// Run Analysis
export async function startRunAnalysis(params) {
  const res = await fetch(`${API_BASE}/analysis/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to start analysis");
  }
  return res.json();
}

export async function getRunStatus(jobId) {
  const res = await fetch(`${API_BASE}/analysis/run/${jobId}`);
  if (!res.ok) throw new Error("Failed to get status");
  return res.json();
}

export async function getActiveJob() {
  const res = await fetch(`${API_BASE}/analysis/active-job`);
  if (!res.ok) throw new Error("Failed to check active job");
  return res.json();
}

export async function fetchAnalysisOutputs() {
  const res = await fetch(`${API_BASE}/analysis/outputs`);
  if (!res.ok) throw new Error("Failed to load outputs");
  return res.json();
}

export async function fetchAnalysisOutput(runId) {
  const res = await fetch(`${API_BASE}/analysis/outputs/${runId}`);
  if (!res.ok) throw new Error("Failed to load output");
  return res.json();
}

export async function runSimulation(runId, datasetPath) {
  const res = await fetch(`${API_BASE}/analysis/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, dataset_path: datasetPath }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Simulation failed");
  }
  return res.json();
}
