"""Org creation and the single-org-per-user rule (SPEC section 8)."""

from __future__ import annotations

import pytest

from intake.backend.services.org_service import OrgError


def test_create_org_creates_a_client_owner(harness) -> None:
    created = harness.create_org()
    assert created["org"]["legal_name"] == "Northlight Studios"
    assert created["owner"]["role"] == "client_owner"
    assert created["owner"]["org_id"] == created["org"]["org_id"]


def test_new_org_awaits_the_seed_form(harness) -> None:
    """Seed-form fields start empty rather than placeholder-filled."""
    org = harness.create_org()["org"]
    assert org["profile_status"] == "awaiting_seed_form"
    assert org["reporting_year"] is None
    assert org["responsible_party"] is None


def test_owner_email_is_normalised(harness) -> None:
    created = harness.org_service.create_org(
        legal_name="Northlight",
        owner_name="Sam",
        owner_email="  Sam@Example.COM ",
        created_by="internal@sustentra.com",
    )
    assert created["owner"]["email"] == "sam@example.com"


@pytest.mark.parametrize("bad_email", ["", "   ", "not-an-email"])
def test_invalid_owner_email_is_rejected(harness, bad_email: str) -> None:
    with pytest.raises(OrgError):
        harness.org_service.create_org(
            legal_name="Northlight",
            owner_name="Sam",
            owner_email=bad_email,
            created_by="internal@sustentra.com",
        )


def test_blank_legal_name_is_rejected(harness) -> None:
    with pytest.raises(OrgError):
        harness.org_service.create_org(
            legal_name="   ",
            owner_name="Sam",
            owner_email="sam@example.com",
            created_by="internal@sustentra.com",
        )


def test_a_user_cannot_belong_to_two_orgs(harness) -> None:
    harness.create_org(legal_name="First Studio", email="shared@example.com")
    with pytest.raises(OrgError) as exc:
        harness.create_org(legal_name="Second Studio", email="shared@example.com")
    assert "exactly one org" in str(exc.value)


def test_adding_a_user_to_a_second_org_is_rejected(harness) -> None:
    first = harness.create_org(legal_name="First", email="a@example.com")
    second = harness.create_org(legal_name="Second", email="b@example.com")
    with pytest.raises(OrgError):
        harness.org_service.add_user(
            org_id=second["org"]["org_id"], name="A", email="a@example.com", role="client_member"
        )
    assert len(harness.org_service.list_users(first["org"]["org_id"])) == 1


def test_adding_an_existing_user_to_their_own_org_is_idempotent(harness) -> None:
    created = harness.create_org()
    again = harness.org_service.add_user(
        org_id=created["org"]["org_id"],
        name="Sam Owner",
        email="owner@example.com",
        role="client_member",
    )
    assert again["user_id"] == created["owner"]["user_id"]
    assert again["role"] == "client_owner", "an existing user keeps their role"


def test_unknown_role_is_rejected(harness) -> None:
    created = harness.create_org()
    with pytest.raises(OrgError):
        harness.org_service.add_user(
            org_id=created["org"]["org_id"], name="X", email="x@example.com", role="admin"
        )


def test_unknown_org_is_rejected(harness) -> None:
    with pytest.raises(OrgError):
        harness.org_service.get_org("org_missing")


def test_role_permissions_come_from_config(harness) -> None:
    assert harness.org_service.can_manage_users("client_owner") is True
    assert harness.org_service.can_manage_users("client_member") is False
    assert harness.org_service.can_submit_seed_form("sustentra_reviewer") is False


# -- privilege escalation ----------------------------------------------------


def test_a_client_owner_cannot_create_a_sustentra_reviewer(harness) -> None:
    """The hole this closes was real and provable.

    ``sustentra_reviewer`` gained cross-client powers in Phase D2 (the review
    queue) and Phase E (any client's profile). A client owner can manage their
    own team, so before this check they could grant that role to an email they
    controlled and read every other client's data.
    """
    created = harness.create_org()
    with pytest.raises(OrgError) as error:
        harness.org_service.add_user(
            org_id=created["org"]["org_id"],
            name="Ada (alt)",
            email="ada.alt@example.com",
            role="sustentra_reviewer",
            actor_role="client_owner",
        )
    assert "Sustentra staff" in str(error.value)


def test_a_client_member_cannot_either(harness) -> None:
    created = harness.create_org()
    with pytest.raises(OrgError):
        harness.org_service.add_user(
            org_id=created["org"]["org_id"],
            name="Alt",
            email="alt@example.com",
            role="sustentra_reviewer",
            actor_role="client_member",
        )


def test_an_unstated_actor_is_refused_rather_than_trusted(harness) -> None:
    """Fails closed: a caller that forgets to say who is acting cannot grant staff."""
    created = harness.create_org()
    with pytest.raises(OrgError):
        harness.org_service.add_user(
            org_id=created["org"]["org_id"],
            name="Alt",
            email="alt@example.com",
            role="sustentra_reviewer",
        )


def test_sustentra_staff_can_create_sustentra_staff(harness) -> None:
    created = harness.create_org()
    user = harness.org_service.add_user(
        org_id=created["org"]["org_id"],
        name="Rae Reviewer",
        email="rae@sustentra.com",
        role="sustentra_reviewer",
        actor_role="sustentra_reviewer",
    )
    assert user["role"] == "sustentra_reviewer"


def test_a_client_owner_can_still_manage_their_own_team(harness) -> None:
    """The fix must not stop a client adding their own colleagues."""
    created = harness.create_org()
    user = harness.org_service.add_user(
        org_id=created["org"]["org_id"],
        name="Sam Colleague",
        email="sam@example.com",
        role="client_member",
        actor_role="client_owner",
    )
    assert user["role"] == "client_member"
