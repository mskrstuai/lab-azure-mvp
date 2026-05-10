import { useState } from "react";
import {
  assumeAwsRole,
  connectAws,
  connectAzure,
  setMigrationScope,
  verifyAzureSubscription,
} from "../api/apiClient";

const AWS_REGIONS = [
  "us-east-1", "us-east-2", "us-west-1", "us-west-2",
  "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
  "ap-southeast-1", "ap-southeast-2", "ap-south-1",
  "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1",
  "sa-east-1", "ca-central-1",
];

const AZURE_REGIONS = [
  { id: "koreacentral",      label: "Korea Central" },
  { id: "koreasouth",        label: "Korea South" },
  { id: "eastus",            label: "East US" },
  { id: "eastus2",           label: "East US 2" },
  { id: "westus2",           label: "West US 2" },
  { id: "westus3",           label: "West US 3" },
  { id: "japaneast",         label: "Japan East" },
  { id: "southeastasia",     label: "Southeast Asia" },
  { id: "australiaeast",     label: "Australia East" },
  { id: "northeurope",       label: "North Europe" },
  { id: "westeurope",        label: "West Europe" },
  { id: "uksouth",           label: "UK South" },
  { id: "germanywestcentral", label: "Germany West Central" },
  { id: "canadacentral",     label: "Canada Central" },
];

/* ── Small utility components ─────────────────────────────────── */

function StepHeader({ number, title, done }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
      <div style={{
        width: 28, height: 28, borderRadius: "50%",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: "0.8rem", fontWeight: 700,
        background: done ? "#16a34a" : "var(--color-accent)",
        color: "#fff",
        flexShrink: 0,
      }}>
        {done ? "✓" : number}
      </div>
      <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 600 }}>{title}</h3>
    </div>
  );
}

function Field({ label, children, hint }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
      <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--color-text-light)" }}>
        {label}
      </label>
      {children}
      {hint && <span style={{ fontSize: "0.74rem", color: "var(--color-text-light)" }}>{hint}</span>}
    </div>
  );
}

function Sel({ value, onChange, disabled, children }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} disabled={disabled}
      style={{ padding: "6px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border)", background: "var(--color-surface)", fontSize: "0.85rem" }}>
      {children}
    </select>
  );
}

function Inp({ value, onChange, placeholder, type = "text", disabled }) {
  return (
    <input type={type} value={value} onChange={e => onChange(e.target.value)}
      placeholder={placeholder} disabled={disabled}
      style={{ padding: "6px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border)", background: "var(--color-surface)", fontSize: "0.85rem" }} />
  );
}

function ConnectBtn({ loading, label, loadingLabel, onClick, disabled }) {
  return (
    <button type="button" className="run-btn action-btn" onClick={onClick}
      disabled={loading || disabled}
      style={{ marginTop: 8, minHeight: 36, padding: "0 20px", fontSize: "0.85rem" }}>
      {loading ? <><span className="spinner" />{loadingLabel}</> : label}
    </button>
  );
}

function PermissionsTable({ permissions }) {
  const ok = permissions.filter(p => p.ok);
  const fail = permissions.filter(p => !p.ok);
  return (
    <details style={{ marginTop: 10 }}>
      <summary style={{ cursor: "pointer", fontSize: "0.8rem", color: "var(--color-text-light)" }}>
        권한 점검 — {ok.length}/{permissions.length} 통과
        {fail.length > 0 && <span style={{ color: "#b91c1c", marginLeft: 6 }}>({fail.length}개 실패)</span>}
      </summary>
      <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
        {permissions.map(p => (
          <span key={`${p.service}-${p.action}`} style={{
            fontSize: "0.72rem", padding: "2px 8px",
            borderRadius: 99, border: "1px solid",
            borderColor: p.ok ? "#16a34a" : "#b91c1c",
            color: p.ok ? "#16a34a" : "#b91c1c",
            background: p.ok ? "rgba(22,163,74,0.06)" : "rgba(185,28,28,0.06)",
          }}>
            {p.ok ? "✓" : "✗"} {p.service}:{p.action}
            {!p.ok && p.note && ` (${p.note})`}
          </span>
        ))}
      </div>
    </details>
  );
}

function SuccessBadge({ children }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "10px 14px", borderRadius: "var(--radius-sm)",
      background: "rgba(22,163,74,0.08)", border: "1px solid #16a34a",
      fontSize: "0.85rem", color: "#15803d",
    }}>
      <span style={{ fontSize: "1rem" }}>✓</span>
      {children}
    </div>
  );
}

function ErrorBox({ msg, onDismiss }) {
  if (!msg) return null;
  return (
    <div className="form-error" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, marginTop: 8 }}>
      <span style={{ flex: 1 }}>{msg}</span>
      {onDismiss && <button type="button" onClick={onDismiss} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1rem", lineHeight: 1 }}>×</button>}
    </div>
  );
}

/* ── Step 1: AWS ──────────────────────────────────────────────── */

function AwsStep({ sessionId, setSessionId, awsResult, setAwsResult }) {
  const [method, setMethod]   = useState("profile");
  const [profile, setProfile] = useState("default");
  const [keyId, setKeyId]     = useState("");
  const [secret, setSecret]   = useState("");
  const [token, setToken]     = useState("");
  const [region, setRegion]   = useState("us-east-1");
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  const connect = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { method, region, session_id: sessionId || undefined };
      if (method === "profile")     params.profile = profile;
      if (method === "static_keys") { params.access_key_id = keyId; params.secret_access_key = secret; if (token) params.session_token = token; }
      const res = await connectAws(params);
      if (!sessionId) setSessionId(res.session_id);
      setAwsResult(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const reconnect = () => { setAwsResult(null); setError(null); };

  if (awsResult) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <SuccessBadge>
          <div>
            <strong>{awsResult.identity.arn}</strong>
            <div style={{ fontSize: "0.78rem", opacity: 0.8 }}>Account: {awsResult.identity.account_id} · Region: {awsResult.region}</div>
          </div>
        </SuccessBadge>
        {awsResult.permissions && <PermissionsTable permissions={awsResult.permissions} />}
        <button type="button" onClick={reconnect}
          style={{ alignSelf: "flex-start", fontSize: "0.78rem", background: "none", border: "none", color: "var(--color-text-light)", cursor: "pointer", padding: 0, textDecoration: "underline" }}>
          다른 자격증명으로 재연결
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <Field label="인증 방식">
        <Sel value={method} onChange={setMethod} disabled={loading}>
          <option value="profile">AWS Profile (~/.aws/credentials)</option>
          <option value="static_keys">Access Key + Secret</option>
          <option value="default">기본 체인 (EC2 Instance Role 등)</option>
        </Sel>
      </Field>

      {method === "profile" && (
        <Field label="Profile 이름" hint="~/.aws/credentials 또는 ~/.aws/config에 정의된 프로파일">
          <Inp value={profile} onChange={setProfile} placeholder="default" disabled={loading} />
        </Field>
      )}

      {method === "static_keys" && (
        <>
          <Field label="Access Key ID">
            <Inp value={keyId} onChange={setKeyId} placeholder="AKIAXXXXXXXXXXXXXXXX" disabled={loading} />
          </Field>
          <Field label="Secret Access Key">
            <Inp value={secret} onChange={setSecret} type="password" placeholder="wJalrXUt..." disabled={loading} />
          </Field>
          <Field label="Session Token" hint="STS 임시 자격증명일 때만 입력 (선택)">
            <Inp value={token} onChange={setToken} type="password" placeholder="선택 사항" disabled={loading} />
          </Field>
        </>
      )}

      <Field label="기본 Region">
        <Sel value={region} onChange={setRegion} disabled={loading}>
          {AWS_REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
        </Sel>
      </Field>

      <ErrorBox msg={error} onDismiss={() => setError(null)} />
      <ConnectBtn loading={loading} label="AWS 연결" loadingLabel="연결 중…" onClick={connect} />
    </div>
  );
}

/* ── Step 2: Azure ────────────────────────────────────────────── */

function AzureStep({ sessionId, setSessionId, azureResult, setAzureResult }) {
  const [method, setMethod]     = useState("cli");
  const [tenantId, setTenantId] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  const connect = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { method, session_id: sessionId || undefined };
      if (method === "service_principal") { params.tenant_id = tenantId; params.client_id = clientId; params.client_secret = clientSecret; }
      const res = await connectAzure(params);
      if (!sessionId) setSessionId(res.session_id);
      setAzureResult(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const reconnect = () => { setAzureResult(null); setError(null); };

  if (azureResult) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <SuccessBadge>
          <div>
            <strong>Azure 연결 완료</strong>
            <div style={{ fontSize: "0.78rem", opacity: 0.8 }}>
              Subscription {azureResult.subscriptions.length}개 접근 가능
              {azureResult.tenant_id && ` · Tenant: ${azureResult.tenant_id}`}
            </div>
          </div>
        </SuccessBadge>
        <button type="button" onClick={reconnect}
          style={{ alignSelf: "flex-start", fontSize: "0.78rem", background: "none", border: "none", color: "var(--color-text-light)", cursor: "pointer", padding: 0, textDecoration: "underline" }}>
          다른 자격증명으로 재연결
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <Field label="인증 방식">
        <Sel value={method} onChange={setMethod} disabled={loading}>
          <option value="cli">Azure CLI (az login)</option>
          <option value="service_principal">Service Principal</option>
        </Sel>
      </Field>

      {method === "cli" && (
        <div style={{ padding: "10px 12px", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", fontSize: "0.82rem", color: "var(--color-text-light)", marginBottom: 12 }}>
          터미널에서 <code style={{ background: "rgba(0,0,0,0.06)", padding: "1px 5px", borderRadius: 3 }}>az login</code> 을 먼저 실행해 주세요.
        </div>
      )}

      {method === "service_principal" && (
        <>
          <Field label="Tenant ID">
            <Inp value={tenantId} onChange={setTenantId} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" disabled={loading} />
          </Field>
          <Field label="Client ID (App ID)">
            <Inp value={clientId} onChange={setClientId} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" disabled={loading} />
          </Field>
          <Field label="Client Secret">
            <Inp value={clientSecret} onChange={setClientSecret} type="password" placeholder="••••••••" disabled={loading} />
          </Field>
          <div style={{ fontSize: "0.75rem", color: "var(--color-text-light)", marginBottom: 12 }}>
            필요 권한: 대상 Subscription의 <strong>Contributor</strong> (배포) 또는 <strong>Reader</strong> (분석 전용)
          </div>
        </>
      )}

      <ErrorBox msg={error} onDismiss={() => setError(null)} />
      <ConnectBtn loading={loading} label="Azure 연결" loadingLabel="연결 중…" onClick={connect} />
    </div>
  );
}

/* ── Step 3: Scope ────────────────────────────────────────────── */

function ScopeStep({ sessionId, awsResult, azureResult, scope, setScope }) {
  const accounts = awsResult?.org_accounts || [];
  const subscriptions = azureResult?.subscriptions || [];

  const [awsAccount, setAwsAccount]     = useState(accounts[0]?.account_id || "");
  const [awsRegion, setAwsRegion]       = useState(awsResult?.region || "us-east-1");
  const [azureSub, setAzureSub]         = useState(subscriptions[0]?.subscription_id || "");
  const [azureRegion, setAzureRegion]   = useState("koreacentral");
  const [assumeRole, setAssumeRole]     = useState(false);
  const [roleName, setRoleName]         = useState("MigrationReadRole");
  const [loading, setLoading]           = useState(false);
  const [verifying, setVerifying]       = useState(false);
  const [error, setError]               = useState(null);

  const needsAssumeRole = accounts.length > 1 && awsAccount !== awsResult?.identity?.account_id;
  const selectedSub = subscriptions.find(s => s.subscription_id === azureSub);

  const confirm = async () => {
    setError(null);
    // If cross-account, assume role first
    if (needsAssumeRole && assumeRole) {
      setLoading(true);
      try {
        await assumeAwsRole({ session_id: sessionId, account_id: awsAccount, role_name: roleName });
      } catch (e) {
        setError(`Role assume 실패: ${e.message}`);
        setLoading(false);
        return;
      }
    }

    // Verify Azure subscription access
    setVerifying(true);
    try {
      const check = await verifyAzureSubscription(sessionId, azureSub);
      if (!check.accessible) {
        setError(`Azure Subscription 접근 불가: ${check.reason}`);
        setVerifying(false);
        setLoading(false);
        return;
      }
    } catch (e) {
      setError(`Azure 검증 실패: ${e.message}`);
      setVerifying(false);
      setLoading(false);
      return;
    }
    setVerifying(false);

    try {
      const res = await setMigrationScope({
        session_id: sessionId,
        aws_account_id: awsAccount,
        aws_region: awsRegion,
        azure_subscription_id: azureSub,
        azure_subscription_name: selectedSub?.display_name || azureSub,
        azure_region: azureRegion,
      });
      setScope(res.scope);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  if (scope) {
    return (
      <SuccessBadge>
        <div>
          <strong>마이그레이션 범위 확정</strong>
          <div style={{ fontSize: "0.78rem", opacity: 0.8, marginTop: 2 }}>
            AWS {scope.aws_account_id} ({scope.aws_region})
            {" → "}
            Azure {scope.azure_subscription_name} ({scope.azure_region})
          </div>
        </div>
      </SuccessBadge>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 16 }}>
        {/* AWS side */}
        <div>
          <div style={{ fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-light)", marginBottom: 8 }}>
            출발지 (AWS)
          </div>
          <Field label="Account">
            <Sel value={awsAccount} onChange={setAwsAccount} disabled={loading}>
              {accounts.map(a => (
                <option key={a.account_id} value={a.account_id}>
                  {a.name} ({a.account_id})
                </option>
              ))}
            </Sel>
          </Field>
          {needsAssumeRole && (
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.82rem", cursor: "pointer", marginBottom: 6 }}>
                <input type="checkbox" checked={assumeRole} onChange={e => setAssumeRole(e.target.checked)} />
                Cross-account Role Assume
              </label>
              {assumeRole && (
                <Field label="Role 이름" hint="대상 계정에 사전 생성된 IAM Role">
                  <Inp value={roleName} onChange={setRoleName} placeholder="MigrationReadRole" disabled={loading} />
                </Field>
              )}
            </div>
          )}
          <Field label="Region">
            <Sel value={awsRegion} onChange={setAwsRegion} disabled={loading}>
              {AWS_REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
            </Sel>
          </Field>
        </div>

        {/* Azure side */}
        <div>
          <div style={{ fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-light)", marginBottom: 8 }}>
            목적지 (Azure)
          </div>
          <Field label="Subscription">
            <Sel value={azureSub} onChange={setAzureSub} disabled={loading}>
              {subscriptions.map(s => (
                <option key={s.subscription_id} value={s.subscription_id}>
                  {s.display_name}
                </option>
              ))}
            </Sel>
          </Field>
          {selectedSub && (
            <div style={{ fontSize: "0.74rem", color: "var(--color-text-light)", marginBottom: 12, fontFamily: "monospace" }}>
              {selectedSub.subscription_id}
            </div>
          )}
          <Field label="Region">
            <Sel value={azureRegion} onChange={setAzureRegion} disabled={loading}>
              {AZURE_REGIONS.map(r => <option key={r.id} value={r.id}>{r.label} ({r.id})</option>)}
            </Sel>
          </Field>
        </div>
      </div>

      <ErrorBox msg={error} onDismiss={() => setError(null)} />

      <button type="button" className="run-btn action-btn" onClick={confirm}
        disabled={loading || verifying || !awsAccount || !azureSub}
        style={{ alignSelf: "flex-start", marginTop: 4, minHeight: 36, padding: "0 20px", fontSize: "0.85rem" }}>
        {loading ? <><span className="spinner" />Role 연결 중…</>
          : verifying ? <><span className="spinner" />Azure 접근 확인 중…</>
          : "범위 확정"}
      </button>
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────────── */

export default function CredentialsPage({ sessionId, setSessionId, onReady }) {
  const [awsResult, setAwsResult]   = useState(null);
  const [azureResult, setAzureResult] = useState(null);
  const [scope, setScope]           = useState(null);

  const awsDone   = !!awsResult;
  const azureDone = !!azureResult;
  const scopeDone = !!scope;
  const allDone   = awsDone && azureDone && scopeDone;

  const handleSetScope = (s) => {
    setScope(s);
    if (s) onReady?.({ sessionId, scope: s });
  };

  const reset = () => {
    setAwsResult(null);
    setAzureResult(null);
    setScope(null);
    setSessionId(null);
  };

  return (
    <section className="page-section">
      <h2 className="page-title">🔑 Credentials & Scope</h2>
      <p className="page-desc">
        AWS와 Azure 자격증명을 연결하고, 마이그레이션 범위(어느 계정 → 어느 구독)를 확정합니다.
        자격증명은 서버 메모리에만 보관되며 디스크나 네트워크로 전송되지 않습니다.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 860 }}>
        {/* Step 1 */}
        <div style={{ padding: "20px 24px", border: "1px solid var(--color-border)", borderRadius: "var(--radius)", background: "var(--color-surface)" }}>
          <StepHeader number={1} title="AWS 연결" done={awsDone} />
          <AwsStep
            sessionId={sessionId}
            setSessionId={setSessionId}
            awsResult={awsResult}
            setAwsResult={setAwsResult}
          />
        </div>

        {/* Step 2 */}
        <div style={{
          padding: "20px 24px", border: "1px solid var(--color-border)", borderRadius: "var(--radius)", background: "var(--color-surface)",
          opacity: awsDone ? 1 : 0.45, pointerEvents: awsDone ? "auto" : "none",
        }}>
          <StepHeader number={2} title="Azure 연결" done={azureDone} />
          {awsDone
            ? <AzureStep sessionId={sessionId} setSessionId={setSessionId} azureResult={azureResult} setAzureResult={setAzureResult} />
            : <p style={{ fontSize: "0.82rem", color: "var(--color-text-light)", margin: 0 }}>AWS 연결 후 활성화됩니다.</p>
          }
        </div>

        {/* Step 3 */}
        <div style={{
          padding: "20px 24px", border: "1px solid var(--color-border)", borderRadius: "var(--radius)", background: "var(--color-surface)",
          opacity: awsDone && azureDone ? 1 : 0.45, pointerEvents: awsDone && azureDone ? "auto" : "none",
        }}>
          <StepHeader number={3} title="마이그레이션 범위 선택" done={scopeDone} />
          {awsDone && azureDone
            ? <ScopeStep sessionId={sessionId} awsResult={awsResult} azureResult={azureResult} scope={scope} setScope={handleSetScope} />
            : <p style={{ fontSize: "0.82rem", color: "var(--color-text-light)", margin: 0 }}>AWS와 Azure를 모두 연결한 후 활성화됩니다.</p>
          }
        </div>

        {/* Done */}
        {allDone && (
          <div style={{
            padding: "16px 24px", borderRadius: "var(--radius)",
            background: "rgba(22,163,74,0.08)", border: "1px solid #16a34a",
            display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16,
          }}>
            <div>
              <div style={{ fontWeight: 700, color: "#15803d", marginBottom: 4 }}>✓ 준비 완료 — Discover & Select 탭으로 이동하세요</div>
              <div style={{ fontSize: "0.8rem", color: "#15803d", opacity: 0.85 }}>
                AWS {scope.aws_account_id} {scope.aws_region} → Azure {scope.azure_subscription_name} {scope.azure_region}
              </div>
            </div>
            <button type="button" onClick={reset}
              style={{ fontSize: "0.78rem", background: "none", border: "1px solid #16a34a", color: "#15803d", borderRadius: "var(--radius-sm)", padding: "4px 12px", cursor: "pointer" }}>
              초기화
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
