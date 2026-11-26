"""Compare PostgreSQL, migrations, documented DDL and the full ER diagram."""

import importlib.util
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

from app import models  # noqa: F401
from app.database import Base, get_engine

ROOT = Path(__file__).resolve().parents[1]
DIAGRAM = ROOT / "docs/database.mmd"
APPLICATION_MINIMUMS = {
    ("invoices", "order_id"),
    ("ticket_messages", "ticket_id"),
}
LEFT_CARDS = {
    "||": (1, 1),
    "|o": (0, 1),
    "}o": (0, "N"),
    "}|": (1, "N"),
}
RIGHT_CARDS = {
    "||": (1, 1),
    "o|": (0, 1),
    "o{": (0, "N"),
    "|{": (1, "N"),
}


def type_name(column):
    value = str(column.type.compile(dialect=postgresql.dialect()))
    return (
        value.replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ")
        .replace(", ", ",")
        .lower()
    )


def signature(table):
    return {
        "columns": {
            col.name: (type_name(col), col.nullable) for col in table.columns
        },
        "pk": tuple(col.name for col in table.primary_key.columns),
        "fk": sorted(
            (fk.parent.name, fk.target_fullname, fk.ondelete)
            for fk in table.foreign_keys
        ),
        "unique": sorted(
            tuple(col.name for col in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        ),
        "checks": sorted(
            (constraint.name, " ".join(str(constraint.sqltext).split()))
            for constraint in table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        ),
        "indexes": sorted(
            (
                index.name,
                tuple(col.name for col in index.columns),
                bool(index.unique),
                str(index.dialect_options["postgresql"].get("where")),
            )
            for index in table.indexes
        ),
    }


def migration_metadata():
    metadata = sa.MetaData()

    def create_table(name, *items, **kwargs):
        return sa.Table(name, metadata, *items, **kwargs)

    def create_index(name, table_name, columns, **kwargs):
        return sa.Index(
            name,
            *(metadata.tables[table_name].c[name] for name in columns),
            **kwargs,
        )

    def drop_constraint(name, table_name, **kwargs):
        table = metadata.tables[table_name]
        constraint = next(c for c in table.constraints if c.name == name)
        table.constraints.remove(constraint)

    def drop_index(name, table_name):
        table = metadata.tables[table_name]
        table.indexes.remove(next(i for i in table.indexes if i.name == name))

    def alter_column(table_name, column_name, **kwargs):
        table = metadata.tables[table_name]
        column = table.c[column_name]
        if "new_column_name" in kwargs:
            table._columns.remove(column)
            column.name = column.key = kwargs["new_column_name"]
            table.append_column(column)
        if "nullable" in kwargs:
            column.nullable = kwargs["nullable"]

    def create_unique_constraint(name, table_name, columns):
        metadata.tables[table_name].append_constraint(
            sa.UniqueConstraint(*columns, name=name)
        )

    def create_foreign_key(name, source, target, local, remote, **kwargs):
        metadata.tables[source].append_constraint(
            sa.ForeignKeyConstraint(
                local,
                [f"{target}.{col}" for col in remote],
                name=name,
                **kwargs,
            )
        )

    operations = SimpleNamespace(
        create_table=create_table,
        create_index=create_index,
        drop_index=drop_index,
        drop_constraint=drop_constraint,
        alter_column=alter_column,
        create_unique_constraint=create_unique_constraint,
        create_foreign_key=create_foreign_key,
        execute=lambda statement: None,
        add_column=lambda name, column: metadata.tables[name].append_column(
            column
        ),
        create_check_constraint=lambda name, table, condition: metadata.tables[
            table
        ].append_constraint(sa.CheckConstraint(condition, name=name)),
        f=lambda name: name,
    )
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    for revision in reversed(list(scripts.walk_revisions())):
        spec = importlib.util.spec_from_file_location(
            f"schema_{revision.revision}", revision.path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.op = operations
        module.upgrade()
    return metadata


def audit_diagram():
    source = DIAGRAM.read_text(encoding="utf-8")
    blocks = dict(
        re.findall(r"^    ([A-Z_]+) \{\n(.*?)^    \}", source, re.M | re.S)
    )
    assert set(blocks) == {name.upper() for name in Base.metadata.tables}
    foreign_keys = {}
    column_count = 0
    for table in Base.metadata.sorted_tables:
        rows = [row.strip() for row in blocks[table.name.upper()].splitlines()]
        assert len(rows) == len(table.columns), table.name
        for column in table.columns:
            row = next(row for row in rows if row.split()[1] == column.name)
            assert row.split()[0] == type_name(column), row
            assert ("PK" in row) == column.primary_key, row
            assert ("FK" in row) == bool(column.foreign_keys), row
            assert ("UK" in row) == bool(column.unique), row
            assert ('"NULL"' in row) == column.nullable, row
            column_count += 1
            for fk in column.foreign_keys:
                foreign_keys[(table.name.upper(), column.name)] = fk

    verified = set()
    report = []
    pattern = r"^    (\w+) ([|o}{]{2})(--|\.\.)([|o}{]{2}) (\w+) : (\w+)$"
    for left, left_card, style, right_card, right, label in re.findall(
        pattern, source, re.M
    ):
        candidates = [
            (name, foreign_keys[(name, label)])
            for name in (left, right)
            if (name, label) in foreign_keys
        ]
        candidates = [
            (name, fk)
            for name, fk in candidates
            if {name, fk.column.table.name.upper()} == {left, right}
        ]
        assert len(candidates) == 1, (left, right, label)
        child, fk = candidates[0]
        assert (child, label) not in verified
        verified.add((child, label))
        cards = {left: LEFT_CARDS[left_card], right: RIGHT_CARDS[right_card]}
        parent = fk.column.table.name.upper()
        assert cards[parent] == (0 if fk.parent.nullable else 1, 1)
        minimum = int((child.lower(), label) in APPLICATION_MINIMUMS)
        maximum = 1 if fk.parent.unique else "N"
        assert cards[child] == (minimum, maximum), (child, label)
        assert style == "..", (child, label, "identifying relationship")
        report.append(
            {
                "fk": f"{child.lower()}.{label}",
                "references": fk.target_fullname,
                "parent_per_child": cards[parent],
                "children_per_parent": cards[child],
                "application_minimum": bool(minimum),
            }
        )
    assert verified == set(foreign_keys)
    return column_count, report


def normalize_sql(sql: str) -> str:
    # At a two-parent merge Alembic can delete either old version row and
    # update the other. Both operations consume exactly the same two heads.
    merge_stamp = (
        r"DELETE FROM alembic_version WHERE "
        r"alembic_version\.version_num = '([a-f0-9]+)'; "
        r"UPDATE alembic_version SET version_num='([a-f0-9]+)' "
        r"WHERE alembic_version\.version_num = '([a-f0-9]+)';"
    )

    def parents(match):
        left, head, right = match.groups()
        return "MERGE " + " ".join(sorted([left, right])) + " INTO " + head

    return re.sub(merge_stamp, parents, " ".join(sql.split()))


def main():
    migrated = migration_metadata()
    assert set(migrated.tables) == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        assert signature(table) == signature(migrated.tables[name]), name

    buffer = io.StringIO()
    command.upgrade(
        Config(str(ROOT / "alembic.ini"), output_buffer=buffer),
        "head",
        sql=True,
    )
    expected_sql = (ROOT / "docs/schema.sql").read_text(encoding="utf-8")
    assert normalize_sql(buffer.getvalue()) == normalize_sql(expected_sql)
    columns, relationships = audit_diagram()

    inspector = sa.inspect(get_engine())
    for table in Base.metadata.sorted_tables:
        actual_columns = {
            column["name"]: (
                type_name(SimpleNamespace(type=column["type"])),
                column["nullable"],
            )
            for column in inspector.get_columns(table.name)
        }
        assert actual_columns == signature(table)["columns"], table.name
        assert (
            tuple(
                inspector.get_pk_constraint(table.name)["constrained_columns"]
            )
            == signature(table)["pk"]
        ), table.name
        actual_unique = sorted(
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table.name)
        )
        assert actual_unique == signature(table)["unique"], table.name
        actual = {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                fk["options"].get("ondelete"),
            )
            for fk in inspector.get_foreign_keys(table.name)
        }
        expected = {
            (
                (fk.parent.name,),
                fk.column.table.name,
                (fk.column.name,),
                fk.ondelete,
            )
            for fk in table.foreign_keys
        }
        assert actual == expected, table.name
        actual_checks = {
            c["name"] for c in inspector.get_check_constraints(table.name)
        }
        expected_checks = {
            c.name
            for c in table.constraints
            if isinstance(c, sa.CheckConstraint)
        }
        assert actual_checks == expected_checks, table.name
        actual_indexes = {
            index["name"]: index
            for index in inspector.get_indexes(table.name)
            if not index.get("duplicates_constraint")
        }
        assert set(actual_indexes) == {
            index.name for index in table.indexes
        }, table.name
        for index in table.indexes:
            actual_index = actual_indexes[index.name]
            assert bool(actual_index["unique"]) == bool(index.unique)
            assert actual_index["column_names"] == [
                column.name for column in index.columns
            ]
            actual_where = actual_index.get("dialect_options", {}).get(
                "postgresql_where"
            )
            expected_where = index.dialect_options["postgresql"].get("where")

            def normalize_where(value):
                if value is None:
                    return None
                if re.search(r"\b(IN|ANY)\b", str(value), re.I):
                    column = re.search(r"[a-z_]+", str(value), re.I).group()
                    values = sorted(re.findall(r"'([^']*)'", str(value)))
                    return column.lower(), tuple(values)
                value = re.sub(r"::(?:text|character varying)", "", str(value))
                return re.sub(r"[\s()]", "", value).lower()

            assert normalize_where(actual_where) == normalize_where(
                expected_where
            ), index.name

    result = {
        "tables": len(Base.metadata.tables),
        "columns": columns,
        "foreign_keys": len(relationships),
        "models_vs_migration": "match",
        "migration_vs_documented_ddl": "match",
        "live_columns_keys_checks_and_indexes": "match",
        "diagram": "all keys, nullability and cardinalities match",
        "relationships": relationships,
    }
    output = ROOT / "outputs"
    output.mkdir(exist_ok=True)
    (output / "beta-schema-audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key != "relationships"
            }
        )
    )


if __name__ == "__main__":
    main()
