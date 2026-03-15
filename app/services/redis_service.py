import redis.asyncio as redis
from app.utils.config import REDIS_URL
from app.utils.logger import get_logger

logger = get_logger(__name__)

redis_client = None

async def init_redis():
    """Initialize a global async Redis client."""
    global redis_client
    logger.info("Initializing connection to Redis...")
    try:
        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True
        )
        await redis_client.ping()
        logger.info("Successfully connected to Redis.")
    except Exception as exc:
        logger.error("Failed to connect to Redis: %s", exc)
        redis_client = None

async def close_redis():
    """Close the global Redis client connection."""
    global redis_client
    if redis_client:
        logger.info("Closing Redis connection...")
        await redis_client.close()
        redis_client = None

async def get_cache(key: str) -> str | None:
    """Retrieve string value from Redis."""
    if not redis_client:
        return None
    try:
        return await redis_client.get(key)
    except Exception as exc:
        logger.error("Redis GET error for key %s: %s", key, exc)
        return None

async def set_cache(key: str, value: str, expire: int = 3600) -> None:
    """Set string value in Redis with standard expiration."""
    if not redis_client:
        return
    try:
        await redis_client.set(key, value, ex=expire)
    except Exception as exc:
        logger.error("Redis SET error for key %s: %s", key, exc)

async def get_redis_client() -> redis.Redis | None:
    """Return the raw redis client for advanced operations like locks."""
    return redis_client
