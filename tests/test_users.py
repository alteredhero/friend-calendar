from conftest import event_payload


def users(client):
    return {u["name"]: u for u in client.get("/api/users").json()}


def test_add_and_list_user(client):
    resp = client.post("/api/users", json={"name": "Sam", "color": "#112233", "timezone": "America/Chicago"})
    assert resp.json() == {"ok": True, "name": "Sam", "color": "#112233", "timezone": "America/Chicago"}
    assert users(client)["Sam"]["timezone"] == "America/Chicago"


def test_adding_again_updates_instead_of_duplicating(client):
    client.post("/api/users", json={"name": "Sam", "color": "#112233"})
    client.post("/api/users", json={"name": "Sam", "color": "#445566", "timezone": "America/New_York"})
    found = client.get("/api/users").json()
    assert [u["name"] for u in found] == ["Sam"]
    assert found[0]["color"] == "#445566" and found[0]["timezone"] == "America/New_York"


def test_unknown_timezone_falls_back_to_default(client):
    resp = client.post("/api/users", json={"name": "Sam", "timezone": "Mars/Olympus_Mons"})
    assert resp.json()["timezone"] == "America/Los_Angeles"


def test_validation(client):
    assert client.post("/api/users", json={"name": "Sam", "color": "red"}).status_code == 422
    assert client.post("/api/users", json={"name": ""}).status_code == 422
    assert client.post("/api/users", json={"name": "   "}).status_code == 400


def test_name_is_trimmed(client):
    assert client.post("/api/users", json={"name": "  Sam  "}).json()["name"] == "Sam"


def test_event_owners_without_a_user_row_still_show_up(client):
    client.post("/api/events", json=event_payload(owner="Ghost"))
    assert "Ghost" in users(client)


def test_users_are_sorted_case_insensitively(client):
    for name in ("bob", "Alice", "carol"):
        client.post("/api/users", json={"name": name})
    assert [u["name"] for u in client.get("/api/users").json()] == ["Alice", "bob", "carol"]
