import { useMemo, useState } from "react";

import { terraformZipUrl } from "../api/apiClient";

/**
 * File-browser-style viewer for the generated Terraform module — mirrors the
 * Deploy page's FileBrowserEditor layout (left list, right content) so the
 * Plan and Deploy stages feel consistent.
 *
 * Props
 *   files   – [{ filename, content, description }]
 *   runId   – used to build the "download zip" URL. Optional.
 *   compact – if true, drop the CLI guide accordion (Deploy renders its own).
 */
function TerraformViewer({ files, runId, compact = false, validationPassed = null, moduleNames = null }) {
  const sortedFiles = useMemo(() => {
    return [...(files || [])].sort((a, b) => (a.filename > b.filename ? 1 : -1));
  }, [files]);

  const [active, setActive] = useState(sortedFiles[0]?.filename || "");
  const [copied, setCopied] = useState("");

  const activeFile = useMemo(
    () => sortedFiles.find((f) => f.filename === active) || sortedFiles[0],
    [sortedFiles, active],
  );

  if (!sortedFiles.length) return null;

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
    <div className="result-section">
      <div style={{
        display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
        marginBottom: 8,
      }}>
        <strong style={{ fontSize: "0.85rem" }}>
          🧱 Azure Terraform module
        </strong>
        <span style={{ fontSize: "0.78rem", color: "var(--color-text-light)" }}>
          {sortedFiles.length} 개 파일
        </span>
        <div style={{ flex: 1 }} />
        {runId && (
          <a
            href={terraformZipUrl(runId)}
            className="tab action-btn action-btn--secondary"
            style={{ padding: "4px 12px", fontSize: "0.78rem", textDecoration: "none" }}
          >
            ⬇ 전체 zip
          </a>
        )}
      </div>

      {/* validation 상태 — 헤더 바로 아래 */}
      {validationPassed != null && (
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "8px 12px", marginBottom: 8,
          background: validationPassed ? "rgba(22,163,74,0.08)" : "rgba(217,119,6,0.08)",
          border: `1px solid ${validationPassed ? "#16a34a" : "#d97706"}`,
          borderRadius: "var(--radius-sm)", fontSize: "0.82rem",
        }}>
          <span style={{ fontSize: "1rem" }}>{validationPassed ? "✓" : "⚠"}</span>
          <span style={{ fontWeight: 600 }}>
            {validationPassed
              ? "terraform validate 통과 — 바로 적용 가능"
              : "terraform validate 미통과 — 적용 전 확인 필요"
            }
          </span>
          {moduleNames?.length > 0 && (
            <span style={{ marginLeft: "auto", color: "var(--color-text-light)", fontSize: "0.78rem" }}>
              모듈: root + {moduleNames.join(", ")}
            </span>
          )}
        </div>
      )}

      <div style={{
        display: "grid", gridTemplateColumns: "260px 1fr",
        border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)",
        overflow: "hidden", height: 480,
      }}>
        {/* 왼쪽: 파일 리스트 */}
        <div style={{
          background: "var(--color-bg)", borderRight: "1px solid var(--color-border)",
          overflowY: "auto",
        }}>
          {sortedFiles.map((f) => {
            const isSel = f.filename === activeFile?.filename;
            return (
              <div
                key={f.filename}
                onClick={() => setActive(f.filename)}
                title={f.description || f.filename}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "6px 10px", cursor: "pointer",
                  fontFamily: "monospace", fontSize: "0.74rem",
                  background: isSel ? "var(--color-primary, #2563eb)" : "transparent",
                  color: isSel ? "#fff" : "var(--color-text)",
                  borderBottom: "1px solid var(--color-border)",
                }}
              >
                <span style={{
                  flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {f.filename}
                </span>
              </div>
            );
          })}
        </div>

        {/* 오른쪽: 본문 viewer */}
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "5px 10px", borderBottom: "1px solid var(--color-border)",
            fontFamily: "monospace", fontSize: "0.74rem",
            background: "var(--color-bg)", color: "var(--color-text-light)",
          }}>
            <span style={{ flex: 1 }}>{activeFile?.filename || "(파일 없음)"}</span>
            {activeFile && (
              <>
                <button
                  type="button"
                  onClick={() => copy(activeFile.content, activeFile.filename)}
                  className="tab"
                  style={{ padding: "2px 10px", fontSize: "0.7rem" }}
                  title="클립보드 복사"
                >
                  {copied === activeFile.filename ? "✓ 복사됨" : "📋 복사"}
                </button>
                <button
                  type="button"
                  onClick={() => downloadOne(activeFile)}
                  className="tab"
                  style={{ padding: "2px 10px", fontSize: "0.7rem" }}
                  title="이 파일만 다운로드"
                >
                  ⬇
                </button>
              </>
            )}
          </div>
          {activeFile?.description && (
            <div style={{
              padding: "4px 10px", fontSize: "0.74rem", fontStyle: "italic",
              color: "var(--color-text-light)",
              borderBottom: "1px solid var(--color-border)",
              background: "var(--color-bg)",
            }}>
              {activeFile.description}
            </div>
          )}
          <pre style={{
            flex: 1, margin: 0, padding: "10px 12px",
            background: "#0d1117", color: "#00d4aa",
            fontFamily: "monospace", fontSize: "0.76rem", lineHeight: 1.55,
            overflow: "auto", whiteSpace: "pre",
          }}>
            <code>{activeFile?.content || ""}</code>
          </pre>
        </div>
      </div>

      {!compact && (
        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: "pointer", fontSize: "0.78rem", color: "var(--color-text-light)" }}>
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
          >{`# 1. zip 받아서 풀기
unzip azure-terraform-*.zip -d azure-tf && cd azure-tf

# 2. 로그인 + subscription 지정
az login
az account set --subscription "<your subscription id>"

# 3. init / plan / apply
terraform init
terraform plan -out tfplan
terraform apply tfplan`}</pre>
        </details>
      )}
    </div>
  );
}

export default TerraformViewer;
