"""Keyset (cursor) pagination for list endpoints.

A page continues after the last row the client saw instead of skipping a
number of rows, so it stays fast deep into a list and rows never repeat or
disappear when new ones arrive between requests. The sort columns must end
with a unique column (the id) and are compared as one tuple.
"""

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query
from sqlalchemy import Select, literal, tuple_
from sqlalchemy.orm import Session

PAGE_SIZE = 50
# Polling reloads everything the client has loaded in one request.
MAX_PAGE_SIZE = 200


class Page:
    def __init__(
        self,
        limit: int = Query(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(None, max_length=512),
    ):
        self.limit = limit
        self.cursor = cursor


PageParams = Annotated[Page, Depends()]


def encode(values: Sequence[Any]) -> str:
    plain = [
        value.isoformat() if isinstance(value, datetime) else value
        for value in values
    ]
    return base64.urlsafe_b64encode(json.dumps(plain).encode()).decode()


def decode(cursor: str, columns: Sequence) -> list:
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not isinstance(values, list) or len(values) != len(columns):
            raise ValueError("cursor shape")
        result = []
        for value, column in zip(values, columns, strict=True):
            kind = column.type.python_type
            result.append(
                datetime.fromisoformat(value)
                if kind is datetime
                else kind(value)
            )
        return result
    except (ValueError, TypeError, binascii.Error) as error:
        raise HTTPException(422, "Invalid page cursor") from error


def paginate(
    db: Session,
    query: Select,
    columns: Sequence,
    page: Page,
    *,
    descending: bool,
    key: Callable[[Any], Sequence[Any]],
) -> dict:
    """One page of `query` sorted by `columns`; key(row) gives their values."""
    if page.cursor:
        values = decode(page.cursor, columns)
        position = tuple_(*columns)
        after = tuple_(
            *[
                literal(value, column.type)
                for value, column in zip(values, columns, strict=True)
            ]
        )
        query = query.where(
            position < after if descending else position > after
        )
    order = [
        column.desc() if descending else column.asc() for column in columns
    ]
    rows = db.execute(query.order_by(*order).limit(page.limit + 1)).all()
    more = len(rows) > page.limit
    rows = rows[: page.limit]
    return {
        "rows": rows,
        "next_cursor": encode(key(rows[-1])) if more else None,
    }
