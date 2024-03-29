"""Inspired by RoboDanny's db.py."""

from __future__ import annotations

import json
import typing

import asyncpg

from nokari.core.constants import POSTGRESQL_DSN

__all__: typing.Final[typing.List[str]] = [
    "Column",
    "PrimaryKeyColumn",
    "Table",
    "create_pool",
    "create_tables",
]
T = typing.TypeVar("T")


class Column(typing.Generic[T]):
    # more to add as I need it
    typing_map: typing.Dict[str, str] = {
        "Snowflake": "BIGINT",
        "str": "TEXT",
        "datetime": "TIMESTAMP WITH TIME ZONE",
        "dict": "JSONB",
    }
    primary_key: typing.ClassVar[bool] = False

    def __init__(self, data_type: T | str):
        is_list = getattr(data_type, "__origin__", None) is list
        if is_list:
            data_type = getattr(data_type, "__args__")[0]

        stringified = self._get_data_type(data_type)
        self.type = f"{self.typing_map.get(stringified, stringified)}{'[]'*is_list}"

    @staticmethod
    def _get_data_type(data_type: T | str, /) -> str:
        return (
            str(data_type).replace("<class '", "").replace("'>", "").rsplit(".", 1)[-1]
        )

    def __class_getitem__(cls, item: T) -> Column[T]:
        return cls(data_type=item)  # pylint: disable=not-callable

    def __str__(self) -> str:
        return self.type


class PrimaryKeyColumn(Column, typing.Generic[T]):
    primary_key: typing.ClassVar[bool] = True


class Table:
    name: typing.ClassVar[str]
    columns: typing.ClassVar[typing.Dict[str, Column]]
    primary_keys: typing.ClassVar[typing.Sequence[str]]

    def __init_subclass__(cls, name: str | None = None) -> None:
        cls.name = name or cls.__name__.lower()
        cls.columns = columns = {
            k: v for k, v in cls.__annotations__.items() if isinstance(v, Column)
        }
        cls.primary_keys = cls.primary_keys = [
            k for k, v in columns.items() if v.primary_key
        ]

    @classmethod
    def get_all_tables(cls) -> typing.List[typing.Type[Table]]:
        return cls.__subclasses__()

    @classmethod
    def get_query(cls, if_not_exists: bool = True) -> str:
        queries = ["CREATE TABLE"]

        if if_not_exists:
            queries.append("IF NOT EXISTS")

        queries.append(cls.name)

        has_multiple_primary_keys = len(cls.primary_keys) > 1

        columns = ", ".join(
            f"{name} {column}"
            f"{' PRIMARY KEY'*(not has_multiple_primary_keys and name in cls.primary_keys)}"
            for name, column in cls.columns.items()
        )

        if has_multiple_primary_keys:
            columns += f", PRIMARY KEY ({', '.join(cls.primary_keys)})"

        return f"{' '.join(queries)} ({columns});"


def create_tables(
    con: asyncpg.Connection | asyncpg.Pool, if_not_exists: bool = True
) -> typing.Coroutine[typing.Any, typing.Any, str]:
    statements = []

    for table in Table.get_all_tables():
        statements.append(table.get_query(if_not_exists=if_not_exists))

    return con.execute(" ".join(statements))


async def create_pool(
    min_size: int = 3, max_size: int = 10, max_inactive_connection_lifetime: int = 60
) -> asyncpg.Pool | None:
    if not POSTGRESQL_DSN:
        return None

    def _encode_jsonb(value: dict) -> str:
        return json.dumps(value)

    def _decode_jsonb(value: str) -> dict:
        return json.loads(value)

    async def init(con: asyncpg.Connection) -> None:
        await con.set_type_codec(
            "jsonb",
            schema="pg_catalog",
            encoder=_encode_jsonb,
            decoder=_decode_jsonb,
            format="text",
        )

    return await asyncpg.create_pool(
        dsn=POSTGRESQL_DSN,
        init=init,
        min_size=min_size,
        max_size=max_size,
        max_inactive_connection_lifetime=max_inactive_connection_lifetime,
    )
