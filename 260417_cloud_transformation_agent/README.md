# Cloud Transformation Agent (AWS → Azure)

AWS 리소스 범위를 자연어로 입력하면 Azure OpenAI가 **마이그레이션 단계, 매핑, 리스크, 미결 사항**을 구조화해 반환하는 MVP입니다. [260310_promotion_planning](../260310_promotion_planning/)과 같은 **FastAPI 백엔드 + Vite/React 프론트**, 비동기 작업·`outputs/` 저장 패턴을 따릅니다.

## Prerequisites

- Python 3.9+ (structured output uses the OpenAI Python SDK + `beta.chat.completions.parse`; use a model/deployment that supports it, e.g. `gpt-4o`)
- Node 18+
- Azure OpenAI 엔드포인트와 채팅 배포
- 로컬: `az login` 후 `DefaultAzureCredential`로 토큰

의존성은 `260310_promotion_planning`의 LangChain 스택 대신 **경량 `openai` + `azure-identity`**로 두어, 동일 저장소의 구형 Python에서도 설치가 되도록 했습니다.

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # AZURE_OPENAI_ENDPOINT 등 수정
uvicorn app.main:app --reload --port 8002
```

- Health: `http://127.0.0.1:8002/health`
- API: `POST /api/migration/run`, `GET /api/migration/run/{job_id}`, `GET /api/migration/outputs`, …

## Frontend

```bash
cd frontend
npm install
npm run dev
```

- 기본 포트 **5174** (다른 MVP와 충돌 방지). Vite 프록시가 `/api` → `8002`로 전달합니다.

## AWS Resources 탭 (옵션)

프론트엔드의 **🔎 AWS resources** 탭은 실제 AWS 계정을 읽기 전용으로 조회해서 EC2 / RDS / S3 / Lambda / VPC / ELB / DynamoDB / ECS 목록을 표로 보여주고, 한 번의 클릭으로 Migration planner의 입력란에 채워 넣습니다.

**AWS Resource Group 필터** — 리전을 고르면 해당 리전의 Resource Group 목록이 드롭다운에 채워집니다. 하나를 선택하면 `resource-groups:ListGroupResources`로 멤버 ARN을 받아와 각 서비스 스캔 결과를 그 집합에 속한 것만 남깁니다. 선택 시 각 서비스 칩에 "이 그룹에 몇 개가 있는지" 배지가 표시되고, **📤 Build migration plan from this scope** 버튼은 (1) 리전·그룹 컨텍스트가 포함된 AWS 스코프 텍스트와 (2) "이 Resource Group을 Azure로 마이그레이션" 목표 문장을 Migration planner에 동시에 프리필합니다.

백엔드는 boto3 기본 자격 증명 체인을 그대로 사용합니다. 아래 중 하나만 설정되어 있으면 됩니다.

```bash
# 1) 권장: 프로필
export AWS_PROFILE=default

# 2) 정적 키
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
# 임시 자격이라면
export AWS_SESSION_TOKEN=...
```

`backend/.env`의 `AWS_*` 항목을 채워도 동일하게 동작합니다.

주요 엔드포인트:

- `GET /api/aws/status` — 자격 증명 점검
- `GET /api/aws/regions` — 리전 목록
- `GET /api/aws/resource-groups?region=<r>` — 해당 리전의 Resource Group 목록
- `GET /api/aws/resource-groups/<name>?region=<r>` — 그룹 멤버 ARN + 서비스별 카운트
- `POST /api/aws/scan` — 본문 예시:
  ```json
  { "region": "us-east-1", "services": ["ec2","rds"], "resource_group": "my-prod-stack" }
  ```
  `resource_group`을 주면 해당 그룹 멤버 ARN에 매칭되는 항목만 반환하며, 응답에 `count` / `total_before_filter` / `resource_group_member_count`를 함께 돌려줍니다.

필요한 IAM 권한 (읽기 전용):

- 서비스별 `describe_*` / `list_*` (이미 사용 중이던 권한과 동일)
- `resource-groups:ListGroups`, `resource-groups:ListGroupResources`

## Notes

- 이 도구는 **계획·설계 보조**이며, 실제 이전·비용·규정 준수는 별도 검증이 필요합니다.
- AWS resources 탭은 읽기 전용(`describe_*` / `list_*`)만 호출합니다. 쓰기 API는 사용하지 않습니다.
