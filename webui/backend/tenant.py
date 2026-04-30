"""Multi-tenant scaffolding.

Section 2.5 P3 of docs/improvements.md.

Today the backend serves a single school. To prepare for multi-tenant
deployments (multi-school SaaS, plessi consortia) we:

  1. Define a `TenantMixin` that adds a `tenant_id` column with a
     default of 1 (the singleton tenant). Mixed into the user-facing
     entities so every row carries its tenant.
  2. Provide a request-scoped `current_tenant_id()` getter that reads
     `X-Tenant-Id` header (or env default) so future routers can
     filter by tenant transparently.
  3. The actual filtering / cross-tenant isolation is NOT yet
     enforced -- routers continue to query without a tenant filter
     until a real multi-tenant deployment requires it. This commit
     is purely scaffolding.

Backwards compat: single-tenant DBs default everything to tenant_id=1.
The lightweight migration in db.py adds the column and back-fills.
"""
from __future__ import annotations

import os

from fastapi import Header
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column


DEFAULT_TENANT_ID = int(os.environ.get("PITANTUM_DEFAULT_TENANT_ID", "1"))


class TenantMixin:
    """Adds `tenant_id INTEGER NOT NULL DEFAULT 1, indexed`.

    Mixed into top-level user-facing entities (Subject, Teacher,
    SchoolClass, Classroom, Curriculum, Student, StudyGroup). Junction
    tables inherit the tenant via FK.
    """
    tenant_id: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_TENANT_ID, nullable=False, index=True,
        server_default=str(DEFAULT_TENANT_ID),
        comment="Section 2.5 P3 -- multi-tenant scaffolding",
    )


def current_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> int:
    """FastAPI dependency: returns the tenant id for this request.

    - Reads the `X-Tenant-Id` header if present.
    - Falls back to the env-configured default (default: 1).
    - Routers can `Depends(current_tenant_id)` and filter their
      queries by `Model.tenant_id == tid`.

    The header is intentionally trusted with no auth in this scaffolding
    pass: the API-key middleware (B13) is the gatekeeper. Real
    multi-tenant deployments would derive tenant from the
    authenticated user, NOT from a header.
    """
    if x_tenant_id is None or not x_tenant_id.strip():
        return DEFAULT_TENANT_ID
    try:
        return int(x_tenant_id)
    except ValueError:
        return DEFAULT_TENANT_ID
