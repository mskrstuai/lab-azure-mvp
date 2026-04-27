const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export async function startMigrationPlan(params) {
  const res = await fetch(`${API_BASE}/migration/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "마이그레이션 계획을 시작하지 못했습니다");
  }
  return res.json();
}

/**
 * Synchronously fetch Azure target mappings WITHOUT mutating React state —
 * used by flows like "Run migration plan" that want to ensure we have fresh
 * mappings before kicking off the planner.
 */
export async function fetchAzureMappings({
  resources,
  targetAzureRegion,
  sourceAwsRegion,
  signal,
} = {}) {
  const res = await fetch(`${API_BASE}/migration/azure-mapping`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resources,
      target_azure_region: targetAzureRegion || "eastus",
      source_aws_region: sourceAwsRegion || "",
    }),
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "리소스를 Azure 대상으로 매핑하지 못했습니다");
  }
  return res.json();
}

export async function getMigrationStatus(jobId) {
  const res = await fetch(`${API_BASE}/migration/run/${jobId}`);
  if (!res.ok) throw new Error("상태를 가져오지 못했습니다");
  return res.json();
}

export async function getActiveMigrationJob() {
  const res = await fetch(`${API_BASE}/migration/active-job`);
  if (!res.ok) throw new Error("실행 중인 작업을 확인하지 못했습니다");
  return res.json();
}

export async function fetchMigrationOutputs() {
  const res = await fetch(`${API_BASE}/migration/outputs`);
  if (!res.ok) throw new Error("출력 목록을 불러오지 못했습니다");
  return res.json();
}

export async function fetchMigrationOutput(runId) {
  const res = await fetch(`${API_BASE}/migration/outputs/${runId}`);
  if (!res.ok) throw new Error("출력을 불러오지 못했습니다");
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
    throw new Error(err.detail || "Terraform 파일을 불러오지 못했습니다");
  }
  return res.json();
}

/* ---------------- In-app Terraform deploy ---------------- */

export async function fetchDeployPreflight() {
  const res = await fetch(`${API_BASE}/migration/deploy/preflight`);
  if (!res.ok) throw new Error("배포 사전 점검을 불러오지 못했습니다");
  return res.json();
}

export async function startTerraformDeploy(runId, { action, subscriptionId, tenantId } = {}) {
  const res = await fetch(
    `${API_BASE}/migration/outputs/${encodeURIComponent(runId)}/deploy`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: action || "apply",
        subscription_id: subscriptionId || "",
        tenant_id: tenantId || "",
      }),
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Terraform 배포를 시작하지 못했습니다");
  }
  return res.json();
}

export async function fetchDeployStatus(deployId, since = 0) {
  const res = await fetch(
    `${API_BASE}/migration/deploy/${encodeURIComponent(deployId)}?since=${since}`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "배포 상태를 불러오지 못했습니다");
  }
  return res.json();
}

export async function getAwsStatus() {
  const res = await fetch(`${API_BASE}/aws/status`);
  if (!res.ok) throw new Error("AWS 상태를 확인하지 못했습니다");
  return res.json();
}

export async function listAwsServices() {
  const res = await fetch(`${API_BASE}/aws/services`);
  if (!res.ok) throw new Error("AWS 서비스 목록을 가져오지 못했습니다");
  return res.json();
}

export async function listAwsRegions() {
  const res = await fetch(`${API_BASE}/aws/regions`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "AWS Region 목록을 가져오지 못했습니다");
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
    throw new Error(err.detail || "AWS 리소스 스캔에 실패했습니다");
  }
  return res.json();
}

export async function listAwsResourceGroups(region) {
  const qs = region ? `?region=${encodeURIComponent(region)}` : "";
  const res = await fetch(`${API_BASE}/aws/resource-groups${qs}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Resource Group 목록을 가져오지 못했습니다");
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
    throw new Error(err.detail || "Resource Group 정보를 불러오지 못했습니다");
  }
  return res.json();
}
