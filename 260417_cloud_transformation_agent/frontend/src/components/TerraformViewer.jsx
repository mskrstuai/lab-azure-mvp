import { useMemo, useState } from "react";

import { terraformZipUrl } from "../api/apiClient";

/**
 * Tabbed viewer for a MigrationPlan.terraform[] list.
 *
 * Props
 *   files  – [{ filename, content, description }]
 *   runId  – used to build the "download zip" URL. If absent, only per-file
 *            download (Blob) is offered.
 *   compact – pass true to drop the "How to deploy" accordion (the Deploy
 *            page renders its own, richer guide).
 */
function TerraformViewer({ files, runId, compact = false }) {
  const [active, setActive] = useState(files[0]?.filename || "");
  const [copied, setCopied] = useState("");

  const activeFile = useMemo(
    () => files.find((f) => f.filename === active) || files[0],
    [files, active],
  );

  if (!files || files.length === 0) return null;

  const copy = async (text, name) => {
    try {
      await navigator.clipboard.writeText(text || "");
      setCopied(name);
      setTimeout(() => setCopied(""), 1500);
    } catch {
      /* no-op */
    }
  };

  const downloadOne = (f) => {
    const blob = new Blob([f.content || ""], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = f.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
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
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 10,
        }}
      >
        <h3 className="result-section-title" style={{ margin: 0 }}>
          🧱 Azure Terraform module ({files.length} file{files.length === 1 ? "" : "s"})
        </h3>
        {runId && (
          <a
            className="run-btn"
            href={terraformZipUrl(runId)}
            style={{ padding: "8px 14px", fontSize: "0.85rem", textDecoration: "none" }}
          >
            ⬇ Download all as .zip
          </a>
        )}
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 6,
          marginBottom: 10,
          borderBottom: "1px solid var(--color-border)",
          paddingBottom: 8,
        }}
      >
        {files.map((f) => (
          <button
            key={f.filename}
            type="button"
            onClick={() => setActive(f.filename)}
            className={`tab ${active === f.filename ? "active" : ""}`}
            style={{
              padding: "4px 10px",
              fontFamily: "monospace",
              fontSize: "0.78rem",
              borderRadius: "var(--radius-sm, 4px)",
              border: "1px solid var(--color-border)",
              background:
                active === f.filename ? "var(--color-accent)" : "var(--color-bg)",
              color: active === f.filename ? "white" : "var(--color-text)",
              cursor: "pointer",
            }}
            title={f.description || f.filename}
          >
            {f.filename}
          </button>
        ))}
      </div>

      {activeFile && (
        <div>
          {activeFile.description && (
            <div
              style={{
                fontSize: "0.8rem",
                color: "var(--color-text-light)",
                marginBottom: 6,
                fontStyle: "italic",
              }}
            >
              {activeFile.description}
            </div>
          )}
          <div style={{ position: "relative" }}>
            <pre
              style={{
                background: "var(--color-bg)",
                border: "1px solid var(--color-border)",
                borderRadius: "var(--radius-sm, 4px)",
                padding: 14,
                overflowX: "auto",
                fontSize: "0.78rem",
                lineHeight: 1.55,
                maxHeight: 460,
                margin: 0,
              }}
            >
              <code>{activeFile.content}</code>
            </pre>
            <div
              style={{
                position: "absolute",
                top: 8,
                right: 8,
                display: "flex",
                gap: 6,
              }}
            >
              <button
                type="button"
                className="tab"
                onClick={() => copy(activeFile.content, activeFile.filename)}
                style={{ padding: "4px 10px", fontSize: "0.72rem" }}
              >
                {copied === activeFile.filename ? "✓ Copied" : "📋 Copy"}
              </button>
              <button
                type="button"
                className="tab"
                onClick={() => downloadOne(activeFile)}
                style={{ padding: "4px 10px", fontSize: "0.72rem" }}
              >
                ⬇ {activeFile.filename}
              </button>
            </div>
          </div>
        </div>
      )}

      {!compact && (
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: "pointer", fontSize: "0.85rem" }}>
            ▸ 배포 방법 (CLI)
          </summary>
          <pre
            style={{
              background: "var(--color-bg)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-sm, 4px)",
              padding: 12,
              fontSize: "0.78rem",
              marginTop: 8,
            }}
          >{`# 1. Download + unzip the module
unzip azure-terraform-*.zip -d azure-tf && cd azure-tf

# 2. Sign in and pick a subscription
az login
az account set --subscription "<your subscription id>"

# 3. Initialize providers, review the plan, and apply
terraform init
terraform plan -out tfplan
terraform apply tfplan`}</pre>
        </details>
      )}
    </div>
  );
}

export default TerraformViewer;
