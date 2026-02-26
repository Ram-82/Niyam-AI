Niyam AI Frontend

This folder contains the static frontend for the Niyam AI project. Deploy this directory separately to Vercel, Netlify, or any static host.

Quick deploy to Vercel (recommended):

1. In the Vercel dashboard, create a new project and import this GitHub repository.
2. Set the project root to `niyam-frontend`.
3. Build & Output Settings: for a static site, use the default settings. If using any build step, configure accordingly.
4. Set environment variables if necessary (e.g., `NEXT_PUBLIC_BACKEND_URL`), or update `vercel.json` rewrites to point to your backend.

Local preview:

```bash
# Serve static files (python)
cd niyam-frontend
python -m http.server 3000
# Open http://localhost:3000
```
