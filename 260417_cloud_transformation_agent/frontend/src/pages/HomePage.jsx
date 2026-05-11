import { useState } from "react";
import {
  assumeAwsRole,
  connectAws,
  connectAzure,
  setMigrationScope,
  verifyAzureSubscription,
} from "../api/apiClient";

/* ── Constants ─────────────────────────────────────────────────── */

const AWS_REGIONS = [
  "ap-northeast-2", "ap-northeast-1", "ap-southeast-1", "ap-southeast-2",
  "us-east-1", "us-east-2", "us-west-1", "us-west-2",
  "eu-west-1", "eu-west-2", "eu-central-1",
  "sa-east-1", "ca-central-1", "ap-south-1",
];

const AZURE_REGIONS = [
  { id: "koreacentral",       label: "Korea Central" },
  { id: "koreasouth",         label: "Korea South" },
  { id: "japaneast",          label: "Japan East" },
  { id: "southeastasia",      label: "Southeast Asia" },
  { id: "eastus",             label: "East US" },
  { id: "eastus2",            label: "East US 2" },
  { id: "westus2",            label: "West US 2" },
  { id: "westeurope",         label: "West Europe" },
  { id: "northeurope",        label: "North Europe" },
  { id: "germanywestcentral", label: "Germany West Central" },
  { id: "australiaeast",      label: "Australia East" },
  { id: "uksouth",            label: "UK South" },
  { id: "canadacentral",      label: "Canada Central" },
];

/* ── Shared mini-components ────────────────────────────────────── */

function Field({ label, hint, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 14 }}>
      <label style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--color-text-light)" }}>
        {label}
      </label>
      {children}
      {hint && <span style={{ fontSize: "0.72rem", color: "var(--color-text-light)" }}>{hint}</span>}
    </div>
  );
}

const inputStyle = {
  padding: "7px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
  color: "var(--color-text)",
  fontSize: "0.85rem",
  width: "100%",
  boxSizing: "border-box",
};

function Inp({ value, onChange, placeholder, type = "text", disabled }) {
  return (
    <input type={type} value={value} onChange={e => onChange(e.target.value)}
      placeholder={placeholder} disabled={disabled} style={inputStyle} />
  );
}

function Sel({ value, onChange, disabled, children }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} disabled={disabled}
      style={inputStyle}>
      {children}
    </select>
  );
}

function ErrorBox({ msg }) {
  if (!msg) return null;
  return (
    <div className="form-error" style={{ marginTop: 8, fontSize: "0.82rem" }}>{msg}</div>
  );
}

function SuccessCard({ children }) {
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10,
      padding: "12px 16px", borderRadius: "var(--radius-sm)",
      background: "rgba(22,163,74,0.07)", border: "1px solid #16a34a",
      fontSize: "0.85rem", color: "#15803d",
    }}>
      <span style={{ fontSize: "1.1rem", lineHeight: 1.4 }}>✓</span>
      <div>{children}</div>
    </div>
  );
}

/* ── Vertical toggle sections ───────────────────────────────────── */

function StepToggleSection({
  number,
  label,
  desc,
  isDone,
  isOpen,
  disabled,
  summary,
  onToggle,
  children,
}) {
  return (
    <div style={{
      border: "1px solid var(--color-border)",
      borderRadius: "var(--radius-sm)",
      background: "var(--color-surface)",
      opacity: disabled ? 0.5 : 1,
    }}>
      <button
        type="button"
        onClick={onToggle}
        disabled={disabled}
        aria-expanded={isOpen}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          border: "none",
          background: "transparent",
          color: "var(--color-text)",
          textAlign: "left",
          padding: "12px 14px",
          cursor: disabled ? "not-allowed" : "pointer",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <span style={{
            width: 22,
            height: 22,
            borderRadius: "50%",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "0.72rem",
            fontWeight: 700,
            background: isDone ? "#16a34a" : "var(--color-accent)",
            color: "#0d1117",
            flexShrink: 0,
          }}>
            {isDone ? "✓" : number}
          </span>
          <span style={{ minWidth: 0 }}>
            <div style={{ fontSize: "0.9rem", fontWeight: 700 }}>{label}</div>
            <div style={{
              fontSize: "0.76rem",
              color: "var(--color-text-light)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}>
              {summary || desc}
            </div>
          </span>
        </span>
        <span style={{ fontSize: "0.8rem", color: "var(--color-text-light)", flexShrink: 0 }}>
          {isOpen ? "▲" : "▼"}
        </span>
      </button>

      {isOpen && !disabled && (
        <div style={{ padding: "0 14px 14px", borderTop: "1px solid rgba(255,255,255,0.05)" }}>
          <div style={{ marginTop: 12 }}>{children}</div>
        </div>
      )}
    </div>
  );
}

/* ── Step 1: AWS ─────────────────────────────────────────────────── */

function AwsForm({ sessionId, setSessionId, onDone }) {
  const [method, setMethod]     = useState("profile");
  const [profile, setProfile]   = useState("default");
  const [keyId, setKeyId]       = useState("");
  const [secret, setSecret]     = useState("");
  const [token, setToken]       = useState("");
  const [region, setRegion]     = useState("ap-northeast-2");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  const connect = async () => {
    setLoading(true); setError(null);
    try {
      const params = { method, region, session_id: sessionId || undefined };
      if (method === "profile")     params.profile = profile;
      if (method === "static_keys") {
        params.access_key_id     = keyId;
        params.secret_access_key = secret;
        if (token) params.session_token = token;
      }
      const res = await connectAws(params);
      if (!sessionId) setSessionId(res.session_id);
      onDone(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 480 }}>
      <Field label="인증 방식">
        <Sel value={method} onChange={setMethod} disabled={loading}>
          <option value="profile">AWS Profile (~/.aws/credentials)</option>
          <option value="static_keys">Access Key + Secret</option>
          <option value="default">기본 체인 (Instance Role 등)</option>
        </Sel>
      </Field>

      {method === "profile" && (
        <Field label="Profile 이름" hint="~/.aws/credentials 에 정의된 이름">
          <Inp value={profile} onChange={setProfile} placeholder="default" disabled={loading} />
        </Field>
      )}
      {method === "static_keys" && (
        <>
          <Field label="Access Key ID">
            <Inp value={keyId} onChange={setKeyId} placeholder="AKIAXXXXXXXXXXXXXXXX" disabled={loading} />
          </Field>
          <Field label="Secret Access Key">
            <Inp value={secret} onChange={setSecret} type="password" placeholder="••••••••" disabled={loading} />
          </Field>
          <Field label="Session Token" hint="STS 임시 자격증명일 때만 입력 (선택)">
            <Inp value={token} onChange={setToken} type="password" placeholder="선택 사항" disabled={loading} />
          </Field>
        </>
      )}
      {method === "default" && (
        <div style={{ padding: "10px 12px", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", fontSize: "0.82rem", color: "var(--color-text-light)", marginBottom: 14 }}>
          EC2 Instance Role, 환경변수, <code>~/.aws/config</code> 순서로 자동 탐색합니다.
        </div>
      )}

      <Field label="기본 Region">
        <Sel value={region} onChange={setRegion} disabled={loading}>
          {AWS_REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
        </Sel>
      </Field>

      <ErrorBox msg={error} />
      <button type="button" className="run-btn action-btn" onClick={connect} disabled={loading}
        style={{ marginTop: 4, minHeight: 38, padding: "0 24px" }}>
        {loading ? <><span className="spinner" />연결 중…</> : "AWS 연결 →"}
      </button>
    </div>
  );
}

/* ── Step 2: Azure ───────────────────────────────────────────────── */

function AzureForm({ sessionId, onDone }) {
  const [method, setMethod]         = useState("cli");
  const [tenantId, setTenantId]     = useState("");
  const [clientId, setClientId]     = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState(null);

  const connect = async () => {
    setLoading(true); setError(null);
    try {
      const params = { method, session_id: sessionId };
      if (method === "service_principal") {
        params.tenant_id     = tenantId;
        params.client_id     = clientId;
        params.client_secret = clientSecret;
      }
      const res = await connectAzure(params);
      onDone(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 480 }}>
      <Field label="인증 방식">
        <Sel value={method} onChange={setMethod} disabled={loading}>
          <option value="cli">Azure CLI (az login)</option>
          <option value="service_principal">Service Principal</option>
        </Sel>
      </Field>

      {method === "cli" && (
        <div style={{ padding: "10px 12px", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", fontSize: "0.82rem", color: "var(--color-text-light)", marginBottom: 14 }}>
          터미널에서 <code style={{ background: "rgba(0,0,0,0.07)", padding: "1px 5px", borderRadius: 3 }}>az login</code>을 먼저 실행하세요.
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
          <div style={{ fontSize: "0.75rem", color: "var(--color-text-light)", marginBottom: 14 }}>
            필요 권한: 대상 Subscription의 <strong>Contributor</strong> (배포) 또는 <strong>Reader</strong> (분석 전용)
          </div>
        </>
      )}

      <ErrorBox msg={error} />
      <button type="button" className="run-btn action-btn" onClick={connect} disabled={loading}
        style={{ marginTop: 4, minHeight: 38, padding: "0 24px" }}>
        {loading ? <><span className="spinner" />연결 중…</> : "Azure 연결 →"}
      </button>
    </div>
  );
}

/* ── Step 3: Scope ───────────────────────────────────────────────── */

function ScopeForm({ sessionId, awsResult, azureResult, onDone }) {
  const accounts      = awsResult?.org_accounts || [];
  const subscriptions = azureResult?.subscriptions || [];

  const [awsAccount, setAwsAccount]   = useState(accounts[0]?.account_id || "");
  const [awsRegion, setAwsRegion]     = useState(awsResult?.region || "ap-northeast-2");
  const [azureSub, setAzureSub]       = useState(subscriptions[0]?.subscription_id || "");
  const [azureRegion, setAzureRegion] = useState("koreacentral");
  const [roleName, setRoleName]       = useState("MigrationReadRole");
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState(null);

  const callerAccountId = awsResult?.identity?.account_id;
  const isCrossAccount  = awsAccount && awsAccount !== callerAccountId;
  const selectedSub     = subscriptions.find(s => s.subscription_id === azureSub);

  const confirm = async () => {
    setLoading(true); setError(null);

    if (isCrossAccount) {
      try {
        await assumeAwsRole({ session_id: sessionId, account_id: awsAccount, role_name: roleName });
      } catch (e) {
        setError(`Cross-account Role assume 실패: ${e.message}`);
        setLoading(false);
        return;
      }
    }

    try {
      const check = await verifyAzureSubscription(sessionId, azureSub);
      if (!check.accessible) {
        setError(`Azure Subscription 접근 불가: ${check.reason}`);
        setLoading(false);
        return;
      }
    } catch (e) {
      setError(`Azure 접근 확인 실패: ${e.message}`);
      setLoading(false);
      return;
    }

    try {
      const res = await setMigrationScope({
        session_id: sessionId,
        aws_account_id: awsAccount,
        aws_region: awsRegion,
        azure_subscription_id: azureSub,
        azure_subscription_name: selectedSub?.display_name || azureSub,
        azure_region: azureRegion,
      });
      onDone(res.scope);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 32, maxWidth: 700 }}>
      {/* AWS side */}
      <div>
        <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-light)", marginBottom: 12 }}>
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
        {isCrossAccount && (
          <Field label="Cross-account Role 이름" hint="대상 계정에 사전 생성된 IAM Role">
            <Inp value={roleName} onChange={setRoleName} placeholder="MigrationReadRole" disabled={loading} />
          </Field>
        )}
        <Field label="Region">
          <Sel value={awsRegion} onChange={setAwsRegion} disabled={loading}>
            {AWS_REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
          </Sel>
        </Field>
      </div>

      {/* Azure side */}
      <div>
        <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-light)", marginBottom: 12 }}>
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
          <div style={{ fontSize: "0.72rem", color: "var(--color-text-light)", fontFamily: "monospace", marginBottom: 14, marginTop: -8 }}>
            {selectedSub.subscription_id}
          </div>
        )}
        <Field label="Region">
          <Sel value={azureRegion} onChange={setAzureRegion} disabled={loading}>
            {AZURE_REGIONS.map(r => (
              <option key={r.id} value={r.id}>{r.label} ({r.id})</option>
            ))}
          </Sel>
        </Field>
      </div>

      {/* Confirm button spans full width */}
      <div style={{ gridColumn: "1 / -1" }}>
        <ErrorBox msg={error} />
        <button type="button" className="run-btn action-btn" onClick={confirm}
          disabled={loading || !awsAccount || !azureSub}
          style={{ marginTop: 4, minHeight: 38, padding: "0 24px" }}>
          {loading ? <><span className="spinner" />확인 중…</> : "범위 확정 →"}
        </button>
      </div>
    </div>
  );
}

/* ── Ready state ─────────────────────────────────────────────────── */

function ReadyPanel({ awsResult, azureResult, scope, onStart, onReset }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SuccessCard>
        <strong>세션 준비 완료</strong>
        <div style={{ fontSize: "0.8rem", marginTop: 4, opacity: 0.9 }}>
          AWS {scope.aws_account_id} ({scope.aws_region})
          {" → "}
          Azure {scope.azure_subscription_name} ({scope.azure_region})
        </div>
      </SuccessCard>

      {/* Summary grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div style={{ padding: "12px 16px", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)" }}>
          <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-light)", marginBottom: 6 }}>AWS</div>
          <div style={{ fontSize: "0.82rem", fontWeight: 600 }}>{awsResult?.identity?.arn?.split("/").pop()}</div>
          <div style={{ fontSize: "0.75rem", color: "var(--color-text-light)", marginTop: 2 }}>{scope.aws_account_id} · {scope.aws_region}</div>
          {awsResult?.org_accounts?.length > 1 && (
            <div style={{ fontSize: "0.72rem", color: "var(--color-text-light)", marginTop: 4 }}>
              Org 계정 {awsResult.org_accounts.length}개 접근 가능
            </div>
          )}
        </div>
        <div style={{ padding: "12px 16px", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)" }}>
          <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-light)", marginBottom: 6 }}>Azure</div>
          <div style={{ fontSize: "0.82rem", fontWeight: 600 }}>{scope.azure_subscription_name}</div>
          <div style={{ fontSize: "0.75rem", color: "var(--color-text-light)", marginTop: 2 }}>{scope.azure_region}</div>
          {azureResult?.subscriptions?.length > 1 && (
            <div style={{ fontSize: "0.72rem", color: "var(--color-text-light)", marginTop: 4 }}>
              Subscription {azureResult.subscriptions.length}개 접근 가능
            </div>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
        <button type="button" className="run-btn action-btn" onClick={onStart}
          style={{ minHeight: 40, padding: "0 28px", fontSize: "0.95rem" }}>
          Discover 시작 →
        </button>
        <button type="button" className="tab action-btn action-btn--secondary" onClick={onReset}
          style={{ minHeight: 40, padding: "0 16px", fontSize: "0.85rem" }}>
          초기화
        </button>
      </div>
    </div>
  );
}

/* ── Main component ──────────────────────────────────────────────── */

export default function HomePage({ sessionId, setSessionId, onReady, onStart }) {
  const [awsResult, setAwsResult]     = useState(null);
  const [azureResult, setAzureResult] = useState(null);
  const [scope, setScope]             = useState(null);
  const [openStep, setOpenStep]       = useState("aws");

  const allDone = !!scope;

  const handleAwsDone = (res) => {
    setAwsResult(res);
    setOpenStep("azure");
  };

  const handleAzureDone = (res) => {
    setAzureResult(res);
    setOpenStep("scope");
  };

  const handleScopeDone = (s) => {
    setScope(s);
    setOpenStep(null);
    onReady?.({ sessionId, scope: s });
  };

  const handleReset = () => {
    setAwsResult(null);
    setAzureResult(null);
    setScope(null);
    setOpenStep("aws");
    setSessionId(null);
  };

  return (
    <section className="page-section">
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: "0 0 6px", fontSize: "1.15rem", fontWeight: 700 }}>
          AWS · Azure 계정 연결
        </h2>
        <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--color-text-light)" }}>
          출발지(AWS)와 목적지(Azure)를 연결하고 마이그레이션 범위를 확정합니다.
          자격증명은 서버 메모리에만 유지되며 디스크나 외부로 전송되지 않습니다.
        </p>
      </div>

      {/* Vertical toggle panels */}
      {!allDone && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <StepToggleSection
            number={1}
            label="AWS"
            desc="boto3 자격증명 체인으로 AWS 계정에 연결합니다."
            isDone={!!awsResult}
            isOpen={openStep === "aws"}
            disabled={false}
            summary={awsResult ? `완료 · ${awsResult.identity.account_id} · ${awsResult.region}` : null}
            onToggle={() => setOpenStep((prev) => (prev === "aws" ? null : "aws"))}
          >
            <AwsForm
              sessionId={sessionId}
              setSessionId={setSessionId}
              onDone={handleAwsDone}
            />
          </StepToggleSection>

          <StepToggleSection
            number={2}
            label="Azure"
            desc="az login 또는 Service Principal로 Azure에 연결합니다."
            isDone={!!azureResult}
            isOpen={openStep === "azure"}
            disabled={!awsResult}
            summary={azureResult ? `완료 · Subscription ${azureResult.subscriptions.length}개` : null}
            onToggle={() => setOpenStep((prev) => (prev === "azure" ? null : "azure"))}
          >
            <AzureForm
              sessionId={sessionId}
              onDone={handleAzureDone}
            />
          </StepToggleSection>

          <StepToggleSection
            number={3}
            label="Scope"
            desc="AWS 계정/리전과 Azure 구독/리전을 확정합니다."
            isDone={!!scope}
            isOpen={openStep === "scope"}
            disabled={!awsResult || !azureResult}
            summary={scope ? `완료 · ${scope.aws_account_id} → ${scope.azure_subscription_name}` : null}
            onToggle={() => setOpenStep((prev) => (prev === "scope" ? null : "scope"))}
          >
            <ScopeForm
              sessionId={sessionId}
              awsResult={awsResult}
              azureResult={azureResult}
              onDone={handleScopeDone}
            />
          </StepToggleSection>
        </div>
      )}

      {/* Ready state */}
      {allDone && (
        <ReadyPanel
          awsResult={awsResult}
          azureResult={azureResult}
          scope={scope}
          onStart={onStart}
          onReset={handleReset}
        />
      )}
    </section>
  );
}
