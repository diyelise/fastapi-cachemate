import logging
import uuid

from redis import exceptions as redis_exceptions

from fastapi_cachemate import MAX_LOCK_TTL_SECONDS
from fastapi_cachemate.core.backends.redis import RedisBackend
from fastapi_cachemate.core.types import LockManager

logger = logging.getLogger(__name__)


class RedisLockManager(LockManager):
    UNLOCK_SCRIPT = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

    def __init__(
        self,
        backend: RedisBackend,
        lock_ttl: int | None = None,
    ):
        self._backend = backend
        self._lock_ttl = lock_ttl or MAX_LOCK_TTL_SECONDS
        self._lock_token = str(uuid.uuid4())

    async def acquire(self, lock_key: str) -> bool:
        try:
            is_lock = await self._backend.set(lock_key, self._lock_token, ttl=self._lock_ttl, nx=True)
        except redis_exceptions.RedisError as e:
            logger.error("RedisLockManagerError", extra={"lock_key": lock_key, "error": str(e)})
            return False
        except Exception as e:
            logger.error(
                "RedisLockManagerUnexpectedError",
                extra={"lock_key": lock_key, "error": str(e)},
                exc_info=True,
            )
            return False
        if not is_lock:
            return False
        return True

    async def release(self, lock_key: str) -> bool:
        try:
            redis_client = self._backend.client
            released = await redis_client.eval(self.UNLOCK_SCRIPT, 1, lock_key, self._lock_token)
        except redis_exceptions.RedisError as e:
            logger.error("RedisUnLockManagerError", extra={"lock_key": lock_key, "error": str(e)}, exc_info=True)
            return False
        except Exception as e:
            logger.error(
                "RedisUnLockManagerUnexpectedError",
                extra={"lock_key": lock_key, "error": str(e)},
                exc_info=True,
            )
            return False

        if released == 1:
            logger.info("Release lock successfully", extra={"lock_key": lock_key})
            return True
        logger.warning("Lock was not released", extra={"lock_key": lock_key})
        return False
