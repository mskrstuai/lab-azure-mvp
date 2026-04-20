const STEPS = [
  {
    icon: "🔎",
    title: "1. Discover & Select",
    body: (
      <>
        Connect AWS (default credential chain or <code>AWS_PROFILE</code>),
        pick a region, and select a <strong>Resource Group</strong>. Every
        member resource is enumerated — EC2 instances, VPCs, subnets,
        security groups, launch templates, RDS, S3, Lambda, and more.
      </>
    ),
  },
  {
    icon: "🧭",
    title: "2. Plan",
    body: (
      <>
        The agent turns the selected AWS scope into a structured AWS → Azure
        migration plan <em>and</em> a complete Azure Terraform module (
        <code>providers.tf</code>, <code>variables.tf</code>,
        <code>main.tf</code>, <code>outputs.tf</code>,
        <code>README.md</code>).
      </>
    ),
  },
  {
    icon: "🚀",
    title: "3. Deploy & Migrate",
    body: (
      <>
        Download the Terraform module as a <code>.zip</code>, review it,
        then run the standard <code>terraform init / plan / apply</code>{" "}
        workflow against your Azure subscription.
      </>
    ),
  },
];

function HomePage({ onStart }) {
  return (
    <section className="page-section">
      <h2 className="page-title">☁️ Overview</h2>
      <p className="page-desc">
        A guided, read-only workflow that turns an AWS Resource Group into a
        deployable Azure Terraform module. Planning assistance only — validate
        against your landing zone, compliance, and cost models before apply.
      </p>

      <div className="stats-grid" style={{ marginTop: 8 }}>
        {STEPS.map((s) => (
          <div className="stat-card" key={s.title} style={{ padding: 18 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                marginBottom: 10,
              }}
            >
              <span style={{ fontSize: "1.35rem" }}>{s.icon}</span>
              <strong style={{ fontSize: "0.98rem" }}>{s.title}</strong>
            </div>
            <div
              style={{
                fontSize: "0.85rem",
                color: "var(--color-text-light)",
                lineHeight: 1.55,
              }}
            >
              {s.body}
            </div>
          </div>
        ))}
      </div>

      <div className="form-section" style={{ maxWidth: 820, marginTop: 12 }}>
        <h3 className="result-section-title">Prerequisites</h3>
        <ul className="home-list">
          <li>
            <strong>Azure OpenAI</strong> — set <code>AZURE_OPENAI_ENDPOINT</code>
            {" "}and deploy a chat model. Local auth uses <code>az login</code>{" "}
            (DefaultAzureCredential).
          </li>
          <li>
            <strong>AWS credentials</strong> — any method supported by boto3
            (<code>AWS_PROFILE</code>, env vars, instance role). Requires{" "}
            <code>resource-groups:ListGroupResources</code> and{" "}
            <code>tag:GetResources</code>.
          </li>
          <li>
            <strong>Terraform &amp; Azure CLI</strong> — needed only on your
            local machine when it is time to <em>apply</em> the generated
            module.
          </li>
          <li>
            <strong>Backend</strong> on port <strong>8002</strong>, frontend dev
            server on <strong>5174</strong>.
          </li>
        </ul>
      </div>

      {onStart && (
        <button
          type="button"
          className="run-btn"
          style={{ marginTop: 16 }}
          onClick={onStart}
        >
          🔎 Start — Discover &amp; Select
        </button>
      )}
    </section>
  );
}

export default HomePage;
