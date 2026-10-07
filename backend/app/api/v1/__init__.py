"""Versioned public API, mounted at /api/v1."""

from fastapi import APIRouter

from . import auth, org_audit, org_invites, org_users, provider_orgs

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(provider_orgs.router)  # ORG-001
router.include_router(org_users.router)  # ORG-002
router.include_router(org_invites.router)  # ORG-003
router.include_router(org_audit.router)  # COMP-002
