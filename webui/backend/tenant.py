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

from fastapi import Header, HTTPException
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


DEFAULT_TENANT_ID = int(os.environ.get("PITANTUM_DEFAULT_TENANT_ID", "1"))


def _multi_tenant_enabled() -> bool:
    """Multi-tenant is OFF by default and must be explicitly enabled.

    Cross-tenant isolation is NOT actually enforced across the routers
    (only working_hours filters by tenant), and several output tables
    (Solution/Lesson/Assignment) have no tenant column at all, so a
    second tenant sharing the DB would corrupt the first
    (set_active_solution is global, unique names collide). Until that is
    fixed, the safe posture is single-tenant-only: we refuse to honour a
    client-supplied tenant that differs from the default rather than
    silently trusting a spoofable header. Set PITANTUM_MULTI_TENANT=1
    only once real per-tenant scoping lands.
    """
    return os.environ.get("PITANTUM_MULTI_TENANT", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


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

    Fail-closed: with multi-tenant disabled (the default), an
    `X-Tenant-Id` header that asks for anything other than the default
    tenant is REJECTED (400) instead of silently trusted. This closes
    the spoofable-header cross-tenant vector while the real per-tenant
    scoping is still missing. When PITANTUM_MULTI_TENANT is enabled the
    header is honoured (a real deployment must additionally derive/verify
    the tenant from the authenticated principal, not the raw header).
    """
    if x_tenant_id is None or not x_tenant_id.strip():
        return DEFAULT_TENANT_ID
    try:
        requested = int(x_tenant_id)
    except ValueError:
        return DEFAULT_TENANT_ID
    if not _multi_tenant_enabled() and requested != DEFAULT_TENANT_ID:
        raise HTTPException(
            status_code=400,
            detail={
                "detail": (
                    "Multi-tenant non abilitato: questo backend serve un "
                    "singolo istituto. Rimuovere l'header X-Tenant-Id."
                ),
                "code": "multi_tenant_disabled",
            },
        )
    return requested


class SingleTenantGuardMiddleware(BaseHTTPMiddleware):
    """Universally reject cross-tenant requests while multi-tenant is off.

    `current_tenant_id` only guards routes that actually `Depends` on it
    -- and today almost none do, so a spoofed `X-Tenant-Id` header would
    otherwise sail straight through to un-scoped queries. Enforcing the
    check here, before routing, closes that gap for EVERY /api/* route
    in one place: with multi-tenant disabled (the default), any request
    carrying an `X-Tenant-Id` other than the default tenant is refused.
    Enable real multi-tenant with PITANTUM_MULTI_TENANT=1 once per-tenant
    scoping exists.
    """

    async def dispatch(self, request, call_next):
        if not _multi_tenant_enabled():
            raw = request.headers.get("X-Tenant-Id")
            if raw is not None and raw.strip():
                try:
                    requested = int(raw)
                except ValueError:
                    requested = DEFAULT_TENANT_ID
                if requested != DEFAULT_TENANT_ID:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "detail": (
                                "Multi-tenant non abilitato: questo backend "
                                "serve un singolo istituto. Rimuovere "
                                "l'header X-Tenant-Id."
                            ),
                            "code": "multi_tenant_disabled",
                            "error": "Multi-tenant non abilitato.",
                        },
                    )
        return await call_next(request)
