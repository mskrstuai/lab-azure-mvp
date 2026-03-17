# Production Recommendation — Healthcare Supply Chain

Hybrid AI demo: classical ML (Jaccard similarity) + agentic orchestration (Azure OpenAI) for healthcare supply chain customer profiling and product recommendations.

## Architecture

```
┌─────────────┐       ┌──────────────────────────────────────┐
│  Frontend    │──────▶│  Backend (FastAPI)                    │
│  React+Vite  │  /api │  ├── Routers (customers,inventory,..)│
│  port 5173   │       │  ├── Similarity Model (Jaccard ML)   │
└─────────────┘       │  └── Orchestrator (Azure OpenAI)     │
                      │       ↕ tool calls                    │
                      │     Data (customers, products, ...)   │
                      └──────────────────────────────────────┘
```

**Three levels:**

| Level | Name | Tech |
|-------|------|------|
| 1 | Classical ML | Jaccard / Cosine / Dice / Overlap similarity |
| 2 | Agentic Orchestration | Azure OpenAI + function calling |
| 3 | AI-Native Dev | GitHub Copilot |

## Quick Start

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in Azure OpenAI credentials
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

## Features

- **Chat Advisor** — AI-powered chat interface for natural language queries (Azure OpenAI + 13 tools)
- **Customers** — Browse 50 healthcare customer profiles with filtering and sorting
- **Recommendations** — Product recommendations based on collaborative filtering via Jaccard similarity
- **Inventory** — Regional inventory status and shortage alerts

### Agent Tools (13)

| Category | Tools |
|----------|-------|
| Data | `get_summary_stats`, `get_customer_profile`, `find_similar_customers`, `get_product_recommendations`, `check_inventory_alerts`, `get_regional_inventory`, `list_customers` |
| ML Model | `get_model_summary`, `explain_similarity`, `get_feature_importance`, `compare_algorithms`, `retrain_model`, `list_algorithms` |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/stats/summary` | Aggregate statistics |
| GET | `/api/customers` | List customers (filters: region, type, sort_by) |
| GET | `/api/customers/{id}` | Customer profile |
| GET | `/api/customers/{id}/similar` | Similar customers |
| GET | `/api/customers/{id}/recommendations` | Product recommendations |
| GET | `/api/inventory/alerts` | Inventory alerts |
| GET | `/api/inventory/{region}` | Regional inventory |
| GET | `/api/model/summary` | ML model status |
| GET | `/api/model/explain/{a}/{b}` | Similarity explanation |
| POST | `/api/model/retrain` | Retrain model |
| POST | `/api/chat` | Chat with AI advisor |
| POST | `/api/chat/reset` | Reset conversation |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL | — |
| `AZURE_OPENAI_API_KEY` | API key (or use Azure AD) | — |
| `AZURE_OPENAI_DEPLOYMENT` | Model deployment name | `gpt-4o` |
| `AZURE_OPENAI_API_VERSION` | API version | `2024-06-01` |

## Data

- **customers.json** — 50 healthcare customer profiles with 34-category purchase vectors
- **products.json** — 200+ products across 34 categories
- **similarity.json** — Pre-computed similarity index
- **inventory.json** — 5 regional distribution centers with stock levels
