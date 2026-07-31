from __future__ import annotations

import sqlalchemy as sa

JOB_SOURCE_TABLE = sa.table(
    "job_source",
    sa.column("id", sa.String),
    sa.column("display_name", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

__all__ = ["JOB_SOURCE_TABLE"]
