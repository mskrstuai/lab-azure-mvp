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
  targetSubscriptionId,
  signal,
} = {}) {
  const res = await fetch(`${API_BASE}/migration/azure-mapping`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resources,
      target_azure_region:    targetAzureRegion || "eastus",
      source_aws_region:      sourceAwsRegion || "",
      target_subscription_id: targetSubscriptionId || "",
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

export async function deletePlanOutput(runId) {
  const res = await fetch(`${API_BASE}/migration/outputs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Plan 삭제 실패");
  return data;
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

/* ===================== Phase 3: Deploy v2 ======================= */

export async function startDeployV2({
  runId, sessionId, tfvars, autoRollback = true,
  azureSubscriptionId, azureSubscriptionName, azureRegion,
  awsAccountId, awsRegion,
} = {}) {
  const res = await fetch(`${API_BASE}/deploy/v2/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_id:                  runId,
      session_id:              sessionId || null,
      // Fallback scope (used when backend session is gone after reload):
      azure_subscription_id:   azureSubscriptionId || null,
      azure_subscription_name: azureSubscriptionName || null,
      azure_region:            azureRegion || null,
      aws_account_id:          awsAccountId || null,
      aws_region:              awsRegion || null,
      tfvars:                  tfvars || null,
      auto_rollback:           autoRollback,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Deploy 시작에 실패했습니다");
  return data;
}

export async function resetDeployWorkdir(deployId) {
  const res = await fetch(`${API_BASE}/deploy/v2/reset/${encodeURIComponent(deployId)}`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "워크 디렉토리 초기화 실패");
  return data;
}

export async function getRunVariables(runId) {
  const res = await fetch(`${API_BASE}/migration/outputs/${encodeURIComponent(runId)}/variables`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "변수 정보 조회 실패");
  return data;
}

export async function listAllDeploys() {
  const res = await fetch(`${API_BASE}/deploy/v2/list`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Deploy 목록 조회 실패");
  return data;
}

export async function listDeploysForRun(runId) {
  const res = await fetch(`${API_BASE}/deploy/v2/by-run/${encodeURIComponent(runId)}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Deploy 목록 조회 실패");
  return data;
}

export async function getDeployV2Status(deployId, since = 0) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}?since=${since}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "상태 조회 실패");
  return data;
}

export async function approveDeployV2Plan(deployId) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/approve`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Plan 승인 실패");
  return data;
}

export async function cancelDeployV2(deployId) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/cancel`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "취소 실패");
  return data;
}

export async function completeDataMigrationStep(deployId, idx) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/data-migration/${idx}/complete`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "스크립트 완료 처리 실패");
  return data;
}

export async function skipDataMigration(deployId) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/skip-data-migration`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "건너뛰기 실패");
  return data;
}

/* Apply 실패 → 수정 → 재시도 */

export async function listDeployFiles(deployId) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/files`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "파일 목록 조회 실패");
  return data;
}

export async function requestAiFix(deployId, { strategy = "patch_and_retry" } = {}) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/ai-fix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "AI 수정 요청 실패");
  return data;
}

export async function applyFix(deployId, files) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/apply-fix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "패치 적용 실패");
  return data;
}

export async function retryDeployApply(deployId) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/retry-apply`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "재시도 실패");
  return data;
}

export async function abandonDeploy(deployId) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/abandon`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "포기 실패");
  return data;
}

export async function continueAutoFix(deployId) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/continue-auto-fix`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "자동 수정 재시도 실패");
  return data;
}

export async function destroyAndRestart(deployId, { preserveCode = false, pendingFixes = null } = {}) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/destroy-restart`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      preserve_code: !!preserveCode,
      pending_fixes: pendingFixes || [],
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "destroy 후 재시작 실패");
  return data;
}

export async function checkDeployScope({ runId, subscriptionId, region } = {}) {
  const res = await fetch(`${API_BASE}/deploy/v2/scope-check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_id:          runId,
      subscription_id: subscriptionId,
      region:          region,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "scope 검사 실패");
  return data;
}

export async function execInDeployWorkdir(deployId, cmd) {
  const res = await fetch(`${API_BASE}/deploy/v2/${encodeURIComponent(deployId)}/exec`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cmd }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "명령 실행 실패");
  return data;
}

/* ===================== Phase 2: Plan ============================ */

export async function assessResources(resources) {
  const res = await fetch(`${API_BASE}/plan/assess`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resources }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "평가에 실패했습니다");
  return data;
}

export async function generateDataMigrationScripts({ resources, azureRegion, azureStorageAccount } = {}) {
  const res = await fetch(`${API_BASE}/plan/data-migration-scripts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resources,
      azure_region: azureRegion,
      azure_storage_account: azureStorageAccount,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "스크립트 생성에 실패했습니다");
  return data;
}

/* ===================== Phase 1: Architecture ==================== */

export async function scanArchitecture({ sessionId, region, resourceGroup, tagFilters } = {}) {
  const res = await fetch(`${API_BASE}/architecture/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      region,
      resource_group: resourceGroup || null,
      tag_filters: tagFilters || null,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "아키텍처 스캔에 실패했습니다");
  return data;
}

export async function listArchResourceGroups(sessionId, region) {
  const qs = new URLSearchParams({ session_id: sessionId, ...(region ? { region } : {}) });
  const res = await fetch(`${API_BASE}/architecture/resource-groups?${qs}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Resource Group 목록을 가져오지 못했습니다");
  return data;
}

export async function listArchTagKeys(sessionId, region) {
  const qs = new URLSearchParams({ session_id: sessionId, ...(region ? { region } : {}) });
  const res = await fetch(`${API_BASE}/architecture/tag-keys?${qs}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Tag 키 목록을 가져오지 못했습니다");
  return data;
}

/* ===================== Phase 0: Credentials ===================== */

export async function connectAws(params) {
  const res = await fetch(`${API_BASE}/credentials/aws/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "AWS 연결에 실패했습니다");
  return data;
}

export async function assumeAwsRole(params) {
  const res = await fetch(`${API_BASE}/credentials/aws/assume-role`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Role assume에 실패했습니다");
  return data;
}

export async function connectAzure(params) {
  const res = await fetch(`${API_BASE}/credentials/azure/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Azure 연결에 실패했습니다");
  return data;
}

export async function verifyAzureSubscription(sessionId, subscriptionId) {
  const res = await fetch(`${API_BASE}/credentials/azure/verify-subscription`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, subscription_id: subscriptionId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "구독 확인에 실패했습니다");
  return data;
}

export async function setMigrationScope(params) {
  const res = await fetch(`${API_BASE}/credentials/scope`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "범위 설정에 실패했습니다");
  return data;
}

export async function getCredentialSession(sessionId) {
  const res = await fetch(`${API_BASE}/credentials/session/${sessionId}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "세션 조회에 실패했습니다");
  return data;
}

export async function deleteCredentialSession(sessionId) {
  await fetch(`${API_BASE}/credentials/session/${sessionId}`, { method: "DELETE" });
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
