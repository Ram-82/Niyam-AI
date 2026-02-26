Deployment notes for the `niyam-backend` FastAPI service

Local run
---------
1. From repository root:

```powershell
cd niyam-backend
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Render / Railway / Heroku (recommended quick deploy)
--------------------------------------------------
- Connect the GitHub repo and choose the `niyam-backend` subdirectory as the service root.
- Build command: `pip install -r requirements.txt`
- Start command / Procfile: `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Ensure the platform sets an environment variable `PORT` (Render, Railway, Heroku do).

Notes about Vercel
-------------------
Vercel is optimized for frontend and serverless functions. Deploying a long-lived ASGI server (uvicorn) inside the same Vercel project is not supported as a typical web service. Options:

- Keep the frontend on Vercel and deploy `niyam-backend` separately to Render/Railway/Heroku.
- Or convert backend endpoints into Vercel Serverless Functions under an `/api` folder (requires refactor: each route into a function and using an adapter for ASGI). This is more work and not recommended for a full FastAPI app.

Environment variables
---------------------
Set any secrets (DB, JWT secret, SUPABASE keys) in the host's environment settings.

Example Heroku steps (CLI)
--------------------------
1. Create an app in the `niyam-backend` folder or set root in dashboard.
2. Push to Heroku (from repo root):

```powershell
heroku create your-app-name
git push heroku main
```

Then set config vars in dashboard: `PORT`, `DATABASE_URL`, `JWT_SECRET`, etc.

GitHub Actions (auto-deploy)
---------------------------
Two workflows are provided in `.github/workflows/`:

- `deploy-heroku.yml` — pushes the `niyam-backend` subdirectory to a Heroku app using the Heroku git endpoint. Required repository secrets:
	- `HEROKU_API_KEY` — your Heroku API key
	- `HEROKU_APP_NAME` — the Heroku app name (e.g., `my-niyam-backend`)

- `deploy-render.yml` — triggers a new deploy on Render via the Render API. Required repository secrets:
	- `RENDER_API_KEY` — Render API key
	- `RENDER_SERVICE_ID` — Render service ID (the UUID for your service)

To enable automatic deploys:

1. Add the appropriate secrets to your GitHub repo (Settings → Secrets → Actions).
2. Ensure the services are configured to use the `niyam-backend` folder as the service root (Render) or that the Heroku app expects a Python app from the pushed repository contents.

Notes:
- The Heroku workflow uses a lightweight git init/commit in the `niyam-backend` folder and pushes that folder's contents to the Heroku remote. This keeps the Heroku slug focused on the backend only.
- The Render workflow triggers Render's API to start a deploy from the repository. Render will pull the latest commit and build from your configuration.

Verifying secrets (quick check)
-------------------------------
A manual workflow `verify-secrets.yml` is provided to ensure the required repository secrets are configured before attempting automatic deploys.

How to add secrets (web UI)
1. Open your GitHub repository in the browser.
2. Go to `Settings` → `Secrets and variables` → `Actions` → `New repository secret`.
3. Add the following secrets (values below are examples — use your real keys):
	- `HEROKU_API_KEY` — your Heroku API key
	- `HEROKU_APP_NAME` — the Heroku app name (e.g., `my-niyam-backend`)
	- `RENDER_API_KEY` — your Render API key
	- `RENDER_SERVICE_ID` — the Render service UUID for your backend

How to add secrets (gh CLI)
```bash
gh secret set HEROKU_API_KEY --body "<your_heroku_api_key>"
gh secret set HEROKU_APP_NAME --body "<your_heroku_app_name>"
gh secret set RENDER_API_KEY --body "<your_render_api_key>"
gh secret set RENDER_SERVICE_ID --body "<your_render_service_id>"
```

How to run the verification workflow
1. Push your changes to the `main` branch (or use the GitHub UI to create a branch and open a PR).
2. In GitHub, go to the `Actions` tab, find `Verify GitHub Actions Secrets`, and click `Run workflow` → choose branch `main` → `Run workflow`.
3. The workflow will report which secrets are present or missing. It does not print secret values.

Testing a deploy trigger
------------------------
Once secrets are added, you can test a deploy by making a trivial commit that touches the `niyam-backend` folder and pushing it to `main`. Example:

```bash
git checkout main
git pull origin main
# make a small change, e.g. update DEPLOY.md or create a file
git add niyam-backend/.github/trigger-test
git commit -m "chore: test deploy trigger for niyam-backend"
git push origin main
```

This push will: 1) trigger the `deploy-heroku.yml` and `deploy-render.yml` workflows (they are scoped to changes under `niyam-backend/**`), and 2) if secrets are present, they will attempt to deploy as configured.

If you want me to run a test push from this environment I will need your Git remote push access set up (or you can add me as a collaborator and provide temporary push credentials). For security, I will not request or handle your keys directly — use GitHub secrets to store them.


