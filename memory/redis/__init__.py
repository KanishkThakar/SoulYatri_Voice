"""memory/redis/ — L2 hot session cache (final_use.md §4, Phase 12A).

Owner: memory agent. Fast, bounded session memory in Redis. Already provisioned in
docker-compose.yml.
"""

from memory.redis.hot_cache import HotCache, RedisHotCache

__all__ = ["HotCache", "RedisHotCache"]
