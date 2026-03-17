"""Run the Promotion Planning API server.
Port 8001 to avoid conflict with Executor (8000).
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
