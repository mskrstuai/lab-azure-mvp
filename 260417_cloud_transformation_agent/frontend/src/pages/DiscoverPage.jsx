import { useState, useMemo, useCallback, useEffect } from "react";
import { scanArchitecture, listArchResourceGroups, listArchTagKeys } from "../api/apiClient";

/* ── Type display (fallback-friendly) ───────────────────────────── */
const TYPE_META = {
  ec2:         { icon: "🖥",  label: "EC2 Instance" },
  rds:         { icon: "🗄",  label: "RDS" },
  elb:         { icon: "⚖",  label: "Load Balancer" },
  lambda:      { icon: "λ",   label: "Lambda" },
  s3:          { icon: "🪣",  label: "S3 Bucket" },
  ecs:         { icon: "🧩",  label: "ECS Cluster" },
  dynamodb:    { icon: "📇",  label: "DynamoDB" },
  elasticache: { icon: "⚡",  label: "ElastiCache" },
  eks:         { icon: "☸",   label: "EKS" },
};

function typeMeta(type) {
  return TYPE_META[type] || { icon: "📦", label: (type || "resource").toUpperCase() };
}

/* ── Fields to omit from the generic detail view ────────────────── */
const INTERNAL = new Set([
  "_type", "arn", "id", "name", "vpc_id", "subnet_id", "subnet_ids",
  "security_group_ids", "tags", "resources", "direct_resources",
  "listeners", "services", "ebs_volumes",
]);

function fmtVal(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return v.toLocaleString();
  const s = String(v);
  return s.length > 60 ? s.slice(0, 58) + "…" : s;
}

/** Filter the full architecture down to only the selected resources.
 *  Keeps VPC/Subnet/SG topology intact (selected resources reference them),
 *  but trims ec2/rds/s3/lambda/elb arrays to just the chosen ARNs. */
function filterArchitecture(arch, chosen) {
  if (!arch) return null;
  const chosenArns = new Set((chosen || []).map(r => r.arn).filter(Boolean));
  const keep = (item) => !chosenArns.size || chosenArns.has(item?.arn);

  // Filter top-level resource arrays
  const filtered = {
    ...arch,
    ec2:    (arch.ec2    || []).filter(keep),
    rds:    (arch.rds    || []).filter(keep),
    elb:    (arch.elb    || []).filter(keep),
    lambda: (arch.lambda || []).filter(keep),
    s3:     (arch.s3     || []).filter(keep),
    ecs:    (arch.ecs    || []).filter(keep),
  };

  // Filter networking subnets' embedded resources too
  filtered.networking = (arch.networking || []).map(vpc => ({
    ...vpc,
    subnets: (vpc.subnets || []).map(s => ({
      ...s,
      resources: (s.resources || []).filter(keep),
    })),
    direct_resources: (vpc.direct_resources || []).filter(keep),
  }));

  return filtered;
}

/* Pick the most informative scalar fields for badge display. */
function keyFields(resource) {
  return Object.entries(resource)
    .filter(([k, v]) => !INTERNAL.has(k) && v != null && v !== "" && typeof v !== "object")
    .slice(0, 5);
}

function Badge({ children, color }) {
  return (
    <span style={{
      fontSize: "0.68rem", padding: "1px 7px", borderRadius: 99, whiteSpace: "nowrap",
      border: `1px solid ${color || "var(--color-border)"}`,
      color: color || "var(--color-text-light)",
    }}>
      {children}
    </span>
  );
}

/* ── Generic resource row ────────────────────────────────────────── */
function ResourceRow({ resource, isSelected, onToggle }) {
  const [open, setOpen] = useState(false);
  const { icon, label } = typeMeta(resource._type);
  const name = resource.name || resource.id || "";
  const id   = resource.id   || resource.name || "";
  const key  = resource.arn  || `${resource._type}:${id}`;

  const badges   = useMemo(() => keyFields(resource), [resource]);
  const sgCount  = (resource.security_group_ids || []).length;
  const hasExtra = (resource.listeners?.length > 0) || (resource.services?.length > 0) || (resource.ebs_volumes?.length > 0);

  return (
    <div>
      <div style={{
        display: "flex", alignItems: "center", gap: 8, padding: "7px 10px",
        borderRadius: "var(--radius-sm)",
        background: isSelected ? "rgba(0,212,170,0.07)" : "transparent",
        transition: "background 0.15s",
      }}>
        <input
          type="checkbox"
          checked={!!isSelected}
          onChange={() => onToggle(key, resource)}
          style={{ flexShrink: 0, cursor: "pointer" }}
        />
        <span style={{ flexShrink: 0, fontSize: "1rem" }}>{icon}</span>
        <span style={{ fontSize: "0.68rem", color: "var(--color-text-light)", flexShrink: 0 }}>
          {label}
        </span>
        <span style={{ fontWeight: 600, fontSize: "0.85rem", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {name || <em style={{ fontWeight: 400, color: "var(--color-text-light)" }}>(unnamed)</em>}
        </span>
        {id !== name && (
          <span style={{ fontFamily: "monospace", fontSize: "0.72rem", color: "var(--color-text-light)", flexShrink: 0 }}>
            {id}
          </span>
        )}
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginLeft: "auto", flexShrink: 0, alignItems: "center" }}>
          {badges.map(([k, v]) => <Badge key={k}>{fmtVal(v)}</Badge>)}
          {sgCount > 0 && <Badge color="#8b9eb5">🔒 {sgCount}</Badge>}
          {hasExtra && (
            <button type="button" onClick={() => setOpen(o => !o)}
              style={{ fontSize: "0.7rem", background: "none", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", padding: "1px 7px", cursor: "pointer", color: "var(--color-text-light)" }}>
              {open ? "접기" : "상세"}
            </button>
          )}
        </div>
      </div>

      {/* Generic detail table */}
      {open && (
        <div style={{ paddingLeft: 40, paddingBottom: 10, paddingRight: 10 }}>
          <table style={{ fontSize: "0.75rem", width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {Object.entries(resource)
                .filter(([k]) => !INTERNAL.has(k))
                .map(([k, v]) => (
                  <tr key={k} style={{ borderBottom: "1px solid var(--color-border)" }}>
                    <td style={{ padding: "3px 12px 3px 0", color: "var(--color-text-light)", whiteSpace: "nowrap", verticalAlign: "top" }}>{k}</td>
                    <td style={{ padding: "3px 0", color: "var(--color-text)", wordBreak: "break-all" }}>
                      {typeof v === "object"
                        ? <pre style={{ margin: 0, fontSize: "0.72rem", fontFamily: "monospace", color: "var(--color-text-light)" }}>{JSON.stringify(v, null, 2)}</pre>
                        : fmtVal(v)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {(resource.listeners || []).length > 0 && (
            <div style={{ marginTop: 6 }}>
              {resource.listeners.map((l, li) => (
                <div key={li} style={{ fontSize: "0.75rem", color: "var(--color-text-light)", padding: "2px 0" }}>
                  :{l.port} {l.protocol}
                  {(l.target_groups || []).map((tg, ti) => (
                    <span key={ti}> → <strong style={{ color: "var(--color-text)" }}>{tg.name || tg.arn?.split("/").pop()}</strong> [{tg.targets?.length ?? 0} targets]</span>
                  ))}
                </div>
              ))}
            </div>
          )}
          {(resource.services || []).length > 0 && (
            <div style={{ marginTop: 6 }}>
              {resource.services.map((svc, si) => (
                <div key={si} style={{ fontSize: "0.75rem", color: "var(--color-text-light)", padding: "2px 0" }}>
                  🧩 {svc.name} — desired: {svc.desired}, running: {svc.running}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Subnet section ──────────────────────────────────────────────── */
function SubnetSection({ subnet, selected, onToggle }) {
  const [open, setOpen] = useState(true);
  const resources = subnet.resources || [];
  if (!resources.length) return null;

  return (
    <div style={{ marginBottom: 2 }}>
      <button type="button" onClick={() => setOpen(o => !o)}
        style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", background: "none", border: "none", cursor: "pointer", padding: "4px 8px", borderRadius: "var(--radius-sm)", color: "var(--color-text-light)", fontSize: "0.75rem", textAlign: "left" }}>
        <span>{open ? "▾" : "▸"}</span>
        <span style={{ fontFamily: "monospace", fontSize: "0.72rem" }}>{subnet.id}</span>
        {subnet.name && <strong style={{ color: "var(--color-text)", fontSize: "0.78rem" }}>{subnet.name}</strong>}
        <Badge>{subnet.cidr}</Badge>
        <Badge>{subnet.az}</Badge>
        {subnet.public ? <Badge color="#f59e0b">PUBLIC</Badge> : <Badge>PRIVATE</Badge>}
        <span style={{ marginLeft: "auto" }}>{resources.length}개</span>
      </button>
      {open && (
        <div style={{ paddingLeft: 16, marginLeft: 12, borderLeft: "1px solid var(--color-border)" }}>
          {resources.map((r, i) => (
            <ResourceRow key={i} resource={r}
              isSelected={selected.has(r.arn || `${r._type}:${r.id || r.name}`)}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── VPC card ────────────────────────────────────────────────────── */
function VpcCard({ vpc, selected, onToggle }) {
  const [open, setOpen] = useState(true);
  const subnetCount  = (vpc.subnets || []).reduce((n, s) => n + (s.resources || []).length, 0);
  const directCount  = (vpc.direct_resources || []).length;
  const total        = subnetCount + directCount;

  return (
    <div style={{ border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", marginBottom: 10, overflow: "hidden" }}>
      <button type="button" onClick={() => setOpen(o => !o)}
        style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", background: "#0d1117", border: "none", cursor: "pointer", padding: "10px 14px", color: "var(--color-text)", textAlign: "left" }}>
        <span style={{ fontSize: "1.1rem" }}>🌐</span>
        <span style={{ fontFamily: "monospace", fontSize: "0.78rem", color: "var(--color-text-light)" }}>{vpc.id}</span>
        {vpc.name && <strong style={{ fontSize: "0.88rem" }}>{vpc.name}</strong>}
        <Badge>{vpc.cidr}</Badge>
        {vpc.is_default && <Badge color="#f59e0b">default</Badge>}
        {(vpc.internet_gateways || []).length > 0 && <Badge color="#00d4aa">IGW</Badge>}
        {(vpc.nat_gateways || []).length > 0 && <Badge>NAT</Badge>}
        <span style={{ marginLeft: "auto", fontSize: "0.75rem", color: "var(--color-text-light)" }}>
          {total}개 리소스
        </span>
        <span style={{ color: "var(--color-text-light)", fontSize: "0.8rem" }}>{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div style={{ padding: "10px 12px", background: "var(--color-bg)" }}>
          {/* Subnets with resources */}
          {(vpc.subnets || []).filter(s => (s.resources || []).length > 0).map((s, i) => (
            <SubnetSection key={i} subnet={s} selected={selected} onToggle={onToggle} />
          ))}

          {/* Empty subnet hint */}
          {(() => {
            const empty = (vpc.subnets || []).filter(s => !(s.resources || []).length).length;
            return empty > 0
              ? <div style={{ fontSize: "0.72rem", color: "var(--color-text-light)", padding: "4px 8px" }}>빈 서브넷 {empty}개</div>
              : null;
          })()}

          {/* VPC-level resources (RDS, ELB, etc.) */}
          {(vpc.direct_resources || []).length > 0 && (
            <div style={{ marginTop: 6, paddingLeft: 8, borderLeft: "1px solid var(--color-border)", marginLeft: 4 }}>
              <div style={{ fontSize: "0.7rem", color: "var(--color-text-light)", padding: "2px 4px 4px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                VPC-level
              </div>
              {vpc.direct_resources.map((r, i) => (
                <ResourceRow key={i} resource={r}
                  isSelected={selected.has(r.arn || `${r._type}:${r.id || r.name}`)}
                  onToggle={onToggle}
                />
              ))}
            </div>
          )}

          {/* Security groups */}
          {(vpc.security_groups || []).length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ fontSize: "0.72rem", color: "var(--color-text-light)", cursor: "pointer", padding: "4px 8px" }}>
                🔒 Security Groups ({vpc.security_groups.length})
              </summary>
              <div style={{ paddingLeft: 16, marginTop: 4 }}>
                {vpc.security_groups.map((sg, i) => (
                  <div key={i} style={{ fontSize: "0.74rem", padding: "2px 0", color: "var(--color-text-light)" }}>
                    <strong style={{ color: "var(--color-text)" }}>{sg.name}</strong>
                    {" "}<span style={{ fontFamily: "monospace" }}>{sg.id}</span>
                    {" — "}{(sg.ingress || []).length} inbound rule{(sg.ingress || []).length !== 1 ? "s" : ""}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Global (S3, ECS) ────────────────────────────────────────────── */
function GlobalSection({ title, icon, items, type, selected, onToggle }) {
  const [open, setOpen] = useState(false);
  if (!items?.length) return null;
  return (
    <div style={{ border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", marginBottom: 10, overflow: "hidden" }}>
      <button type="button" onClick={() => setOpen(o => !o)}
        style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", background: "#0d1117", border: "none", cursor: "pointer", padding: "10px 14px", color: "var(--color-text)", textAlign: "left" }}>
        <span>{icon}</span>
        <strong style={{ fontSize: "0.85rem" }}>{title}</strong>
        <span style={{ marginLeft: "auto", fontSize: "0.75rem", color: "var(--color-text-light)" }}>{items.length}개</span>
        <span style={{ color: "var(--color-text-light)" }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div style={{ padding: "8px 12px", background: "var(--color-bg)" }}>
          {items.map((r, i) => (
            <ResourceRow key={i} resource={{ ...r, _type: r._type || type }}
              isSelected={selected.has(r.arn || `${type}:${r.name || r.id}`)}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Summary card ────────────────────────────────────────────────── */
function SummaryCard({ icon, label, count, color }) {
  if (!count) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, padding: "10px 16px", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", minWidth: 70 }}>
      <span style={{ fontSize: "1.2rem" }}>{icon}</span>
      <span style={{ fontSize: "1rem", fontWeight: 700, fontVariantNumeric: "tabular-nums", color: color || "var(--color-text)" }}>{count}</span>
      <span style={{ fontSize: "0.68rem", color: "var(--color-text-light)" }}>{label}</span>
    </div>
  );
}

/* ── Filter panel ────────────────────────────────────────────────── */
function FilterPanel({ sessionId, region, onFilterChange }) {
  const [mode, setMode]             = useState("none");
  const [resourceGroups, setRGs]    = useState([]);
  const [selectedRG, setSelectedRG] = useState("");
  const [tagKeys, setTagKeys]       = useState([]);
  const [tagFilters, setTagFilters] = useState([{ key: "", values: "" }]);
  const [loadingRGs, setLoadingRGs] = useState(false);
  const [loadingKeys, setLoadingKeys] = useState(false);

  useEffect(() => {
    if (mode !== "rg" || !sessionId) return;
    setLoadingRGs(true);
    listArchResourceGroups(sessionId, region)
      .then(r => setRGs(r.groups || [])).catch(() => setRGs([])).finally(() => setLoadingRGs(false));
  }, [mode, sessionId, region]);

  useEffect(() => {
    if (mode !== "tag" || !sessionId) return;
    setLoadingKeys(true);
    listArchTagKeys(sessionId, region)
      .then(r => setTagKeys(r.tag_keys || [])).catch(() => setTagKeys([])).finally(() => setLoadingKeys(false));
  }, [mode, sessionId, region]);

  useEffect(() => {
    if (mode === "none") onFilterChange({ resourceGroup: null, tagFilters: null });
    else if (mode === "rg") onFilterChange({ resourceGroup: selectedRG || null, tagFilters: null });
    else {
      const parsed = tagFilters.filter(f => f.key)
        .map(f => ({ key: f.key, values: f.values.split(",").map(v => v.trim()).filter(Boolean) }));
      onFilterChange({ resourceGroup: null, tagFilters: parsed.length ? parsed : null });
    }
  }, [mode, selectedRG, tagFilters]); // eslint-disable-line react-hooks/exhaustive-deps

  const sel = { padding: "5px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", fontSize: "0.82rem" };

  return (
    <div style={{ paddingTop: 12, borderTop: "1px solid var(--color-border)" }}>
      <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-light)", marginBottom: 10 }}>스캔 범위</div>
      <div style={{ display: "flex", gap: 20, marginBottom: 10, flexWrap: "wrap" }}>
        {[["none","전체",true],["rg","Resource Group"],["tag","Tag 필터"]].map(([v, lbl, warn]) => (
          <label key={v} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: "0.82rem", cursor: "pointer" }}>
            <input type="radio" name="filter-mode" value={v} checked={mode === v} onChange={() => setMode(v)} />
            {lbl}
          </label>
        ))}
      </div>
      {mode === "rg" && (
        <select value={selectedRG} onChange={e => setSelectedRG(e.target.value)} disabled={loadingRGs} style={sel}>
          <option value="">{loadingRGs ? "로드 중…" : resourceGroups.length ? "선택하세요" : "(Resource Group 없음)"}</option>
          {resourceGroups.map(g => <option key={g.arn || g.name} value={g.name}>{g.name}</option>)}
        </select>
      )}
      {mode === "tag" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {tagFilters.map((f, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              {tagKeys.length
                ? <select value={f.key} onChange={e => setTagFilters(p => p.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} disabled={loadingKeys} style={sel}>
                    <option value="">{loadingKeys ? "로드 중…" : "Key 선택"}</option>
                    {tagKeys.map(k => <option key={k} value={k}>{k}</option>)}
                  </select>
                : <input value={f.key} onChange={e => setTagFilters(p => p.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} placeholder="Tag Key" style={{ ...sel, minWidth: 160 }} />
              }
              <span style={{ color: "var(--color-text-light)" }}>=</span>
              <input value={f.values} onChange={e => setTagFilters(p => p.map((x, j) => j === i ? { ...x, values: e.target.value } : x))} placeholder="value1, value2" style={{ ...sel, minWidth: 200 }} />
              {tagFilters.length > 1 && (
                <button type="button" onClick={() => setTagFilters(p => p.filter((_, j) => j !== i))}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-light)", fontSize: "1rem" }}>×</button>
              )}
            </div>
          ))}
          <button type="button" onClick={() => setTagFilters(p => [...p, { key: "", values: "" }])}
            style={{ alignSelf: "flex-start", fontSize: "0.75rem", background: "none", border: "1px dashed var(--color-border)", borderRadius: "var(--radius-sm)", color: "var(--color-text-light)", padding: "3px 10px", cursor: "pointer" }}>
            + 필터 추가
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Main page ───────────────────────────────────────────────────── */
export default function DiscoverPage({ sessionId, sessionScope, onSendToMigration }) {
  const [arch, setArch]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [filter, setFilter]   = useState({ resourceGroup: null, tagFilters: null });

  const region = sessionScope?.aws_region || "ap-northeast-2";

  const handleScan = async () => {
    setLoading(true); setError(null); setSelected(new Set());
    try {
      const data = await scanArchitecture({ sessionId, region, ...filter });
      setArch(data);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const toggleResource = useCallback((key, resource) => {
    setSelected(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  }, []);

  const allTreeResources = useMemo(() => {
    if (!arch) return [];
    const out = [];
    for (const vpc of arch.networking || []) {
      for (const s of vpc.subnets || []) out.push(...(s.resources || []));
      out.push(...(vpc.direct_resources || []));
    }
    out.push(...(arch.s3  || []).map(r => ({ ...r, _type: r._type || "s3" })));
    out.push(...(arch.ecs || []).map(r => ({ ...r, _type: r._type || "ecs" })));
    // Resources not covered by typed collectors (Security Groups, ASGs, EKS, etc.)
    out.push(...(arch.other_resources || []));
    return out;
  }, [arch]);

  const handleSelectAll = () => {
    setSelected(prev =>
      prev.size === allTreeResources.length
        ? new Set()
        : new Set(allTreeResources.map(r => r.arn || `${r._type}:${r.id || r.name}`))
    );
  };

  const handleSend = () => {
    const chosen = selected.size > 0
      ? allTreeResources.filter(r => selected.has(r.arn || `${r._type}:${r.id || r.name}`))
      : allTreeResources;

    const lines = [`Region: ${arch.region}`, `Account: ${arch.account_id}`, `Filter: ${arch.filter || "전체"}`, ""];
    for (const vpc of arch.networking || []) {
      lines.push(`VPC ${vpc.name || vpc.id} (${vpc.cidr})`);
      for (const s of vpc.subnets || []) {
        const res = (s.resources || []).filter(r => selected.size === 0 || selected.has(r.arn || `${r._type}:${r.id || r.name}`));
        if (!res.length) continue;
        lines.push(`  Subnet ${s.name || s.id} (${s.cidr}, ${s.az}, ${s.public ? "public" : "private"})`);
        for (const r of res) {
          lines.push(`    [${typeMeta(r._type).label}] ${r.name || r.id || ""}` + (r.instance_type || r.engine || r.runtime ? ` (${r.instance_type || r.engine || r.runtime})` : ""));
          if (r.iam_role) lines.push(`      IAM Role: ${r.iam_role}`);
          if ((r.security_group_ids || []).length) lines.push(`      SGs: ${r.security_group_ids.join(", ")}`);
        }
      }
      for (const r of (vpc.direct_resources || []).filter(r => selected.size === 0 || selected.has(r.arn || `${r._type}:${r.id || r.name}`))) {
        lines.push(`  [${typeMeta(r._type).label}] ${r.name || r.id || ""}`);
        for (const l of r.listeners || []) {
          for (const tg of l.target_groups || []) lines.push(`    → ${tg.name} [${(tg.targets || []).join(", ")}]`);
        }
      }
    }

    // Filter the architecture graph to only the selected resources (so the
    // v2 pipeline doesn't generate Terraform for things the user excluded).
    const filteredArch = filterArchitecture(arch, chosen);

    onSendToMigration?.({
      spec: lines.join("\n"),
      goals: `AWS account ${arch.account_id} (${arch.region}) → Azure 마이그레이션. VPC 토폴로지 보존, 관리형 서비스 선호.`,
      rows: chosen.map(r => ({ _type: r._type, arn: r.arn, id: r.id || r.name, name: r.name || r.id, service: typeMeta(r._type).label, region: arch.region, vpc_id: r.vpc_id, subnet_id: r.subnet_id, security_group_ids: r.security_group_ids || [], details: r })),
      region: arch.region,
      resourceGroup: arch.resource_group,
      mode: "architecture",
      architecture: filteredArch,   // ← v2 pipeline 입력 (Phase 1 그래프 그대로)
    });
  };

  const s = arch?.summary || {};
  // Show results panel whenever scan completed — even if account has only VPCs and no workloads
  const hasData = !!arch;
  const totalResCount = allTreeResources.length;
  const selectedCount = selected.size;

  return (
    <section className="page-section">

      {/* ─── Header ─── */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: "0 0 4px", fontSize: "1.2rem", fontWeight: 700 }}>
          AWS 아키텍처 탐색
        </h2>
        <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--color-text-light)" }}>
          연결된 AWS 계정의 VPC · 서브넷 · 보안 그룹 · 리소스를 자동 스캔합니다.
        </p>
      </div>

      {/* ─── 스캔 대상 Panel ─── */}
      <div style={{
        padding: "16px 20px",
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-sm)",
        marginBottom: 16,
      }}>
        {/* Panel header + Scan button */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 12,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.8rem", fontWeight: 700, color: "var(--color-text)" }}>
            <span style={{ color: "#00d4aa" }}>●</span> 스캔 대상
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {!sessionId && (
              <span style={{ fontSize: "0.78rem", color: "#f59e0b" }}>⚠ Connect 먼저</span>
            )}
            <button
              type="button"
              className="run-btn action-btn"
              onClick={handleScan}
              disabled={loading || !sessionId}
              style={{ minHeight: 34, padding: "0 20px", fontSize: "0.82rem", fontWeight: 600 }}
            >
              {loading
                ? <><span className="spinner" />스캔 중…</>
                : "🔎 리소스 스캔"
              }
            </button>
          </div>
        </div>

        {/* Account / Region info */}
        {sessionScope && (
          <div style={{ display: "flex", gap: 24, marginBottom: 12, fontSize: "0.82rem" }}>
            <span>
              <span style={{ color: "var(--color-text-light)" }}>계정 </span>
              <strong>{sessionScope.aws_account_id || "—"}</strong>
            </span>
            <span>
              <span style={{ color: "var(--color-text-light)" }}>리전 </span>
              <strong>{region}</strong>
            </span>
          </div>
        )}

        {/* Filter panel (inline) */}
        {sessionId && <FilterPanel sessionId={sessionId} region={region} onFilterChange={setFilter} />}
      </div>

      {error && <div className="form-error" style={{ marginBottom: 16 }}>{error}</div>}

      {arch?.errors && Object.keys(arch.errors).length > 0 && (
        <details style={{ marginBottom: 12 }}>
          <summary style={{ fontSize: "0.78rem", color: "#f59e0b", cursor: "pointer" }}>⚠ 일부 수집 실패 ({Object.keys(arch.errors).length}건)</summary>
          <div style={{ paddingLeft: 12, marginTop: 4, fontSize: "0.75rem", color: "var(--color-text-light)" }}>
            {Object.entries(arch.errors).map(([k, v]) => <div key={k}><strong>{k}</strong>: {v}</div>)}
          </div>
        </details>
      )}

      {/* ─── 스캔 결과 Panel ─── */}
      {hasData && (
        <div style={{
          padding: "16px 20px",
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-sm)",
        }}>
          {/* Header */}
          <div style={{
            display: "flex", alignItems: "center", gap: 8, marginBottom: 14,
            fontSize: "0.8rem", fontWeight: 700, color: "var(--color-text)",
          }}>
            <span style={{ color: "#60a5fa" }}>●</span> 스캔 결과
            <span style={{ marginLeft: "auto", fontSize: "0.78rem", color: "var(--color-text-light)", fontWeight: 400 }}>
              총 {totalResCount}개 리소스
            </span>
          </div>

          {/* Summary breakdown */}
          <div style={{ display: "flex", gap: 16, marginBottom: 14, flexWrap: "wrap", fontSize: "0.78rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontWeight: 600, color: "var(--color-text)" }}>네트워크</span>
              {s.vpcs > 0 && <Badge color="#00d4aa">VPC {s.vpcs}</Badge>}
              {s.subnets > 0 && <Badge>Subnet {s.subnets}</Badge>}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontWeight: 600, color: "var(--color-text)" }}>리소스</span>
              {s.ec2 > 0 && <Badge color="#60a5fa">EC2 {s.ec2}</Badge>}
              {s.rds > 0 && <Badge color="#a78bfa">RDS {s.rds}</Badge>}
              {s.elb > 0 && <Badge color="#34d399">ELB {s.elb}</Badge>}
              {s.lambda > 0 && <Badge color="#fbbf24">Lambda {s.lambda}</Badge>}
              {s.s3 > 0 && <Badge color="#fb923c">S3 {s.s3}</Badge>}
              {s.ecs > 0 && <Badge color="#e879f9">ECS {s.ecs}</Badge>}
              {s.other > 0 && <Badge color="#94a3b8">기타 {s.other}</Badge>}
            </div>
          </div>

          {/* ─── Resource Table ─── */}
          <div style={{ border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", overflow: "hidden" }}>
            {/* Toolbar */}
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "8px 14px",
              background: "#0d1117",
              borderBottom: "1px solid var(--color-border)",
            }}>
              <input
                type="checkbox"
                checked={selectedCount === totalResCount && totalResCount > 0}
                onChange={handleSelectAll}
                style={{ flexShrink: 0, cursor: "pointer" }}
              />
              <span style={{ fontSize: "0.78rem", fontWeight: 600 }}>
                {selectedCount > 0
                  ? `${selectedCount} / ${totalResCount}개 선택됨`
                  : `전체 리소스 (${totalResCount}개)`
                }
              </span>
              <div style={{ marginLeft: "auto" }}>
                <button
                  type="button"
                  className="run-btn action-btn"
                  onClick={handleSend}
                  style={{ minHeight: 30, padding: "0 16px", fontSize: "0.78rem", fontWeight: 600 }}
                >
                  📤 Plan 생성{selectedCount > 0 ? ` (${selectedCount})` : ""}
                </button>
              </div>
            </div>

            {/* Resource list */}
            <div style={{ maxHeight: 480, overflowY: "auto", background: "var(--color-bg)" }}>
              {totalResCount === 0 && (
                <div style={{ padding: "28px 20px", textAlign: "center", color: "var(--color-text-light)", fontSize: "0.85rem" }}>
                  <div style={{ fontSize: "1.8rem", marginBottom: 8 }}>📭</div>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>
                    {s.vpcs > 0
                      ? `VPC ${s.vpcs}개, 서브넷 ${s.subnets}개 발견 — 워크로드 리소스 없음`
                      : "이 리전에 리소스가 없습니다"
                    }
                  </div>
                  <div style={{ fontSize: "0.78rem", opacity: 0.7 }}>
                    EC2, RDS, Lambda, ELB, S3 등의 리소스가 없거나 권한이 부족합니다.
                  </div>
                </div>
              )}
              {(arch.networking || []).map((vpc, i) => (
                <VpcCard key={i} vpc={vpc} selected={selected} onToggle={toggleResource} />
              ))}
              <GlobalSection title="S3 Buckets"   icon="🪣" items={arch.s3}  type="s3"  selected={selected} onToggle={toggleResource} />
              <GlobalSection title="ECS Clusters" icon="🧩" items={arch.ecs} type="ecs" selected={selected} onToggle={toggleResource} />
              {(arch.other_resources || []).length > 0 && (
                <GlobalSection
                  title="기타 리소스 (타입별 수집기 미지원)"
                  icon="📦"
                  items={arch.other_resources}
                  type="other"
                  selected={selected}
                  onToggle={toggleResource}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && !arch && !error && (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          padding: "60px 20px", color: "var(--color-text-light)", textAlign: "center",
        }}>
          <div style={{ fontSize: "2.5rem", marginBottom: 12 }}>🔎</div>
          <p style={{ margin: 0, fontSize: "0.9rem", fontWeight: 500 }}>
            스캔 범위를 설정한 후 "리소스 스캔" 버튼을 클릭하세요.
          </p>
          <p style={{ margin: "6px 0 0", fontSize: "0.78rem" }}>
            VPC, 서브넷, EC2, RDS, ELB, S3 등 리소스를 자동으로 수집합니다.
          </p>
        </div>
      )}
    </section>
  );
}
