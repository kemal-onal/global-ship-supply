# Start the stack (Windows)

> Quick start. For the full guide (DB creation, Docker, etc.)
> see **readme.md** → "Quickstart — local development (no Docker)".

---

## ⚠️ Two `.venv` folders exist — use the one inside `backend/`

There is a stray `.venv` at the repo root that is **not** this project's.
Always activate `backend/.venv` and always run from `backend/`.

---

## 1. DB — PostgreSQL 16

Must be running on `localhost:5432` (role `avs`, password `avs-dev-password`, db `avs`).

**If it's a Windows service:**
```powershell
services.msc → PostgreSQL 16 → Start
```

**If it was installed without a service (manual cluster):**
```powershell
& "C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe" -D "C:\Program Files\PostgreSQL\16\data" -l "C:\Program Files\PostgreSQL\16\data\log.txt" start
```

Verify it's reachable:
```powershell
"C:\Program Files\PostgreSQL\16\bin\pg_isready.exe" -h localhost -p 5432
# → localhost:5432 - baðlantýlar kabul ediliyor
```

If you get a connection error, see readme.md §2.1 before proceeding.

## 2. Backend

```powershell
cd backend                           # ← into backend/ first
.venv\Scripts\Activate.ps1           # ← this .venv, NOT the one at repo root
$env:PYTHONUTF8 = 1
# Free port 8000 if a previous server is still running (WinError 10013):
taskkill /IM python.exe /F            # ← if it says "not found", port is already free
python -m uvicorn app.main:app --reload --port 8000
```

**Why `python -m uvicorn` and not bare `uvicorn`?**
The `uvicorn.exe` launcher in this `.venv` has a corrupted interpreter path (`Masa³st³` instead of `Masaüstü`) — a known Windows issue when creating a venv in a path with non-ASCII characters. `python -m uvicorn` bypasses the launcher and uses the activated interpreter directly.

**Why this order matters:**
- `python -m uvicorn app.main:app` needs Python's cwd inside `backend/` so it can find the `app` package at `backend/app/`.
- The root `.venv` at `mock-up-backup/.venv` is a leftover from an older setup and does not have the project's dependencies — activating it gives a false sense that everything is fine, then `ModuleNotFoundError: No module named 'app'` follows.
- If you see `WinError 10013` (access denied on port 8000), a previous server instance is still holding the port. `taskkill /IM python.exe /F` kills it.

## 3. Frontend (Vite — localhost:5173 → 8000 proxy)

```powershell
cd /frontend
npm run dev
```

## 4. (Optional) AIS simulator — visible fleet movement on /fleet-map

Open a **second** PowerShell window:

```powershell
cd backend
.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = 1
$env:SIM_SIM_TIME_SCALE = 60       # 1 wall-sec = 1 sim-min
python -m sim.runner --scenario default_med --max-iterations 200
```

> Without this, /fleet-map shows an empty state (no position data).
> See readme.md §AIS simulator for details.
