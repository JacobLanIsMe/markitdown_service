# markitdown — FastAPI demo

This is a minimal FastAPI project scaffold for a POST API example.

Run (PowerShell):

```powershell
# activate the venv (adjust path if needed)
.\.venv\Scripts\Activate.ps1

# start the server
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Example POST (curl):

```bash
curl -X POST "http://127.0.0.1:8000/items/" \
  -H "Content-Type: application/json" \
  -d '{"name":"Sample","price":12.5,"description":"A sample","tax":1.25}'
```

Example POST (PowerShell Invoke-RestMethod):

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/items/ -Body (@{ name = 'Sample'; price = 12.5; description = 'A sample'; tax = 1.25 } | ConvertTo-Json) -ContentType 'application/json'
```

API docs available at `http://127.0.0.1:8000/docs` after server start.
