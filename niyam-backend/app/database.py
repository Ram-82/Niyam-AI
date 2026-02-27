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
                if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
                    logger.error("SUPABASE_URL or SUPABASE_KEY is missing in configuration")
                    return None

                if create_client:
                    # Log masked key for verification in Render logs
                    masked_key = f"{settings.SUPABASE_KEY[:5]}...{settings.SUPABASE_KEY[-5:]}" if len(settings.SUPABASE_KEY) > 10 else "***"
                    logger.info(f"Initializing Supabase client with URL: {settings.SUPABASE_URL} and Key: {masked_key}")
                    
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
                cls._instance = None
        return cls._instance

    @classmethod
    def get_admin_client(cls) -> Client:
        """Get client with service role key for admin operations"""
        try:
            if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
                logger.error("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing in configuration")
                return None
            
            if not create_client:
                return None
                
            masked_key = f"{settings.SUPABASE_SERVICE_ROLE_KEY[:5]}...{settings.SUPABASE_SERVICE_ROLE_KEY[-5:]}" if len(settings.SUPABASE_SERVICE_ROLE_KEY) > 10 else "***"
            logger.info(f"Initializing Supabase Admin client with Key: {masked_key}")
            
            return create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_ROLE_KEY
            )
        except Exception as e:
            logger.error(f"Failed to initialize Supabase admin client: {e}")
            return None # Returning None instead of raising to allow fallback to MockDB

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
