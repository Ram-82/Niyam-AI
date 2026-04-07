import os
import secrets
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Settings:
    # ---- Environment ----
    # Set ENVIRONMENT=production in your deployment platform.
    # Defaults to "development" which allows MockDB fallback.
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()

    # ---- Supabase (PostgreSQL) ----
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").strip().strip('"')
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "").strip().strip('"')

    # ---- JWT ----
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "").strip()
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours (was 7 days — reduced for security)

    # ---- CORS ----
    # Comma-separated list of allowed origins, e.g.:
    #   ALLOWED_ORIGINS=https://niyam.ai,https://app.niyam.ai
    # Defaults to wildcard ("*") in development only; production should always set this.
    _allowed_origins_raw: str = os.getenv("ALLOWED_ORIGINS", "").strip()
    ALLOWED_ORIGINS: list = (
        [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]
        if _allowed_origins_raw
        else ["*"]
    )

    # ---- File Upload ----
    MAX_UPLOAD_SIZE: int = 15 * 1024 * 1024  # 15MB
    ALLOWED_FILE_TYPES: list = [".pdf", ".jpg", ".jpeg", ".png"]

    # ---- OCR ----
    TESSERACT_PATH: str = os.getenv("TESSERACT_PATH", "/usr/bin/tesseract")
    OCR_TIMEOUT: int = int(os.getenv("OCR_TIMEOUT", "30"))  # seconds

    # ---- AI Extraction (optional — fallback when parser confidence is low) ----
    # Set ANTHROPIC_API_KEY to enable AI-assisted extraction for messy invoices.
    # If not set, the system falls back to rule-based parser only.
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "").strip()

    # ---- Email (Resend) ----
    # Set RESEND_API_KEY to send real verification/welcome emails.
    # If not set, emails are skipped (dev mode shows codes in API response).
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "").strip()
    SENDER_EMAIL: str = os.getenv("SENDER_EMAIL", "noreply@niyam.ai")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")

    # ---- Storage ----
    # Supabase Storage bucket for uploaded documents (production).
    # In dev mode, files are saved to the local uploads/ directory.
    SUPABASE_STORAGE_BUCKET: str = os.getenv("SUPABASE_STORAGE_BUCKET", "niyam-documents")
    STORAGE_RETENTION_DAYS: int = int(os.getenv("STORAGE_RETENTION_DAYS", "30"))

    # ---- Payments (Razorpay) ----
    # Set these to enable subscription billing. Both are required for webhook
    # signature verification. Get from: https://dashboard.razorpay.com → Settings → API Keys
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "").strip()
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()
    RAZORPAY_PLAN_ID: str = os.getenv("RAZORPAY_PLAN_ID", "").strip()  # Razorpay subscription plan ID

    # Plan pricing (paise). 99900 = ₹999
    PRO_PLAN_AMOUNT_PAISE: int = int(os.getenv("PRO_PLAN_AMOUNT_PAISE", "99900"))

    # ---- Validation ----
    def validate(self):
        """
        Fail fast if critical env vars are missing.
        In development, we allow defaults. In production, we enforce real values.
        """
        errors = []

        if not self.JWT_SECRET_KEY:
            if self.ENVIRONMENT == "production":
                errors.append("JWT_SECRET_KEY is required in production")
            else:
                self.JWT_SECRET_KEY = secrets.token_urlsafe(32)
                logger.warning("JWT_SECRET_KEY not set — generated ephemeral dev secret.")
        elif len(self.JWT_SECRET_KEY) < 32:
            if self.ENVIRONMENT == "production":
                errors.append("JWT_SECRET_KEY must be at least 32 characters in production")
            else:
                logger.warning(f"JWT_SECRET_KEY is weak ({len(self.JWT_SECRET_KEY)} chars) — use at least 32 random chars.")

        if self.ENVIRONMENT == "production":
            if not self.SUPABASE_URL:
                errors.append("SUPABASE_URL is required in production")
            if not self.SUPABASE_KEY:
                errors.append("SUPABASE_KEY is required in production")
            if self.ALLOWED_ORIGINS == ["*"]:
                errors.append(
                    "ALLOWED_ORIGINS must be set to explicit origin(s) in production — "
                    "wildcard '*' is not permitted. Set ALLOWED_ORIGINS=https://yourdomain.com"
                )
            if self.RAZORPAY_KEY_ID.startswith("rzp_test_"):
                logger.warning("RAZORPAY_KEY_ID looks like a TEST key — ensure live keys are used in production.")

        if errors:
            for err in errors:
                logger.critical(f"CONFIG ERROR: {err}")
            print(f"\n{'='*60}", file=sys.stderr)
            print("FATAL: Missing required environment variables:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            print(f"{'='*60}\n", file=sys.stderr)
            sys.exit(1)

        logger.info(f"Environment: {self.ENVIRONMENT}")


settings = Settings()
settings.validate()
