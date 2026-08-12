"""Regel-engine (ontwerp 2, docs/architectuur.md).

Een regel is een JSON-boom: combinatoren ``and``/``or``/``not`` met condities
op velden als ``extension`` of ``origin_region``. Die boom wordt hier
gecompileerd naar een SQLAlchemy-expressie — geen ``eval``, geen
stringinterpolatie — die direct in een ``select(Series).where(...)`` past.
Tabs en slimme collecties delen deze ene engine.

Voorbeeld — "strips uit Europa":
    {"and": [{"extension": {"in": ["cbz", "cbr"]}}, {"origin_region": {"eq": "europe"}}]}
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, false, func, not_, or_, select, true

from bookpal.models import Book, File, Progress, Series, User

FieldHandler = Callable[[str, Any, User], "ColumnElement[bool]"]


class RuleError(ValueError):
    """Een regel is geen geldige boom, of gebruikt een onbekend veld/operator."""


def compile_rule(rule: dict[str, Any] | None, *, user: User) -> ColumnElement[bool]:
    """Een regelboom (leeg = alles) naar een boolean SQL-expressie op ``Series``."""
    if not rule:
        return true()
    return _compile_node(rule, user)


def _compile_node(node: Any, user: User) -> ColumnElement[bool]:
    if not isinstance(node, dict) or len(node) != 1:
        raise RuleError(f"ongeldig regelknooppunt: {node!r}")
    ((key, value),) = node.items()

    if key == "and":
        _require_list(value, "and")
        return and_(*(_compile_node(child, user) for child in value)) if value else true()
    if key == "or":
        _require_list(value, "or")
        return or_(*(_compile_node(child, user) for child in value)) if value else false()
    if key == "not":
        return not_(_compile_node(value, user))

    handler = _FIELD_HANDLERS.get(key)
    if handler is None:
        raise RuleError(f"onbekend veld: {key}")
    if not isinstance(value, dict) or len(value) != 1:
        raise RuleError(f"ongeldige conditie voor '{key}': {value!r}")
    ((op, operand),) = value.items()
    return handler(op, operand, user)


def _require_list(value: Any, key: str) -> None:
    if not isinstance(value, list):
        raise RuleError(f"'{key}' verwacht een lijst van regels")


def _scalar(column: Any, *, allow_contains: bool = False) -> FieldHandler:
    def handler(op: str, value: Any, _user: User) -> ColumnElement[bool]:
        if op == "eq":
            return column == value  # type: ignore[no-any-return]
        if op == "ne":
            return column != value  # type: ignore[no-any-return]
        if op == "in":
            _require_list(value, "in")
            return column.in_(value)  # type: ignore[no-any-return]
        if op == "not_in":
            _require_list(value, "not_in")
            return column.not_in(value)  # type: ignore[no-any-return]
        if allow_contains and op == "contains":
            return column.ilike(f"%{value}%")  # type: ignore[no-any-return]
        raise RuleError(f"onbekende operator '{op}' voor dit veld")

    return handler


def _normalize_extension(value: str) -> str:
    return value if value.startswith(".") else f".{value}"


def _extension(op: str, value: Any, _user: User) -> ColumnElement[bool]:
    if op == "eq":
        values = [_normalize_extension(value)]
    elif op == "in":
        _require_list(value, "in")
        values = [_normalize_extension(v) for v in value]
    else:
        raise RuleError(f"onbekende operator '{op}' voor extension")
    return Series.books.any(Book.file.has(File.extension.in_(values)))


def _kind(op: str, value: Any, _user: User) -> ColumnElement[bool]:
    if op == "eq":
        return Series.books.any(Book.kind == value)
    if op == "in":
        _require_list(value, "in")
        return Series.books.any(Book.kind.in_(value))
    raise RuleError(f"onbekende operator '{op}' voor kind")


def _tag(op: str, value: Any, _user: User) -> ColumnElement[bool]:
    if op == "eq":
        values = [value]
    elif op == "in":
        _require_list(value, "in")
        values = value
    else:
        raise RuleError(f"onbekende operator '{op}' voor tag")
    # SQLite json1: het gedocumenteerde idioom om een JSON-array als tabel te
    # bevragen, gecorreleerd aan de buitenste Series-rij.
    each = func.json_each(Series.tags).table_valued("value")
    return exists(select(1).select_from(each).where(each.c.value.in_(values)))


def _source(op: str, value: Any, _user: User) -> ColumnElement[bool]:
    if op != "eq":
        raise RuleError("source ondersteunt alleen 'eq'")
    if value == "local":
        return Series.books.any(Book.file_id.isnot(None))
    if value == "remote":
        return Series.books.any(Book.source_id.isnot(None))
    raise RuleError(f"onbekende source: {value}")


def _reading_status(op: str, value: Any, user: User) -> ColumnElement[bool]:
    if op != "eq":
        raise RuleError("reading_status ondersteunt alleen 'eq'")
    if value not in ("unread", "reading", "finished"):
        raise RuleError(f"onbekende reading_status: {value}")

    # "voor elk boek met bestand bestaat een voltooide leespositie" — als
    # dubbele ontkenning, want de ORM kent geen relationship.all().
    has_unfinished_book = exists(
        select(1)
        .select_from(Book)
        .where(
            Book.series_id == Series.id,
            Book.file_id.isnot(None),
            ~exists(
                select(1)
                .select_from(Progress)
                .where(
                    Progress.book_id == Book.id,
                    Progress.user_id == user.id,
                    Progress.finished.is_(True),
                )
            ),
        )
    )
    has_any_progress = exists(
        select(1)
        .select_from(Progress)
        .join(Book, Progress.book_id == Book.id)
        .where(Book.series_id == Series.id, Progress.user_id == user.id)
    )

    if value == "finished":
        has_a_file = Series.books.any(Book.file_id.isnot(None))
        return and_(has_a_file, not_(has_unfinished_book))
    if value == "unread":
        return not_(has_any_progress)
    return and_(has_any_progress, has_unfinished_book)  # "reading"


_FIELD_HANDLERS: dict[str, FieldHandler] = {
    "origin_region": _scalar(Series.origin_region),
    "root": _scalar(Series.library_root_id),
    "series": _scalar(Series.id),
    "publisher": _scalar(Series.publisher, allow_contains=True),
    "kind": _kind,
    "extension": _extension,
    "tag": _tag,
    "source": _source,
    "reading_status": _reading_status,
}
