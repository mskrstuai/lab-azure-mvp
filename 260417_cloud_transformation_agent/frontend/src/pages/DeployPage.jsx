import { useEffect, useMemo, useState } from "react";

import {
  fetchMigrationOutput,
  fetchMigrationOutputs,
  terraformZipUrl,
} from "../api/apiClient";
import TerraformViewer from "../components/TerraformViewer";

/**
 * Deploy & Migrate page.
 *
 * Wraps previously-generated Terraform modules with a focused deployment
 * workflow: pick a run → download the zip → copy the CLI sequence → apply.
 * No planner invocation happens here; this is strictly post-planning.
 */
function DeployPage({ onGoToPlan }) {
  const [runs, setRuns] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [output, setOutput] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingOutput, setLoadingOutput] = useState(false);
  const [copied, setCopied] = useState("");

  useEffect(() => {
    fetchMigrationOutputs()
      .then((res) => {
        const list = (res.runs || []).filter((r) => r.has_terraform);
        setRuns(list);
        if (list.length > 0) setSelectedId(list[0].run_id);
      })
      .catch(() => setRuns([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setOutput(null);
      return;
    }
    setLoadingOutput(true);
    fetchMigrationOutput(selectedId)
      .then(setOutput)
      .catch(() => setOutput(null))
      .finally(() => setLoadingOutput(false));
  }, [selectedId]);

  const tfFiles = useMemo(() => {
    const jd = output?.json_data;
    return Array.isArray(jd?.terraform) ? jd.terraform : [];
  }, [output]);

  const copy = async (text, key) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(""), 1500);
    } catch {
      /* no-op */
    }
  };

  if (loading) {
    return (
      <section className="page-section">
        <h2 className="page-title">🚀 Deploy & Migrate</h2>
        <div className="loading">
          <div className="spinner" />
          <p>Loading previous plans...</p>
        </div>
      </section>
    );
  }

  if (runs.length === 0) {
    return (
      <section className="page-section">
        <h2 className="page-title">🚀 Deploy & Migrate</h2>
        <p className="page-desc">
          Download and apply the Azure Terraform module produced by the planner.
        </p>
        <div className="empty-state">
          <div className="icon">📦</div>
          <p>No Terraform modules yet.</p>
          <p className="hint">
            Run <strong>Plan</strong> first to generate an Azure Terraform module,
            then come back here to deploy it.
          </p>
          {onGoToPlan && (
            <button
              type="button"
              className="run-btn"
              style={{ marginTop: 16 }}
              onClick={onGoToPlan}
            >
              🧭 Go to Plan
            </button>
          )}
        </div>
      </section>
    );
  }

  const zipUrl = selectedId ? terraformZipUrl(selectedId) : "";
  const applyScript = `# 1) Download and unpack the module
curl -L "${zipUrl}" -o azure-tf.zip
unzip azure-tf.zip -d azure-tf && cd azure-tf

# 2) Sign in to Azure (skip if already signed in)
az login
az account set --subscription "<your-subscription-id>"

# 3) Initialise + preview + apply
terraform init
terraform plan -out tfplan
terraform apply tfplan`;

  return (
    <section className="page-section">
      <h2 className="page-title">🚀 Deploy & Migrate</h2>
      <p className="page-desc">
        Select one of the Terraform modules produced by the planner, grab the
        files, and run <code>terraform apply</code> against your Azure
        subscription. All prior runs are kept under{" "}
        <code>backend/outputs/</code>.
      </p>

      <div className="outputs-panel">
        <div className="outputs-sidebar">
          <h3 className="sidebar-title">
            Terraform-ready runs ({runs.length})
          </h3>
          <div className="run-list">
            {runs.map((r) => (
              <button
                key={r.run_id}
                type="button"
                className={`run-card ${selectedId === r.run_id ? "active" : ""}`}
                onClick={() => setSelectedId(r.run_id)}
              >
                <span className="run-id">{r.run_id}</span>
                <span className="run-badges">
                  <span
                    className="badge"
                    style={{ background: "var(--color-accent)", color: "#0d1117" }}
                  >
                    {r.terraform_file_count || 0} TF
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="outputs-content">
          {loadingOutput && (
            <div className="loading">
              <div className="spinner" />
              <p>Loading module...</p>
            </div>
          )}

          {!loadingOutput && selectedId && (
            <>
              {/* Deploy CLI guide — prominent, top of page */}
              <div
                className="result-section"
                style={{
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-md, 8px)",
                  padding: 14,
                  background: "var(--color-surface)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    flexWrap: "wrap",
                    gap: 12,
                    marginBottom: 10,
                  }}
                >
                  <h3 className="result-section-title" style={{ margin: 0 }}>
                    ⚙️ Apply to Azure
                  </h3>
                  <div style={{ display: "flex", gap: 8 }}>
                    <a
                      className="run-btn"
                      href={zipUrl}
                      style={{
                        padding: "8px 14px",
                        fontSize: "0.85rem",
                        textDecoration: "none",
                      }}
                    >
                      ⬇ Download .zip
                    </a>
                    <button
                      type="button"
                      className="tab"
                      onClick={() => copy(applyScript, "script")}
                      style={{ padding: "8px 14px", fontSize: "0.85rem" }}
                    >
                      {copied === "script" ? "✓ Copied" : "📋 Copy commands"}
                    </button>
                  </div>
                </div>
                <pre
                  style={{
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "var(--radius-sm, 4px)",
                    padding: 14,
                    fontSize: "0.8rem",
                    lineHeight: 1.55,
                    overflowX: "auto",
                    margin: 0,
                  }}
                >
                  <code>{applyScript}</code>
                </pre>
                <div
                  style={{
                    marginTop: 10,
                    fontSize: "0.78rem",
                    color: "var(--color-text-light)",
                  }}
                >
                  Tip: review <code>terraform plan</code> output carefully before
                  applying. Destroy a sandbox with{" "}
                  <code>terraform destroy</code> when you're done.
                </div>
              </div>

              {/* Terraform file viewer (compact — no built-in apply guide) */}
              {tfFiles.length > 0 ? (
                <TerraformViewer files={tfFiles} runId={selectedId} compact />
              ) : (
                <div className="empty-state" style={{ padding: 28 }}>
                  <div className="icon">🗂</div>
                  <p>No Terraform files found for this run.</p>
                  <p className="hint">
                    Older runs may have been produced before Terraform
                    generation was enabled.
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

export default DeployPage;
