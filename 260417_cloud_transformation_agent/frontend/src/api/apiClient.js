const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export async function startMigrationPlan(params) {
  const res = await fetch(`${API_BASE}/migration/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to start migration planning");
  }
  return res.json();
}

export async function getMigrationStatus(jobId) {
  const res = await fetch(`${API_BASE}/migration/run/${jobId}`);
  if (!res.ok) throw new Error("Failed to get status");
  return res.json();
}

export async function getActiveMigrationJob() {
  const res = await fetch(`${API_BASE}/migration/active-job`);
  if (!res.ok) throw new Error("Failed to check active job");
  return res.json();
}

export async function fetchMigrationOutputs() {
  const res = await fetch(`${API_BASE}/migration/outputs`);
  if (!res.ok) throw new Error("Failed to load outputs");
  return res.json();
}

export async function fetchMigrationOutput(runId) {
  const res = await fetch(`${API_BASE}/migration/outputs/${runId}`);
  if (!res.ok) throw new Error("Failed to load output");
  return res.json();
}

export function terraformZipUrl(runId) {
  return `${API_BASE}/migration/outputs/${encodeURIComponent(runId)}/terraform.zip`;
}

export async function fetchTerraformFile(runId, filename) {
  const res = await fetch(
    `${API_BASE}/migration/outputs/${encodeURIComponent(runId)}/terraform/${encodeURIComponent(filename)}`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to load terraform file");
  }
  return res.json();
}

export async function getAwsStatus() {
  const res = await fetch(`${API_BASE}/aws/status`);
  if (!res.ok) throw new Error("Failed to check AWS status");
  return res.json();
}

export async function listAwsServices() {
  const res = await fetch(`${API_BASE}/aws/services`);
  if (!res.ok) throw new Error("Failed to list AWS services");
  return res.json();
}

export async function listAwsRegions() {
  const res = await fetch(`${API_BASE}/aws/regions`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to list AWS regions");
  }
  return res.json();
}

export async function scanAwsResources({ region, services, resourceGroup }) {
  const res = await fetch(`${API_BASE}/aws/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      region,
      services,
      resource_group: resourceGroup || null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to scan AWS resources");
  }
  return res.json();
}

export async function listAwsResourceGroups(region) {
  const qs = region ? `?region=${encodeURIComponent(region)}` : "";
  const res = await fetch(`${API_BASE}/aws/resource-groups${qs}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to list resource groups");
  }
  return res.json();
}

export async function describeAwsResourceGroup(groupName, region) {
  const qs = region ? `?region=${encodeURIComponent(region)}` : "";
  const res = await fetch(
    `${API_BASE}/aws/resource-groups/${encodeURIComponent(groupName)}${qs}`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to load resource group");
  }
  return res.json();
}
