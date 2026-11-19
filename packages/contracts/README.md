# ShopFlow API contracts

`api.generated.ts` is produced by [`openapi-typescript`](https://openapi-ts.dev)
from the FastAPI OpenAPI schema. Regenerate it whenever the backend OpenAPI
schema changes:

```powershell
# Terminal 1 - backend on port 8001
cd apps\api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001 --reload

# Terminal 2 - regenerate + validate
cd apps\web
npm run gen:types
```

The file is checked in so the frontend and any future client share one
source of truth without needing the backend running.
