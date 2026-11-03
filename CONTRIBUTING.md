# Contributing to Prompt2Process

This guide gets a new teammate from `git clone` to a running app, and lists the checks every change must pass.

## 1. One-time setup
Install:
- **Git**
- **Python 3.12** (the version is in `.python-version`)
- **Node.js 22 LTS** (the version is in `.nvmrc`)
- **Docker Desktop**
- **VS Code**. When you open the folder, accept "Install recommended extensions" (the list is in `.vscode/extensions.json`).

Get a free Gemini API key at <https://aistudio.google.com/apikey>. Each person uses their own key, and keys are never committed. Without a key the app still runs in offline mode.

## 2. Get the code
```powershell
git clone https://github.com/keshav301104/Prompt2Process.git
cd Prompt2Process
code .
```

## 3. Run it
### Option A: Docker (exactly what Render runs)
```powershell
Copy-Item .env.example .env        # then paste your GEMINI_API_KEY into .env
docker compose up --build          # http://localhost:8000
```
Then open the app and click **Load demo workspace**. Stop it with `Ctrl + C`, and reset all data with `docker compose down -v`.

### Option B: Local development (hot reload)
**Terminal 1, backend:**
```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate             # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
Copy-Item .env.example .env        # macOS/Linux: cp .env.example .env
cd backend
python -m app.llm.check            # optional: tests your Gemma 4 access
uvicorn app.main:app --reload --port 8000
```
**Terminal 2, frontend:**
```powershell
cd frontend
npm ci
npm run dev                        # http://localhost:5173, proxies /api to :8000
```
If PowerShell refuses to activate the venv, run `Set-ExecutionPolicy -Scope Process Bypass` once in that terminal.

## 4. Checks every change must pass
Run these from the repository root (with the venv active). CI runs the same commands.

| Check | Command |
|---|---|
| Python lint | `ruff check backend/app` |
| Python formatting | `ruff format --check backend/app` (use `ruff format backend/app` to fix) |
| Python types | `mypy backend/app` |
| Frontend types + build | `cd frontend; npm run build` |
| Frontend lint | `cd frontend; npm run lint` |
| Container build | `docker build -t prompt2process .` |

## 5. Branch and pull-request workflow
- **Never commit to `main` directly.** Create a branch per task:
  ```powershell
  git switch main
  git pull
  git switch -c ci/github-actions      # e.g. feat/..., fix/..., ci/..., docs/...
  ```
- **Small, focused commits** using conventional-commit messages, the style already used in this repo:
  `feat(...)`, `fix(...)`, `perf(...)`, `refactor(...)`, `docs: ...`, `ci: ...`, `chore: ...`
- **Push the branch and open a pull request:**
  ```powershell
  git push -u origin ci/github-actions
  ```
  Then click **Compare & pull request** on GitHub and ask the other person to review it.
- **Keep your branch up to date:** `git pull origin main`, fix any conflicts, then push.

## 6. Rules
- **Never commit secrets.** `.env` is git-ignored. In CI and on Render, keys go into the platform's secret settings.
- **Never commit generated data.** `data/` (demo documents) and `state/` (database, checkpoints) are regenerated automatically and are git-ignored.
- **Change dependency pins deliberately.** Edit the pin in `requirements.txt` / `requirements-dev.txt`, or use `npm install <pkg>@<version>` for the frontend, so `package-lock.json` updates. Run the checks, then commit.
- **Keep the app working offline** (`LLM_MODE=offline`), so CI never needs a Gemini key.

## Project map
- `backend/app/`: FastAPI app (`main.py`), the plan compiler and checker (`core/`), skills (`actions/`), sector templates (`packs/*.yaml`), workforce logic (`workforce/`), ML (`learning/`), safety (`safety/`), and the Gemma client (`llm/`).
- `frontend/src/`: React console. The pages are in `pages/`, shared UI in `components/`, and the API client in `lib/api.tsx`.
- `Dockerfile`, `docker-compose.yml`, `render.yaml`: container build, local run, and the deployment blueprint.
- `API_SPEC.md`: the API contract between backend and frontend.
