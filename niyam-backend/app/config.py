import os
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
    ALLOWED_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "https://niyam-ai-zncb.vercel.app",
    ]

    # ---- File Upload ----
    MAX_UPLOAD_SIZE: int = 15 * 1024 * 1024  # 15MB
    ALLOWED_FILE_TYPES: list = [".pdf", ".jpg", ".jpeg", ".png"]

    # ---- OCR ----
    TESSERACT_PATH: str = os.getenv("TESSERACT_PATH", "/usr/bin/tesseract")
    OCR_TIMEOUT: int = int(os.getenv("OCR_TIMEOUT", "30"))  # seconds

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
                self.JWT_SECRET_KEY = "dev-secret-key-not-for-production"
                logger.warning("JWT_SECRET_KEY not set — using insecure dev default.")

        if self.ENVIRONMENT == "production":
            if not self.SUPABASE_URL:
                errors.append("SUPABASE_URL is required in production")
            if not self.SUPABASE_KEY:
                errors.append("SUPABASE_KEY is required in production")

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
