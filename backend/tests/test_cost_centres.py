"""L3 integration tests for Phase 3 cost-centre management."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def _token(client: TestClient, username: str) -> str:
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": username}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user_id(db: Session, username: str) -> str:
    user = db.scalar(select(User).where(User.username == username))
    assert user is not None
    return str(user.id)


def _create_cc(client: TestClient, token: str, **overrides) -> dict:
    body = {"code": "CC-1000", "name": "Platform"}
    body.update(overrides)
    resp = client.post("/api/cost-centres", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- create ---------------------------------------------------------------


def test_create_as_admin(client: TestClient, seeded: Session) -> None:
    token = _token(client, "admin")
    cc = _create_cc(
        client, token, code="CC-1234", name="Data Eng", budget_cap=1000.50
    )
    assert cc["code"] == "CC-1234"
    assert cc["name"] == "Data Eng"
    assert cc["status"] == "active"
    assert cc["budget_cap"] == 1000.50
    assert cc["owners"] == []
    assert cc["created_by"]


def test_create_duplicate_code_conflict(
    client: TestClient, seeded: Session
) -> None:
    token = _token(client, "admin")
    _create_cc(client, token, code="CC-DUP")
    resp = client.post(
        "/api/cost-centres",
        json={"code": "CC-DUP", "name": "Other"},
        headers=_auth(token),
    )
    assert resp.status_code == 409
    assert "detail" in resp.json()


def test_create_as_dev_forbidden(client: TestClient, seeded: Session) -> None:
    token = _token(client, "dev1")
    resp = client.post(
        "/api/cost-centres",
        json={"code": "CC-X", "name": "Nope"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


def test_create_unauthenticated(client: TestClient, seeded: Session) -> None:
    resp = client.post("/api/cost-centres", json={"code": "CC-Y", "name": "Z"})
    assert resp.status_code in (401, 403)


def test_create_negative_budget_unprocessable(
    client: TestClient, seeded: Session
) -> None:
    token = _token(client, "admin")
    resp = client.post(
        "/api/cost-centres",
        json={"code": "CC-NEG", "name": "Neg", "budget_cap": -1},
        headers=_auth(token),
    )
    assert resp.status_code == 422


# --- list / get -----------------------------------------------------------


def test_list_visibility(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    active = _create_cc(client, admin, code="CC-ACT", name="Active")
    archived = _create_cc(client, admin, code="CC-ARC", name="Archived")
    client.post(
        f"/api/cost-centres/{archived['id']}/archive", headers=_auth(admin)
    )

    admin_list = client.get("/api/cost-centres", headers=_auth(admin)).json()
    codes = {c["code"] for c in admin_list}
    assert {"CC-ACT", "CC-ARC"} <= codes

    dev = _token(client, "dev1")
    dev_list = client.get("/api/cost-centres", headers=_auth(dev)).json()
    dev_codes = {c["code"] for c in dev_list}
    assert "CC-ACT" in dev_codes
    assert "CC-ARC" not in dev_codes
    # ordered by code
    assert [c["code"] for c in admin_list] == sorted(c["code"] for c in admin_list)
    assert active["id"]


def test_get_missing_404(client: TestClient, seeded: Session) -> None:
    token = _token(client, "admin")
    resp = client.get(
        "/api/cost-centres/00000000-0000-0000-0000-000000000000",
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_get_archived_hidden_from_dev(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-HID")
    client.post(f"/api/cost-centres/{cc['id']}/archive", headers=_auth(admin))

    dev = _token(client, "dev1")
    resp = client.get(f"/api/cost-centres/{cc['id']}", headers=_auth(dev))
    assert resp.status_code == 404
    # admin can still see it
    assert (
        client.get(
            f"/api/cost-centres/{cc['id']}", headers=_auth(admin)
        ).status_code
        == 200
    )


# --- patch ----------------------------------------------------------------


def test_patch_as_admin(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-PATCH", budget_cap=100)
    resp = client.patch(
        f"/api/cost-centres/{cc['id']}",
        json={"name": "Renamed", "budget_cap": 250.0},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["budget_cap"] == 250.0
    assert body["code"] == "CC-PATCH"


def test_patch_as_dev_forbidden(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-PD")
    dev = _token(client, "dev1")
    resp = client.patch(
        f"/api/cost-centres/{cc['id']}",
        json={"name": "X"},
        headers=_auth(dev),
    )
    assert resp.status_code == 403


# --- archive / unarchive --------------------------------------------------


def test_archive_unarchive_cycle(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-CYC")
    dev = _token(client, "dev1")

    arch = client.post(
        f"/api/cost-centres/{cc['id']}/archive", headers=_auth(admin)
    )
    assert arch.status_code == 200
    assert arch.json()["status"] == "archived"

    dev_codes = {
        c["code"] for c in client.get("/api/cost-centres", headers=_auth(dev)).json()
    }
    assert "CC-CYC" not in dev_codes

    unarch = client.post(
        f"/api/cost-centres/{cc['id']}/unarchive", headers=_auth(admin)
    )
    assert unarch.status_code == 200
    assert unarch.json()["status"] == "active"

    dev_codes = {
        c["code"] for c in client.get("/api/cost-centres", headers=_auth(dev)).json()
    }
    assert "CC-CYC" in dev_codes


def test_archive_idempotent_no_duplicate_audit(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-IDEM")
    client.post(f"/api/cost-centres/{cc['id']}/archive", headers=_auth(admin))
    client.post(f"/api/cost-centres/{cc['id']}/archive", headers=_auth(admin))

    rows = db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == "cost_centre.archived",
            AuditLog.entity_id == cc["id"],
        )
    ).all()
    assert len(rows) == 1


# --- owners ---------------------------------------------------------------


def test_assign_and_remove_owner(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-OWN")
    dev2_id = _user_id(db_session, "dev2")

    assign = client.post(
        f"/api/cost-centres/{cc['id']}/owners",
        json={"user_id": dev2_id},
        headers=_auth(admin),
    )
    assert assign.status_code == 200
    owners = assign.json()["owners"]
    assert any(o["user_id"] == dev2_id for o in owners)

    # dev2 now has cco role
    users = client.get("/api/users", headers=_auth(admin)).json()
    dev2 = next(u for u in users if u["username"] == "dev2")
    assert "cco" in dev2["roles"]

    # duplicate assign → 409
    dup = client.post(
        f"/api/cost-centres/{cc['id']}/owners",
        json={"user_id": dev2_id},
        headers=_auth(admin),
    )
    assert dup.status_code == 409

    # remove → owners empty, cco role stripped (owns nothing else)
    remove = client.delete(
        f"/api/cost-centres/{cc['id']}/owners/{dev2_id}", headers=_auth(admin)
    )
    assert remove.status_code == 200
    assert remove.json()["owners"] == []

    users = client.get("/api/users", headers=_auth(admin)).json()
    dev2 = next(u for u in users if u["username"] == "dev2")
    assert "cco" not in dev2["roles"]


def test_remove_owner_keeps_cco_if_owns_another(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="CC-A")
    cc2 = _create_cc(client, admin, code="CC-B")
    dev2_id = _user_id(db_session, "dev2")

    client.post(
        f"/api/cost-centres/{cc1['id']}/owners",
        json={"user_id": dev2_id},
        headers=_auth(admin),
    )
    client.post(
        f"/api/cost-centres/{cc2['id']}/owners",
        json={"user_id": dev2_id},
        headers=_auth(admin),
    )

    client.delete(
        f"/api/cost-centres/{cc1['id']}/owners/{dev2_id}", headers=_auth(admin)
    )

    users = client.get("/api/users", headers=_auth(admin)).json()
    dev2 = next(u for u in users if u["username"] == "dev2")
    assert "cco" in dev2["roles"]


def test_assign_owner_user_not_found(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-NF")
    resp = client.post(
        f"/api/cost-centres/{cc['id']}/owners",
        json={"user_id": "00000000-0000-0000-0000-000000000000"},
        headers=_auth(admin),
    )
    assert resp.status_code == 404


def test_remove_owner_missing_mapping_404(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-RM")
    dev2_id = _user_id(db_session, "dev2")
    resp = client.delete(
        f"/api/cost-centres/{cc['id']}/owners/{dev2_id}", headers=_auth(admin)
    )
    assert resp.status_code == 404


# --- audit ----------------------------------------------------------------


def test_create_writes_audit_row(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    admin_id = _user_id(db_session, "admin")
    cc = _create_cc(client, admin, code="CC-AUD")

    row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "cost_centre.created",
            AuditLog.entity_id == cc["id"],
        )
    )
    assert row is not None
    assert str(row.actor_id) == admin_id
    assert row.entity_type == "cost_centre"
    assert row.new_values["code"] == "CC-AUD"


# --- users listing --------------------------------------------------------


def test_list_users_as_admin(client: TestClient, seeded: Session) -> None:
    token = _token(client, "admin")
    resp = client.get("/api/users", headers=_auth(token))
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()}
    assert {"admin", "dev1", "dev2", "ccowner1"} <= usernames
    assert resp.json() == sorted(resp.json(), key=lambda u: u["username"])


def test_list_users_as_dev_forbidden(
    client: TestClient, seeded: Session
) -> None:
    token = _token(client, "dev1")
    resp = client.get("/api/users", headers=_auth(token))
    assert resp.status_code == 403
