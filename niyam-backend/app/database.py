"""
Supabase PostgreSQL client — used as a standard database only.
No Supabase Auth is used; authentication is handled by custom JWT.
"""

try:
    from supabase import create_client, Client
except ImportError:
    Client = None
    create_client = None

from app.config import settings
import logging

logger = logging.getLogger(__name__)

_client_instance = None


def get_db_client():
    """
    Get or create a Supabase client singleton.
    Returns None if Supabase is not configured (dev mode uses MockDB instead).
    """
    global _client_instance

    if _client_instance is not None:
        return _client_instance

    if not create_client:
        logger.warning("supabase package not installed — cannot connect to database.")
        return None

    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        logger.warning("SUPABASE_URL or SUPABASE_KEY not set — database unavailable.")
        return None

    try:
        _client_instance = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        logger.info(f"Supabase client initialized for {settings.SUPABASE_URL}")
        return _client_instance
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        return None


def test_connection() -> bool:
    """Test database connection."""
    client = get_db_client()
    if not client:
        return False
    try:
        client.table("users").select("id").limit(1).execute()
        logger.info("Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False
