# Promotion Planning

Promotion Planning 앱: agentic-analytics의 프로모션 데이터와 **Run Analysis** 기능을 활용한 백엔드(FastAPI) + React 프론트엔드.

## 구조

```
260310_promotion_planning/
├── backend/              # FastAPI 백엔드 (port 8001)
│   ├── app/
│   │   ├── main.py
│   │   ├── data_loader.py
│   │   ├── agent_module/     # Run Analysis (agentic-analytics 마이그레이션)
│   │   │   ├── agent.py
│   │   │   ├── prompts/
│   │   │   ├── schema/
│   │   │   └── simulator/
│   │   └── routers/
│   │       ├── promotions.py
│   │       └── analysis.py
│   ├── data/
│   ├── outputs/         # Run Analysis 결과 저장
│   └── run.py
├── executor/            # Sandboxed Python (port 8000)
│   ├── main.py
│   └── Dockerfile
├── frontend/            # React + Vite
└── docker-compose.yml
```

## 실행 방법

### 옵션 A: 로컬 실행 (권장)

```bash
# 1. Executor (터미널 1) - Run Analysis에 필요
cd executor
pip install -r requirements.txt
EXECUTOR_USERNAME=executor EXECUTOR_PASSWORD=executor-secret python main.py

# 2. 백엔드 (터미널 2)
cd backend
cp ../.env.example .env   # AZURE_OPENAI_* 등 설정
pip install -r requirements.txt
python run.py

# 3. 프론트엔드 (터미널 3)
cd frontend
npm install
npm run dev
```

- Executor: http://127.0.0.1:8000
- 백엔드: http://127.0.0.1:8001
- 프론트엔드: http://127.0.0.1:5173

### 옵션 B: Docker Compose

```bash
cp .env.example .env   # AZURE_OPENAI_ENDPOINT 등 설정
docker-compose up -d

# 프론트엔드는 별도 실행
cd frontend && npm install && npm run dev
```

## Run Analysis (agentic-analytics 마이그레이션)

**Run Analysis** 탭에서 다음 기능 사용:

1. **Run analysis** – 비즈니스 목표 입력 후 AI 에이전트가 프로모션 포트폴리오 생성
2. **Previous outputs** – 이전 실행 결과 조회
3. **Simulate output** – 저장된 JSON에 대해 econometric 모델로 스코어링

**필수 환경 변수:**
- `AZURE_OPENAI_ENDPOINT` – Azure OpenAI 엔드포인트
- `AZURE_OPENAI_DEPLOYMENT` – LLM 배포명 (예: gpt-4o)
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` – 임베딩 배포명
- `EXECUTOR_URL` – Executor URL (기본: http://localhost:8000)
- `EXECUTOR_USERNAME`, `EXECUTOR_PASSWORD` – Executor 인증

## 데이터

- 기본 데이터: `backend/data/synthetic_promotions_snacks_bev.csv`
- `DATA_PATH` 환경 변수로 다른 경로 지정 가능

## API 엔드포인트

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | /api/promotions | 프로모션 목록 |
| GET | /api/promotions/filter-options | 필터 옵션 |
| GET | /api/promotions/stats | 대시보드 통계 |
| GET | /api/promotions/{id} | 단일 프로모션 상세 |
| POST | /api/analysis/run | Run Analysis 시작 |
| GET | /api/analysis/run/{job_id} | Run Analysis 상태 조회 |
| GET | /api/analysis/outputs | 저장된 실행 목록 |
| GET | /api/analysis/outputs/{run_id} | 실행 상세 |
| POST | /api/analysis/simulate | 시뮬레이션 실행 |
