from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union, cast

from hikari.events.interaction_events import InteractionCreateEvent

from kita.typedefs import BucketHash, HashGetter, LimitGetter, PeriodGetter

if TYPE_CHECKING:
    from kita.command_handlers import GatewayCommandHandler

EXPIRE_AFTER = 30.0

__all__ = ("Bucket", "BucketManager")
_LOGGER = logging.getLogger("kita.buckets")


class EmptyBucketError(Exception):
    def __init__(self, *args: Any, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(*args)


class Bucket:
    __slots__ = ("manager", "tokens", "reset_at", "hash", "limit", "period")

    def __init__(self, manager: BucketManager, hash_: BucketHash) -> None:
        self.manager: BucketManager = manager
        self.tokens: int = 0
        self.reset_at: float = 0.0
        self.hash = hash_
        self.limit: int
        self.period: float

    def set_constraints(
        self, limit: Optional[int] = None, period: Optional[float] = None
    ) -> None:
        if limit is not None:
            self.limit = limit

        if period is not None:
            self.period = period

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
    def is_expired(self) -> bool:
        return self.reset_at + EXPIRE_AFTER < monotonic()

    def invalidate(self) -> None:
        del self.manager.buckets[self.hash]

    def __repr__(self) -> str:
        return (
            f"<Bucket manager={self.manager.name!r} "
            f"limit={self.limit} period={self.period} "
            f"tokens={self.tokens} next_window={self.next_window}>"
        )


class BucketManager:
    __slots__ = ("name", "buckets", "hash_getter", "period", "limit", "gc_task")

    def __init__(
        self,
        name: str,
        hash_getter: HashGetter,
        limit: Union[LimitGetter, int],
        period: Union[PeriodGetter, float],
    ):
        self.name = name
        self.buckets: Dict[BucketHash, Bucket] = {}
        self.hash_getter = hash_getter
        self.limit = limit
        self.period = period
        self.gc_task: Optional[asyncio.Task[None]] = None

    async def get_limit(self, handler: GatewayCommandHandler, hash_: BucketHash) -> int:
        return (
            await handler._invoke_callback(self.limit, hash_)
            if callable(self.limit)
            else self.limit
        )

    async def get_period(
        self, handler: GatewayCommandHandler, hash_: BucketHash
    ) -> float:
        return (
            await handler._invoke_callback(self.period, hash_)
            if callable(self.period)
            else self.period
        )

    async def get_or_create_bucket(
        self, handler: GatewayCommandHandler, event: InteractionCreateEvent
    ) -> Bucket:
        bucket_hash = await handler._invoke_callback(self.hash_getter, event)
        if not (bucket := self.buckets.get(bucket_hash)):
            self.buckets[bucket_hash] = bucket = Bucket(self, bucket_hash)

            bucket.set_constraints(
                await self.get_limit(handler, bucket_hash),
                await self.get_period(handler, bucket_hash),
            )

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
        _LOGGER.debug("started running gc (%s bucket manager)", self.name)
        while 1:
            # runs periodically every `EXPIRE_AFTER` seconds
            await asyncio.sleep(EXPIRE_AFTER)

            if not self.buckets:
                # if there's no bucket yet or all the buckets have been dead
                # the task shall stop.
                _LOGGER.debug(
                    "no buckets were found, stopping the task... (%s bucket manager)",
                    self.name,
                )
                self.close()
                return

            dead_buckets = [
                bucket for bucket in self.buckets.values() if bucket.is_expired
            ]

            for bucket in dead_buckets:
                bucket.invalidate()

            _LOGGER.debug(
                "%d buckets were invalidated (%s bucket manager)",
                len(dead_buckets),
                self.name,
            )

    @property
    def is_running(self) -> bool:
        return self.gc_task is not None
