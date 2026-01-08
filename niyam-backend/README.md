# Niyam AI Compliance OS - Backend

Backend API for Indian MSME Compliance Management System.

## Features
- FastAPI with automatic OpenAPI documentation
- Supabase integration (Auth + Database)
- JWT-based authentication
- GST/TDS/ROC compliance tracking
- Invoice OCR processing placeholder
- Deadline management
- Analytics and reporting

## Quick Start

### 1. Set up environment variables
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the application
```bash
uvicorn app.main:app --reload
```

### 4. Access the API
- API: http://localhost:8001
- Documentation: http://localhost:8001/api/docs
- Health check: http://localhost:8001/health

## Project Structure

```
niyam-backend/
├── app/
│   ├── main.py              # App entry point
│   ├── config.py            # Configuration
│   ├── database.py          # Database connection
│   ├── models/              # Pydantic models
│   ├── routes/              # API routes/controllers
│   ├── services/            # Business logic
│   └── utils/               # Helper functions
├── requirements.txt         # Dependencies
└── .env.example            # Environment template
```

## API Endpoints

### Authentication
- `POST /api/auth/signup` - Register new user
- `POST /api/auth/login` - User login
- `GET /api/auth/me` - Get current user
- `POST /api/auth/logout` - Logout

### Dashboard
- `GET /api/dashboard/summary` - Dashboard metrics

### GST
- `GET /api/gst/filings` - Get GST filings

## Database Setup

1. Create a Supabase project at https://supabase.com
2. Update `.env` with your Supabase credentials
