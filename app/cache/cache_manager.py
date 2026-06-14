import hashlib
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from app.core.config import settings
from app.core.logger import logger
import redis


class CacheManager:
    """Manage caching of prompts and responses"""

    def __init__(self):
        """Initialize cache manager"""
        self.cache_type = settings.CACHE_TYPE
        self.ttl = settings.CACHE_TTL

        if self.cache_type == "redis":
            try:
                self.redis_client = redis.from_url(settings.REDIS_URL)
                self.redis_client.ping()
                logger.info("Connected to Redis cache")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}. Using in-memory cache")
                self.memory_cache = {}
        else:
            self.memory_cache = {}

    def generate_cache_key(self, prompt: str, model: str) -> str:
        """Generate cache key from prompt and model"""
        combined = f"{prompt}:{model}"
        return hashlib.sha256(combined.encode()).hexdigest()

    def get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached response"""
        try:
            if self.cache_type == "redis":
                cached = self.redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit for key: {cache_key}")
                    return json.loads(cached)
            else:
                if cache_key in self.memory_cache:
                    entry = self.memory_cache[cache_key]
                    if entry["expires_at"] > datetime.utcnow():
                        logger.info(f"Cache hit for key: {cache_key}")
                        return entry["data"]
                    else:
                        del self.memory_cache[cache_key]

            logger.debug(f"Cache miss for key: {cache_key}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving from cache: {e}")
            return None

    def set(
        self, cache_key: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """Set cached response"""
        try:
            ttl = ttl or self.ttl

            if self.cache_type == "redis":
                self.redis_client.setex(
                    cache_key, ttl, json.dumps(data, default=str)
                )
            else:
                self.memory_cache[cache_key] = {
                    "data": data,
                    "expires_at": datetime.utcnow() + timedelta(seconds=ttl),
                }

            logger.info(f"Cached response with key: {cache_key}")
            return True
        except Exception as e:
            logger.error(f"Error setting cache: {e}")
            return False

    def delete(self, cache_key: str) -> bool:
        """Delete cached response"""
        try:
            if self.cache_type == "redis":
                self.redis_client.delete(cache_key)
            else:
                if cache_key in self.memory_cache:
                    del self.memory_cache[cache_key]

            logger.info(f"Deleted cache for key: {cache_key}")
            return True
        except Exception as e:
            logger.error(f"Error deleting from cache: {e}")
            return False

    def clear(self) -> bool:
        """Clear all cache"""
        try:
            if self.cache_type == "redis":
                self.redis_client.flushdb()
            else:
                self.memory_cache.clear()

            logger.info("Cleared all cache")
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False
