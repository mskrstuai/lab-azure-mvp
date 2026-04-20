import React, { useCallback, useEffect, useMemo, useState } from "react";

import {
  getAwsStatus,
  listAwsRegions,
  listAwsResourceGroups,
  listAwsServices,
  scanAwsResources,
} from "../api/apiClient";
import Pagination, { usePagination } from "../components/Pagination";

function StatusBanner({ status }) {
  // Only surface something when AWS is *not* ready — in the happy path the
  // rest of the page already implies readiness, so the banner is redundant.
  if (!status || status.ready) return null;
  return (
    <div className="form-error" style={{ marginBottom: 16 }}>
      <strong>AWS not ready:</strong> {status.reason || "Unknown error"}.
      <div style={{ marginTop: 6, fontSize: "0.85rem", color: "var(--color-text-light)" }}>
        Set <code>AWS_PROFILE</code> (e.g. <code>export AWS_PROFILE=default</code>) or{" "}
        <code>AWS_ACCESS_KEY_ID</code>/<code>AWS_SECRET_ACCESS_KEY</code> in{" "}
        <code>backend/.env</code>, then restart <code>uvicorn</code>.
      </div>
    </div>
  );
}

function formatCell(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return v.toLocaleString();
  return String(v);
}

const SERVICE_META = {
  ec2: { icon: "🖥️", label: "EC2", resourceType: "Instance" },
  rds: { icon: "🗄️", label: "RDS", resourceType: "DB Instance" },
  s3: { icon: "🪣", label: "S3", resourceType: "Bucket" },
  lambda: { icon: "λ", label: "Lambda", resourceType: "Function" },
  vpc: { icon: "🌐", label: "VPC", resourceType: "VPC" },
  elb: { icon: "⚖️", label: "ELB", resourceType: "Load Balancer" },
  dynamodb: { icon: "📇", label: "DynamoDB", resourceType: "Table" },
  ecs: { icon: "🧩", label: "ECS", resourceType: "Cluster" },
};

/** Best-effort human size. */
function fmtBytes(n) {
  if (n == null || n === "") return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = Number(n);
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

/** Filter helper that keeps only populated {label, value} pairs. */
function keepFilled(pairs) {
  return pairs.filter(
    (p) => p && p.value !== null && p.value !== undefined && p.value !== "",
  );
}

/**
 * Normalize a service-specific row into the shared column shape used by the
 * combined resources table.  ``details`` is a list of {label, value} pairs
 * rendered as a key/value table when the row is expanded.
 */
function normalizeRow(serviceKey, serviceLabel, row) {
  const meta = SERVICE_META[serviceKey] || { icon: "•", label: serviceKey, resourceType: "" };
  const base = {
    service: serviceKey,
    serviceLabel,
    serviceDisplay: meta.label,
    icon: meta.icon,
    arn: row.arn || "",
    name: "",
    id: "",
    type: meta.resourceType,
    state: "",
    details: [],
    tags: row.tags || {},
  };
  switch (serviceKey) {
    case "ec2":
      return {
        ...base,
        name: row.name || row.id,
        id: row.id,
        state: row.state,
        details: keepFilled([
          { label: "Instance type", value: row.type },
          { label: "Availability zone", value: row.az },
          { label: "VPC", value: row.vpc },
          { label: "Private IP", value: row.private_ip },
          { label: "Public IP", value: row.public_ip },
          { label: "Launch time", value: row.launch_time },
        ]),
      };
    case "rds":
      return {
        ...base,
        name: row.id,
        id: row.id,
        state: row.status,
        details: keepFilled([
          { label: "Engine", value: [row.engine, row.engine_version].filter(Boolean).join(" ") },
          { label: "Class", value: row.class },
          { label: "Allocated storage", value: row.storage_gb != null ? `${row.storage_gb} GB` : "" },
          { label: "Multi-AZ", value: row.multi_az ? "yes" : "no" },
          { label: "Endpoint", value: row.endpoint },
        ]),
      };
    case "s3":
      return {
        ...base,
        name: row.name,
        id: row.name,
        state: "",
        details: keepFilled([
          { label: "Bucket region", value: row.region },
          { label: "Created", value: row.created },
        ]),
      };
    case "lambda":
      return {
        ...base,
        name: row.name,
        id: row.name,
        state: "",
        details: keepFilled([
          { label: "Runtime", value: row.runtime },
          { label: "Memory", value: row.memory_mb != null ? `${row.memory_mb} MB` : "" },
          { label: "Timeout", value: row.timeout_s != null ? `${row.timeout_s}s` : "" },
          { label: "Last modified", value: row.last_modified },
        ]),
      };
    case "vpc":
      return {
        ...base,
        name: row.name || row.id,
        id: row.id,
        type: row.is_default ? "VPC (default)" : "VPC",
        state: row.state,
        details: keepFilled([
          { label: "CIDR", value: row.cidr },
          { label: "Default VPC", value: row.is_default ? "yes" : "no" },
        ]),
      };
    case "elb":
      return {
        ...base,
        name: row.name,
        id: row.name,
        type: row.type === "application" ? "Application LB" : row.type === "network" ? "Network LB" : "Load Balancer",
        state: row.state,
        details: keepFilled([
          { label: "Scheme", value: row.scheme },
          { label: "VPC", value: row.vpc },
          { label: "DNS", value: row.dns },
        ]),
      };
    case "dynamodb":
      return {
        ...base,
        name: row.name,
        id: row.name,
        state: row.status,
        details: keepFilled([
          { label: "Billing mode", value: row.billing_mode },
          { label: "Items", value: row.items != null ? Number(row.items).toLocaleString() : "" },
          { label: "Size", value: fmtBytes(row.size_bytes) },
        ]),
      };
    case "ecs":
      return {
        ...base,
        name: row.name,
        id: row.name,
        state: row.status,
        details: keepFilled([
          { label: "Active services", value: row.services },
          { label: "Running tasks", value: row.running_tasks },
          { label: "Pending tasks", value: row.pending_tasks },
          { label: "Container instances", value: row.instances },
        ]),
      };
    default:
      return base;
  }
}

/** Flatten all per-service scan results into one combined row array. */
function flattenScan(result) {
  if (!result?.services) return [];
  const rows = [];
  for (const svc of result.services) {
    for (const item of svc.items || []) {
      rows.push(normalizeRow(svc.key, svc.label, item));
    }
  }
  // Stable sort: by service, then by name.
  rows.sort((a, b) =>
    a.service === b.service
      ? (a.name || "").localeCompare(b.name || "")
      : a.service.localeCompare(b.service),
  );
  return rows;
}

/** Build rows for the Resource-Group "every member" response. */
function flattenMembers(result) {
  if (!result?.members) return [];
  return result.members.map((m) => {
    const meta = SERVICE_META[m.service];
    const tags = m.tags || {};
    return {
      service: m.service || "other",
      serviceLabel: m.service_label || "",
      serviceDisplay: m.service_label || (meta ? meta.label : m.service || ""),
      icon: (meta && meta.icon) || "•",
      arn: m.arn || "",
      name: m.name || "",
      id: m.id || "",
      type: m.resource_type_label || m.resource_type || "",
      state: "",
      region: m.region || "",
      tagCount: m.tag_count || Object.keys(tags).length,
      details: [],
      tags,
    };
  });
}

const ELLIPSIS_CELL = {
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

function CombinedResourcesTable({
  rows,
  mode = "service",
  selected,
  onToggle,
  onToggleAll,
}) {
  const [expanded, setExpanded] = useState(() => new Set());
  const isMember = mode === "member";
  const hasSelection = typeof onToggle === "function";

  if (!rows || rows.length === 0) {
    return (
      <div className="empty-state" style={{ marginTop: 16 }}>
        <div className="icon">📭</div>
        <p>No resources in scope.</p>
      </div>
    );
  }

  const rowKeyOf = (r, i) => `${r.service}:${r.arn || r.id || i}`;
  const allKeys = rows.map((r, i) => rowKeyOf(r, i));
  const selectedCount = hasSelection
    ? allKeys.filter((k) => selected?.has(k)).length
    : 0;
  const allSelected = hasSelection && selectedCount === rows.length;
  const someSelected = hasSelection && selectedCount > 0 && !allSelected;

  const pagination = usePagination(rows, 20);
  const { pageItems, start } = pagination;

  const toggle = (key) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="table-wrapper analysis-result-table" style={{ marginTop: 12 }}>
      <table style={{ tableLayout: "fixed", width: "100%" }}>
        <colgroup>
          {hasSelection && <col style={{ width: 36 }} />}
          <col style={{ width: 36 }} />
          <col style={{ width: 150 }} />
          <col style={{ width: 150 }} />
          <col />
          <col />
          {isMember ? (
            <>
              <col style={{ width: 140 }} />
              <col style={{ width: 72 }} />
            </>
          ) : (
            <col style={{ width: 110 }} />
          )}
        </colgroup>
        <thead>
          <tr>
            {hasSelection && (
              <th style={{ textAlign: "center" }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = someSelected;
                  }}
                  onChange={() => onToggleAll?.(allKeys)}
                  aria-label={allSelected ? "Deselect all" : "Select all"}
                />
              </th>
            )}
            <th></th>
            <th>Service</th>
            <th>Type</th>
            <th>Name</th>
            <th>Identifier</th>
            {isMember ? (
              <>
                <th>Region</th>
                <th style={{ textAlign: "right" }}>Tags</th>
              </>
            ) : (
              <th>State</th>
            )}
          </tr>
        </thead>
        <tbody>
          {pageItems.map((r, pi) => {
            const i = start + pi;
            const key = rowKeyOf(r, i);
            const isOpen = expanded.has(key);
            const isSelected = hasSelection && selected?.has(key);
            const hasDetails = (r.details || []).length > 0 || r.arn;
            return (
              <React.Fragment key={key}>
                <tr
                  onClick={() => hasDetails && toggle(key)}
                  style={{
                    cursor: hasDetails ? "pointer" : "default",
                    background: isSelected
                      ? "var(--color-surface-hover)"
                      : isOpen
                      ? "var(--color-surface-hover)"
                      : undefined,
                  }}
                >
                  {hasSelection && (
                    <td
                      style={{ textAlign: "center" }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={!!isSelected}
                        onChange={() => onToggle(key)}
                        aria-label={isSelected ? "Deselect row" : "Select row"}
                      />
                    </td>
                  )}
                  <td
                    style={{
                      textAlign: "center",
                      color: "var(--color-text-light)",
                      userSelect: "none",
                    }}
                    aria-label={isOpen ? "collapse" : "expand"}
                  >
                    {hasDetails ? (isOpen ? "▾" : "▸") : ""}
                  </td>
                  <td style={ELLIPSIS_CELL} title={r.serviceDisplay}>
                    <span style={{ marginRight: 6 }}>{r.icon}</span>
                    <strong>{r.serviceDisplay}</strong>
                  </td>
                  <td style={ELLIPSIS_CELL} title={r.type || ""}>
                    <span
                      className="badge"
                      style={{
                        background: "var(--color-surface)",
                        color: "var(--color-text)",
                        border: "1px solid var(--color-border)",
                        fontSize: "0.75rem",
                      }}
                    >
                      {formatCell(r.type)}
                    </span>
                  </td>
                  <td
                    style={{ ...ELLIPSIS_CELL, fontWeight: 500 }}
                    title={r.name || ""}
                  >
                    {r.name ? r.name : (
                      <span style={{ color: "var(--color-text-light)", fontStyle: "italic" }}>
                        (not tagged)
                      </span>
                    )}
                  </td>
                  <td
                    style={{
                      ...ELLIPSIS_CELL,
                      fontFamily: "monospace",
                      fontSize: "0.78rem",
                    }}
                    title={r.arn || r.id || ""}
                  >
                    {formatCell(r.id)}
                  </td>
                  {isMember ? (
                    <>
                      <td
                        style={{
                          ...ELLIPSIS_CELL,
                          fontSize: "0.82rem",
                          color: "var(--color-text-light)",
                        }}
                        title={r.region || ""}
                      >
                        {formatCell(r.region)}
                      </td>
                      <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                        {r.tagCount}
                      </td>
                    </>
                  ) : (
                    <td style={ELLIPSIS_CELL} title={r.state || ""}>
                      {formatCell(r.state)}
                    </td>
                  )}
                </tr>
                {isOpen && (
                  <tr>
                    <td
                      colSpan={(isMember ? 7 : 6) + (hasSelection ? 1 : 0)}
                      style={{
                        background: "var(--color-bg)",
                        padding: "12px 20px 14px 44px",
                        borderTop: "1px solid var(--color-border)",
                      }}
                    >
                      <DetailTable row={r} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
      <Pagination {...pagination} />
    </div>
  );
}

function DetailTable({ row }) {
  const pairs = [...(row.details || [])];
  if (row.arn) pairs.push({ label: "ARN", value: row.arn });
  const tagEntries = Object.entries(row.tags || {}).sort((a, b) =>
    a[0].localeCompare(b[0]),
  );

  if (pairs.length === 0 && tagEntries.length === 0) {
    return (
      <div style={{ color: "var(--color-text-light)", fontSize: "0.85rem" }}>
        No additional details available.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {pairs.length > 0 && (
        <AttrTable pairs={pairs} />
      )}
      {tagEntries.length > 0 && (
        <div>
          <div
            style={{
              fontSize: "0.72rem",
              fontWeight: 600,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              color: "var(--color-text-light)",
              marginBottom: 6,
            }}
          >
            Tags ({tagEntries.length})
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {tagEntries.map(([k, v]) => (
              <span
                key={k}
                className="badge"
                style={{
                  background: "var(--color-surface)",
                  color: "var(--color-text)",
                  border: "1px solid var(--color-border)",
                  fontSize: "0.75rem",
                  fontFamily:
                    "ui-monospace, SFMono-Regular, Menlo, monospace",
                  padding: "3px 8px",
                  maxWidth: 420,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={`${k}=${v}`}
              >
                <strong style={{ color: "var(--color-text-light)" }}>{k}</strong>
                {v ? <>&nbsp;=&nbsp;{v}</> : null}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AttrTable({ pairs }) {
  return (
    <table style={{ width: "100%", fontSize: "0.85rem", borderCollapse: "collapse" }}>
      <tbody>
        {pairs.map((p, i) => (
          <tr key={i}>
            <td
              style={{
                padding: "4px 12px 4px 0",
                color: "var(--color-text-light)",
                width: 180,
                verticalAlign: "top",
                whiteSpace: "nowrap",
              }}
            >
              {p.label}
            </td>
            <td
              style={{
                padding: "4px 0",
                color: "var(--color-text)",
                fontFamily: p.label === "ARN" || p.label === "DNS" || p.label === "Endpoint" ? "monospace" : undefined,
                fontSize: p.label === "ARN" ? "0.78rem" : undefined,
                wordBreak: "break-all",
              }}
            >
              {formatCell(p.value)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Build a plain-text summary suitable for the Migration "AWS resources and
 * scope" textarea.  Keeps it concise — one line per resource at most.
 */
/**
 * Return a narrowed copy of ``result`` keeping only the rows the user
 * explicitly selected in the combined table.  The shape (``services[].items``
 * vs. ``members[]``) is preserved so downstream spec/goal builders keep
 * working unchanged.
 */
function filterResultBySelection(result, selectedKeys) {
  const matches = (serviceKey, raw) => {
    const id = raw.arn || raw.id || raw.name || "";
    return selectedKeys.has(`${serviceKey}:${id}`);
  };

  if (Array.isArray(result.members)) {
    const members = result.members.filter((m) => matches(m.service, m));
    return {
      ...result,
      members,
      total: members.length,
      resource_group_member_count: members.length,
    };
  }

  const services = (result.services || [])
    .map((svc) => {
      const items = (svc.items || []).filter((it) => matches(svc.key, it));
      return { ...svc, items, count: items.length };
    })
    .filter((svc) => (svc.items || []).length > 0);
  return { ...result, services };
}

function buildMigrationSpec(result) {
  const lines = [`Region: ${result.region}`];
  if (result.resource_group) {
    const total = result.resource_group_member_count;
    lines.push(
      `Resource group: ${result.resource_group}` +
        (total != null ? ` (${total} member resource${total === 1 ? "" : "s"})` : ""),
    );
  } else {
    lines.push("Resource group: (not filtered — full account in region)");
  }

  // Member-mode (Resource Group expansion) — group members by "Service Type".
  if (Array.isArray(result.members)) {
    const groups = new Map();
    for (const m of result.members) {
      const key = `${m.service_label || m.service} ${m.resource_type_label || m.resource_type}`.trim();
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(m);
    }
    lines.push(
      `Scope total: ${result.members.length} resource${result.members.length === 1 ? "" : "s"} across ${groups.size} type(s).`,
    );
    for (const [key, members] of groups) {
      lines.push("", `== ${key} (${members.length}) ==`);
      for (const m of members.slice(0, 25)) {
        const label = m.name ? `${m.name} (${m.id})` : m.id;
        lines.push(`- ${label}`);
      }
      if (members.length > 25) {
        lines.push(`- ... and ${members.length - 25} more`);
      }
    }
    return lines.join("\n");
  }

  // Service-mode fallback (no Resource Group filter).
  const services = result.services || [];
  const totalShown = services.reduce((acc, s) => acc + (s.count || 0), 0);
  lines.push(`Scope total: ${totalShown} resource${totalShown === 1 ? "" : "s"} across ${services.length} service(s).`);

  for (const svc of services) {
    if (!svc.items || svc.items.length === 0) continue;
    lines.push("", `== ${svc.label} (${svc.count}) ==`);
    for (const item of svc.items.slice(0, 25)) {
      const parts = (svc.columns || [])
        .map((c) => (item[c] === null || item[c] === undefined || item[c] === "" ? null : `${c}=${item[c]}`))
        .filter(Boolean);
      lines.push("- " + parts.join(", "));
    }
    if (svc.items.length > 25) {
      lines.push(`- ... and ${svc.items.length - 25} more`);
    }
  }
  return lines.join("\n");
}

function buildMigrationGoals(result) {
  const rg = result.resource_group;
  if (rg) {
    return (
      `Plan migration of AWS Resource Group "${rg}" (region ${result.region}) to Azure. ` +
      `Preserve logical grouping as an Azure Resource Group, minimize downtime, use managed equivalents ` +
      `(EC2→VM/VMSS or AKS, RDS→Azure Database, S3→Storage, Lambda→Functions, ALB/NLB→App Gateway/Front Door, ` +
      `DynamoDB→Cosmos DB), and call out dependencies between members.`
    );
  }
  return (
    `Plan migration of the AWS workload in region ${result.region} to Azure. ` +
    `Minimize downtime, align with hub-spoke networking, and prefer managed Azure services.`
  );
}

function AwsResourcesPage({ onSendToMigration }) {
  const [status, setStatus] = useState(null);
  const [services, setServices] = useState([]);
  const [regions, setRegions] = useState([]);
  const [region, setRegion] = useState("");
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const [resourceGroups, setResourceGroups] = useState([]);
  const [resourceGroup, setResourceGroup] = useState("");
  const [rgLoading, setRgLoading] = useState(false);

  useEffect(() => {
    getAwsStatus()
      .then((s) => {
        setStatus(s);
        if (s.default_region && !region) setRegion(s.default_region);
      })
      .catch((e) => setStatus({ ready: false, reason: e.message }));
    listAwsServices()
      .then((r) => setServices(r.services || []))
      .catch(() => setServices([]));
  }, []);

  const loadRegions = useCallback(() => {
    listAwsRegions()
      .then((r) => setRegions(r.regions || []))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (status?.ready && regions.length === 0) loadRegions();
  }, [status, regions.length, loadRegions]);

  const loadResourceGroups = useCallback(
    (r) => {
      const target = r || region;
      if (!target || !status?.ready) return;
      setRgLoading(true);
      listAwsResourceGroups(target)
        .then((res) => setResourceGroups(res.groups || []))
        .catch((e) => {
          setResourceGroups([]);
          setError(`Resource groups: ${e.message}`);
        })
        .finally(() => setRgLoading(false));
    },
    [region, status],
  );

  // Refresh resource groups whenever a usable region is chosen.
  useEffect(() => {
    if (status?.ready && region) {
      setResourceGroup("");
      loadResourceGroups(region);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.ready, region]);

  const runScan = useCallback(
    ({ silent = false } = {}) => {
      if (!region) {
        if (!silent) setError("Select a region first.");
        return;
      }
      if (services.length === 0) return;
      setError(null);
      setResult(null);
      setScanning(true);
      // Always scan the full catalog — filtering happens via the Resource
      // Group (if any) and the UI renders a single combined table.
      scanAwsResources({
        region,
        services: services.map((s) => s.key),
        resourceGroup: resourceGroup || null,
      })
        .then((res) => {
          setResult(res);
          if (res.resource_group_error) setError(res.resource_group_error);
        })
        .catch((e) => setError(e.message))
        .finally(() => setScanning(false));
    },
    [region, resourceGroup, services],
  );

  const handleScan = () => runScan({ silent: false });

  // Clear any previous result when the user changes region or group — the
  // stale rows don't belong to the new scope, and the next scan starts
  // explicitly via the Discover button below.
  useEffect(() => {
    setResult(null);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [region, resourceGroup]);

  const isMemberMode = Array.isArray(result?.members);

  const combinedRows = useMemo(
    () => (isMemberMode ? flattenMembers(result) : flattenScan(result)),
    [result, isMemberMode],
  );

  const totalCount = useMemo(() => {
    if (!result) return 0;
    if (isMemberMode) return result.total ?? combinedRows.length;
    return (result.services || []).reduce((acc, s) => acc + (s.count || 0), 0);
  }, [result, isMemberMode, combinedRows.length]);

  // Selection state — reset each time a new result lands.  We key rows by
  // ``service:(arn|id)`` which matches the key the table builds below.
  const [selected, setSelected] = useState(() => new Set());
  useEffect(() => {
    setSelected(new Set());
  }, [result]);

  const toggleSelected = useCallback((key) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(
    (keys) => {
      setSelected((prev) => {
        const all = keys.every((k) => prev.has(k));
        return all ? new Set() : new Set(keys);
      });
    },
    [],
  );

  const handleSendToMigration = () => {
    if (!result) return;
    const scoped = selected.size > 0 ? filterResultBySelection(result, selected) : result;
    const spec = buildMigrationSpec(scoped);
    const goals = buildMigrationGoals(scoped);
    const scopedRows = isMemberMode ? flattenMembers(scoped) : flattenScan(scoped);
    onSendToMigration?.({
      spec,
      goals,
      region: scoped.region,
      resourceGroup: scoped.resource_group,
      rows: scopedRows,
      mode: isMemberMode ? "member" : "service",
    });
  };

  return (
    <section className="page-section">
      <h2 className="page-title">🔎 Discover &amp; Select</h2>
      <p className="page-desc">
        Pick a region and (optionally) an <strong>AWS Resource Group</strong>.
        All resources in the group are listed in one shot — no per-service
        picking. Push the scope straight into the Migration planner when
        you're ready. Read-only, uses the backend's default credential chain.
      </p>

      <StatusBanner status={status} />

      <div className="form-section">
        <div className="form-row">
          <div className="form-field">
            <label>Region</label>
            {regions.length > 0 ? (
              <select value={region} onChange={(e) => setRegion(e.target.value)}>
                {regions.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                placeholder="us-east-1"
              />
            )}
          </div>

          <div className="form-field">
            <label>
              Resource Group{" "}
              <span style={{ color: "var(--color-text-light)", fontWeight: 400, fontSize: "0.75rem" }}>
                (optional)
              </span>
            </label>
            <select
              value={resourceGroup}
              onChange={(e) => setResourceGroup(e.target.value)}
              disabled={!status?.ready || rgLoading}
            >
              <option value="">
                {rgLoading
                  ? "Loading resource groups..."
                  : resourceGroups.length === 0
                  ? "(no resource groups found)"
                  : "All resources (no filter)"}
              </option>
              {resourceGroups.map((g) => (
                <option key={g.arn || g.name} value={g.name}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>

        </div>
      </div>

      {error && <div className="form-error">{error}</div>}

      <div className="action-bar">
        <button
          className="run-btn action-btn"
          type="button"
          onClick={handleScan}
          disabled={scanning || !status?.ready}
        >
          {scanning ? (
            <>
              <span className="spinner" />
              Discovering...
            </>
          ) : (
            <>🔎 Discover</>
          )}
        </button>
        {result && (
          <button
            className="tab action-btn action-btn--secondary"
            type="button"
            onClick={handleSendToMigration}
            title={
              selected.size > 0
                ? `Send ${selected.size} selected resource(s) to the Plan page`
                : "Send all discovered resources to the Plan page"
            }
          >
            📤 Plan{selected.size > 0 ? ` (${selected.size})` : ""}
          </button>
        )}
      </div>

      {result && (
        <div className="analysis-result-view" style={{ marginTop: 24 }}>
          <div
            style={{
              color: "var(--color-text-light)",
              fontSize: "0.85rem",
              marginBottom: 8,
            }}
          >
            Scanned <strong style={{ color: "var(--color-text)" }}>{result.region}</strong>
            {result.resource_group && (
              <>
                {" / "}
                <strong style={{ color: "var(--color-text)" }}>{result.resource_group}</strong>
              </>
            )}
            {" — "}
            <strong style={{ color: "var(--color-text)" }}>{totalCount}</strong> resource(s)
            {selected.size > 0 && (
              <>
                {" · "}
                <strong style={{ color: "var(--color-text)" }}>{selected.size}</strong> selected
              </>
            )}
            .
          </div>
          <CombinedResourcesTable
            rows={combinedRows}
            mode={isMemberMode ? "member" : "service"}
            selected={selected}
            onToggle={toggleSelected}
            onToggleAll={toggleSelectAll}
          />
        </div>
      )}
    </section>
  );
}

export default AwsResourcesPage;
