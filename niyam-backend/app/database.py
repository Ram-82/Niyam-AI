try:
    from supabase import create_client, Client
except ImportError:
    class Client: pass
    create_client = None

from app.config import settings
import logging

logger = logging.getLogger(__name__)

class SupabaseClient:
    _instance: Client = None
    
    @classmethod
    def get_client(cls) -> Client:
        if cls._instance is None:
            try:
                if create_client:
                    cls._instance = create_client(
                        settings.SUPABASE_URL,
                        settings.SUPABASE_KEY
                    )
                    logger.info("Supabase client initialized successfully")
                else:
                    logger.warning("Supabase package not installed.")
                    cls._instance = None
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                # Don't raise, just set instance to None or a dummy
                cls._instance = None
        return cls._instance

    @classmethod
    def get_admin_client(cls) -> Client:
        """Get client with service role key for admin operations"""
        try:
            if not create_client:
                return None
            return create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_ROLE_KEY
            )
        except Exception as e:
            logger.error(f"Failed to initialize Supabase admin client: {e}")
            raise

# Create a singleton instance
supabase = SupabaseClient().get_client()
supabase_admin = SupabaseClient.get_admin_client()

def test_connection():
    """Test database connection"""
    try:
        response = supabase.table('users').select("*").limit(1).execute()
        logger.info("Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False
