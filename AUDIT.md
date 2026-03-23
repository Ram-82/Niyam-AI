# Niyam AI - Complete Repo Audit

**Date:** 2026-03-23
**Auditor:** Claude (Senior Product Engineer)

---

## 1. Current Architecture

```
FRONTEND (Vanilla HTML/CSS/JS)          BACKEND (FastAPI/Python)           DATABASE
┌──────────────────────────┐     ┌──────────────────────────────┐    ┌──────────────┐
│ index.html (landing)     │     │ main.py (FastAPI app)        │    │ Supabase     │
│ login.html               │────>│ routes/auth.py (WORKING)     │───>│ (PostgreSQL) │
│ signup.html              │     │ routes/dashboard.py (STUB)   │    │              │
│ dashboard.html (3256 LOC)│     │ routes/gst.py (STUB)         │    │ 4 tables:    │
│ ocr_demo.html            │     │ routes/tds.py (STUB)         │    │ - businesses │
│ config.js                │     │ routes/roc.py (STUB)         │    │ - users      │
│ style.css                │     │ routes/ocr.py (STUB)         │    │ - deadlines  │
└──────────────────────────┘     │ routes/analytics.py (STUB)   │    │ - gst_filings│
   Deployed: Vercel              │ routes/settings.py (STUB)    │    └──────────────┘
                                 │                              │       NOT CONNECTED
                                 │ services/auth_service.py     │
                                 │ utils/mock_db.py (JSON files)│◄── Actually used
                                 │ utils/security.py (JWT)      │
                                 └──────────────────────────────┘
                                    Deployed: Render
```

**Data Flow:** Frontend stores JWT in localStorage → sends Bearer token on API calls → Backend validates JWT → queries MockDB (JSON files on disk) or Supabase (if configured). In practice, it's always MockDB because no real Supabase credentials are wired.

---

## 2. What is Working vs Broken

### WORKING
- Auth flow (signup/login/token refresh) — fully implemented with Supabase + MockDB fallback
- JWT token management — access + refresh tokens, proper hashing with passlib
- Frontend pages render — landing, login, signup, dashboard all load visually
- Dashboard UI shell — charts, calendar, sidebar, metrics cards render with placeholder data
- Deployment pipeline — GitHub Actions for Render + Heroku, Vercel config for frontend
- CORS configuration — set up for localhost + Vercel domain
- Pydantic models — well-structured models for compliance, GST filings, deadlines

### BROKEN / NON-FUNCTIONAL
- Database connection — test_connection() commented out, health check hardcodes db_connected = True
- Dashboard API — returns hardcoded values, no real data
- GST route — returns empty array, no service layer
- TDS/ROC/Analytics/Settings routes — literal placeholder strings
- OCR route — GET-only stub; frontend calls POST /api/ocr/process which doesn't exist
- OCR demo page — posts to relative path (not CONFIG.API_URL), will always 404
- Health endpoint timestamp — hardcoded to 2025-01-06
- on_event deprecation — startup/shutdown events deprecated in FastAPI
- Chart.js loaded twice in dashboard.html

---

## 3. Missing Components for MVP

### OCR — 0% Built
- No POST /api/ocr/process endpoint
- pytesseract/pdf2image/Pillow commented out in requirements.txt
- No document parsing logic
- No file storage (S3/Supabase storage)

### Rules Engine — 0% Built
- No GST deadline calculator
- No TDS due date rules
- No ROC filing rules
- No penalty calculation
- No compliance health scoring algorithm
- Models exist but no logic uses them

### ITC Matching — 0% Built
- No GSTR-2A/2B ingestion
- No purchase register
- No invoice matching algorithm
- Only two model fields (itc_available, itc_claimed) exist

### APIs — Only Auth Works
- GST/TDS/ROC CRUD — stubs only
- Deadline management — nothing
- Calendar events API — nothing (FullCalendar loaded but no data source)
- File upload — configured but no handler

### Database — 30% Designed
- Supabase connection code exists but broken in prod
- SQL schema exists, unclear if ever applied
- Missing tables: tds_filings, roc_filings, ocr_documents, notifications
- Missing RLS policies for compliance_deadlines and gst_filings

---

## 4. Tech Debt / Messy Areas

### Critical
1. 3,256-line dashboard.html monolith (164KB — inline CSS + HTML + JS)
2. Dual auth systems (Supabase Auth + custom JWT competing)
3. MockDB as production crutch (no locking, no concurrency safety)
4. No env validation — JWT likely using default secret "your-secret-key-change-in-production"

### Moderate
5. Duplicate HTML files at repo root vs niyam-frontend/
6. simple_main.py — dead prototype code
7. prompt.txt (37KB) checked into repo
8. start_server.bat — Windows-only, deploys to Linux
9. Bare except in auth_service.py:297
10. TrustedHostMiddleware with allowed_hosts=["*"] (no-op)
11. CORS missing localhost:5500 (Live Server)

### Minor
12. datetime.utcnow() deprecated in Python 3.12+
13. Access token expires in 7 days (too long for compliance app)
14. No rate limiting on auth endpoints
15. Zero tests in entire repo

---

## 5. What Should Be Removed or Simplified

### DELETE
| File | Reason |
|---|---|
| /login.html (root) | Duplicate of niyam-frontend/ |
| /signup.html (root) | Duplicate |
| /dashboard.html (root) | Exact duplicate |
| /ocr_demo.html (root) | Duplicate |
| /config.js (root) | Duplicate |
| /simple_main.py | Dead prototype |
| /start_server.bat | Unused Windows script |
| /prompt.txt | 37KB blob, not used by code |

### SIMPLIFY
1. Break dashboard.html into separate CSS/JS files
2. Pick one auth strategy (Supabase Auth OR custom JWT, not both)
3. Add ENVIRONMENT flag, block MockDB in production
4. Remove or implement stub routes (don't ship {"message": "X API"})
5. Remove TrustedHostMiddleware no-op
6. Remove duplicate Chart.js import
7. Pick one deployment platform, remove others

---

## Summary Scorecard

| Area | Readiness |
|---|---|
| Auth | 85% |
| Frontend Shell | 70% |
| Database | 30% |
| GST Module | 5% |
| TDS Module | 2% |
| ROC Module | 2% |
| OCR | 0% |
| Rules Engine | 0% |
| ITC Matching | 0% |
| Testing | 0% |
| Deployment | 60% |
