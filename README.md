# lab-azure-mvp

## 260309 Personalized Recommendation Demo

Project path: `./260309_personalized_recommendation`

### Backend (FastAPI + SQLite)

```bash
cd ./260309_personalized_recommendation/backend
pip install -r requirements.txt
python data_loader.py
uvicorn app.main:app --reload
```

Swagger UI: `http://127.0.0.1:8000/docs`

### Frontend (React)

```bash
cd ./260309_personalized_recommendation/frontend
npm install
npm run dev
```
