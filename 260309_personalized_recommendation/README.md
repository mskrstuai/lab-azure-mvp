# Personalized Recommendation Demo

H&M Personalized Fashion Recommendations dataset을 활용한 추천 시스템 데모 애플리케이션입니다.

- **Backend**: FastAPI + SQLite + SQLAlchemy
- **Frontend**: React (Vite)

## 디렉토리 구조

```
260309_personalized_recommendation/
│
├─ data/                    # Kaggle 데이터셋 (별도 다운로드 필요)
│  ├─ articles.csv
│  ├─ customers.csv
│  ├─ transactions_train.csv
│  └─ images/               # 상품 이미지
│
├─ backend/
│  ├─ app/
│  │  ├─ main.py            # FastAPI 앱 진입점
│  │  ├─ database.py        # SQLAlchemy 엔진 / 세션 설정
│  │  ├─ models.py          # ORM 모델 (Article, Customer, Transaction)
│  │  ├─ schemas.py         # Pydantic 스키마
│  │  ├─ crud.py            # CRUD 함수
│  │  └─ routers/
│  │      ├─ articles.py
│  │      ├─ customers.py
│  │      └─ transactions.py
│  │
│  ├─ data_loader.py        # CSV → SQLite 변환 스크립트
│  └─ requirements.txt
│
└─ frontend/
   ├─ src/
   │  ├─ pages/
   │  │  ├─ ArticlesPage.jsx
   │  │  ├─ CustomersPage.jsx
   │  │  └─ TransactionsPage.jsx
   │  ├─ components/
   │  │  └─ EntityTable.jsx
   │  ├─ api/
   │  │  └─ apiClient.js
   │  ├─ constants.js
   │  └─ App.jsx
   ├─ index.html
   └─ package.json
```

## 데이터셋 준비

Kaggle에서 데이터셋을 다운로드하여 `data/` 디렉토리에 배치합니다.

- 데이터셋: https://www.kaggle.com/competitions/h-and-m-personalized-fashion-recommendations/data
- 필요한 파일:
  - `articles.csv`
  - `customers.csv`
  - `transactions_train.csv`
  - `images/` (상품 이미지 디렉토리)

```bash
# data/ 디렉토리 구조 예시
data/
├─ articles.csv
├─ customers.csv
├─ transactions_train.csv
└─ images/
   ├─ 010/
   │  ├─ 0108775015.jpg
   │  └─ ...
   └─ ...
```

## 실행 방법

### 1. Backend

```bash
cd backend
pip install -r requirements.txt

# CSV → SQLite 변환
python data_loader.py

# FastAPI 서버 실행
uvicorn app.main:app --reload
```

- API 문서 (Swagger UI): http://127.0.0.1:8000/docs

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

- 앱 URL: http://127.0.0.1:5173

## API 엔드포인트

| Method | Path                          | Description        |
|--------|-------------------------------|--------------------|
| GET    | `/api/articles`               | 아티클 목록 조회   |
| GET    | `/api/articles/{article_id}`  | 아티클 상세 조회   |
| GET    | `/api/customers`              | 고객 목록 조회     |
| GET    | `/api/customers/{customer_id}`| 고객 상세 조회     |
| GET    | `/api/transactions`           | 거래 내역 조회     |

모든 목록 API는 `limit`과 `offset` 파라미터를 지원합니다.

```
GET /api/articles?limit=50&offset=0
```

## 주요 기능

- **Tab 기반 네비게이션**: Articles / Customers / Transactions 탭
- **EntityTable**: 동적 컬럼 렌더링, 정렬, 페이지네이션 지원
- **상품 이미지 표시**: article_id를 기반으로 이미지 매칭 및 표시
- **Swagger UI**: FastAPI 자동 API 문서 제공
