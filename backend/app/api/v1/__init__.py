"""Versioned public API, mounted at /api/v1."""

from fastapi import APIRouter

from . import admin_spend, auth, org_audit, org_invites, org_members, org_settings, org_tasks, org_users, provider_orgs

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(provider_orgs.router)  # ORG-001
router.include_router(admin_spend.router)  # MVP-245: per-org AI and scan spend (provider_admin)
router.include_router(org_users.router)  # ORG-002
router.include_router(org_invites.router)  # ORG-003
router.include_router(org_members.router)  # member directory (team picker)
router.include_router(org_settings.router)  # per-org switches
router.include_router(org_tasks.router)  # tasks
router.include_router(org_tasks.notifications_router)  # in-app notifications
router.include_router(org_audit.router)  # COMP-002
