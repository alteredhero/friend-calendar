import json


def test_no_password_means_open(client):
    assert client.get("/api/events").status_code == 200


def test_gate_blocks_api_and_redirects_pages(client, set_password):
    set_password("correct horse battery")
    assert client.get("/api/events").status_code == 401
    page = client.get("/")
    assert page.status_code in (302, 307)
    assert page.headers["location"] == "/login"


def test_login_page_and_static_stay_reachable(client, set_password):
    set_password("correct horse battery")
    assert client.get("/login").status_code == 200
    assert client.get("/static/lib.js").status_code == 200


def test_wrong_password_is_refused(client, set_password):
    set_password("correct horse battery")
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    assert client.get("/api/events").status_code == 401


def test_non_ascii_wrong_password_is_401_not_a_crash(client, set_password):
    set_password("correct horse battery")
    assert client.post("/api/login", json={"password": "pässwörd"}).status_code == 401


def test_right_password_opens_the_gate(client, set_password):
    set_password("correct horse battery")
    assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    assert client.get("/api/events").status_code == 200


def test_password_is_trimmed(client, set_password):
    set_password("correct horse battery")
    assert client.post("/api/login", json={"password": "  correct horse battery  "}).status_code == 200


def test_changing_the_password_signs_everyone_out(client, set_password):
    set_password("first password")
    assert client.post("/api/login", json={"password": "first password"}).status_code == 200
    assert client.get("/api/events").status_code == 200
    set_password("second password")
    assert client.get("/api/events").status_code == 401


def test_clearing_the_password_opens_the_gate_again(client, set_password):
    set_password("a password")
    assert client.get("/api/events").status_code == 401
    set_password("")
    assert client.get("/api/events").status_code == 200


def test_legacy_plaintext_password_still_works(client, data_dir):
    (data_dir / "auth.json").write_text(json.dumps({"password": "legacy"}), encoding="utf-8")
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"password": "legacy"}).status_code == 200
    assert client.get("/api/events").status_code == 200


def test_logout_signs_you_out(client, set_password):
    set_password("a password")
    client.post("/api/login", json={"password": "a password"})
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/events").status_code == 401


def test_corrupt_auth_file_means_open_not_a_crash(client, data_dir):
    (data_dir / "auth.json").write_text("{not json", encoding="utf-8")
    assert client.get("/api/events").status_code == 200
