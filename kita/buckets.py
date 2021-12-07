from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import Any, Dict, Optional

from hikari.events.interaction_events import InteractionCreateEvent
from hikari.snowflakes import Snowflakeish

from kita.typedefs import HashGetter

EXPIRE_AFTER = 30.0

__all__ = ("Bucket", "BucketManager")
_LOGGER = logging.getLogger("kita.buckets")


class EmptyBucketError(Exception):
    def __init__(self, *args: Any, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(*args)


class Bucket:
    __slots__ = ("manager", "tokens", "reset_at", "hash")

    def __init__(self, manager: BucketManager, hash_: Snowflakeish) -> None:
        self.manager: BucketManager = manager
        self.tokens: int = 0
        self.reset_at: float = 0.0
        self.hash = hash_

    @property
    def limit(self) -> int:
        return self.manager.limit

    @property
    def period(self) -> float:
        return self.manager.period

    def consume_token(self) -> None:
        self.tokens -= 1

    def acquire(self) -> None:
        if self.is_exhausted:
            raise EmptyBucketError(
                "you run out of tokens.", retry_after=self.next_window
            )

        self.consume_token()
        return None

    @property
    def is_exhausted(self) -> bool:
        if self.reset_at > (now := monotonic()):
            return self.tokens <= 0

        self.reset_at = now + self.period
        self.tokens = self.limit
        return False

    @property
    def next_window(self) -> float:
        return self.reset_at - monotonic()

    @property
    def is_inactive(self) -> bool:
        return self.reset_at + EXPIRE_AFTER < monotonic()

    def invalidate(self) -> None:
        del self.manager.buckets[self.hash]


class BucketManager:
    __slots__ = ("buckets", "hash_getter", "period", "limit", "gc_task")

    def __init__(self, hash_getter: HashGetter, limit: int, period: float):
        self.buckets: Dict[Snowflakeish, Bucket] = {}
        self.hash_getter = hash_getter
        self.limit = limit
        self.period = period
        self.gc_task: Optional[asyncio.Task[None]] = None

    def get_bucket(self, event: InteractionCreateEvent) -> Bucket:
        bucket_hash = self.hash_getter(event)
        if not (bucket := self.buckets.get(bucket_hash)):
            self.buckets[bucket_hash] = bucket = Bucket(self, bucket_hash)

        self.ensure_gc_task()
        return bucket

    def ensure_gc_task(self) -> None:
        if self.is_running:
            return

        self.gc_task = asyncio.create_task(self._do_gc())

    def close(self) -> None:
        if not self.is_running:
            return

        assert self.gc_task is not None
        self.gc_task.cancel()
        self.gc_task = None

    async def _do_gc(self) -> None:
        while 1:
            if not self.buckets:
                # if there's no bucket yet or all the buckets have been dead
                # the task shall stop.
                _LOGGER.debug("no buckets were found, stopping the task...")
                self.close()
                return

            dead_buckets = [
                bucket for bucket in self.buckets.values() if bucket.is_inactive
            ]

            for bucket in dead_buckets:
                bucket.invalidate()

            _LOGGER.debug("%d buckets were invalidated", len(dead_buckets))

            # runs periodically every `EXPIRE_AFTER` seconds
            await asyncio.sleep(EXPIRE_AFTER)

    @property
    def is_running(self) -> bool:
        return self.gc_task is not None
