const STEPS = [
  {
    icon: "🔎",
    title: "1. Discover & Select",
    body: (
      <>
        AWS에 연결(<code>AWS_PROFILE</code> 등 boto3 기본 자격 증명)한 뒤 Region을 고르고{" "}
        <strong>Resource Group</strong>을 선택합니다. 멤버 리소스가 한 번에 나열됩니다 — EC2
        instance, VPC, subnet, security group, launch template, RDS, S3, Lambda 등.
      </>
    ),
  },
  {
    icon: "🧭",
    title: "2. Plan",
    body: (
      <>
        에이전트가 선택한 AWS 범위를 구조화된 AWS → Azure 마이그레이션 계획과 완성된 Azure
        Terraform 모듈(<code>providers.tf</code>, <code>variables.tf</code>,
        <code>main.tf</code>, <code>outputs.tf</code>, <code>README.md</code>)로
        바꿉니다.
      </>
    ),
  },
  {
    icon: "🚀",
    title: "3. Deploy & Migrate",
    body: (
      <>
        UI에서 Terraform 모듈을 바로 적용하거나, 필요하면 <code>.zip</code>으로 내려받아
        Azure 구독에 대해 <code>terraform init / plan / apply</code> 워크플로를 실행합니다.
      </>
    ),
  },
];

function HomePage({ onStart }) {
  return (
    <section className="page-section">
      <h2 className="page-title">☁️ Overview</h2>
      <p className="page-desc">
        AWS Resource Group을 읽기 전용으로 조회해, Azure에 배포 가능한 Terraform 모듈로
        이어 주는 가이드 화면입니다. 계획 보조용이므로 Landing zone·규정·비용 모델에 맞는지
        적용 전에 반드시 검증하세요.
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
    </section>
  );
}

export default HomePage;
