from conftest import event_payload

DAYS = ["2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30"]


def make_series(client, days=DAYS, **over):
    body = {k: v for k, v in event_payload(**over).items() if k != "day"}
    resp = client.post("/api/events/bulk", json={**body, "days": days})
    assert resp.status_code == 200
    return resp.json()


def events_in(client, month="2026-11"):
    return client.get(f"/api/events?month={month}").json()


def first_id(client, day):
    return next(e["id"] for e in events_in(client) if e["day"] == day)


# ---- create / list ---------------------------------------------------------------
def test_create_and_list_by_month(client):
    created = client.post("/api/events", json=event_payload()).json()
    assert created["id"] and created["owner"] == "RJ" and created["series_id"] is None
    client.post("/api/events", json=event_payload(day="2026-12-01", title="December"))
    assert [e["title"] for e in events_in(client, "2026-11")] == ["Movie night"]
    assert [e["title"] for e in events_in(client, "2026-12")] == ["December"]
    assert len(client.get("/api/events").json()) == 2


def test_events_come_back_sorted_by_day_then_start(client):
    client.post("/api/events", json=event_payload(day="2026-11-06", title="late"))
    client.post("/api/events", json=event_payload(day="2026-11-05", title="b", start_min=600, end_min=700))
    client.post("/api/events", json=event_payload(day="2026-11-05", title="a", start_min=60, end_min=120))
    assert [e["title"] for e in events_in(client)] == ["a", "b", "late"]


def test_validation(client):
    assert client.post("/api/events", json=event_payload(tag="nonsense")).status_code == 400
    assert client.post("/api/events", json=event_payload(start_min=600, end_min=600)).status_code == 400
    assert client.post("/api/events", json=event_payload(start_min=700, end_min=600)).status_code == 400
    assert client.post("/api/events", json=event_payload(day="tomorrow")).status_code == 422
    assert client.post("/api/events", json=event_payload(owner="")).status_code == 422
    assert client.post("/api/events", json=event_payload(end_min=1441)).status_code == 422


def test_update_replaces_one_event_and_404s_when_missing(client):
    ev = client.post("/api/events", json=event_payload()).json()
    changed = client.put(f"/api/events/{ev['id']}", json=event_payload(title="Renamed", tag="game")).json()
    assert changed["title"] == "Renamed" and changed["tag"] == "game"
    assert client.put("/api/events/9999", json=event_payload()).status_code == 404


# ---- bulk / series -----------------------------------------------------------------
def test_bulk_over_several_days_shares_a_series_id(client):
    result = make_series(client)
    assert result["created"] == 5 and result["series_id"]
    assert {e["series_id"] for e in events_in(client)} == {result["series_id"]}


def test_bulk_single_day_is_not_a_series(client):
    result = make_series(client, days=["2026-11-05"])
    assert result["created"] == 1 and result["series_id"] is None


def test_bulk_dedupes_and_ignores_invalid_days(client):
    result = make_series(client, days=["2026-11-05", "2026-11-05", "not-a-day", "2026-11-06"])
    assert result["days"] == ["2026-11-05", "2026-11-06"]


def test_bulk_with_no_valid_days_is_rejected(client):
    body = {k: v for k, v in event_payload().items() if k != "day"}
    assert client.post("/api/events/bulk", json={**body, "days": ["junk"]}).status_code == 400


def test_series_info_counts(client):
    make_series(client)
    third = first_id(client, "2026-11-16")
    info = client.get(f"/api/events/{third}/series").json()
    assert (info["total"], info["following"]) == (5, 3)
    assert (info["first_day"], info["last_day"]) == ("2026-11-02", "2026-11-30")


def test_series_info_for_a_lone_event_counts_one(client):
    ev = client.post("/api/events", json=event_payload()).json()
    info = client.get(f"/api/events/{ev['id']}/series").json()
    assert (info["total"], info["following"], info["series_id"]) == (1, 1, None)


# ---- patch -----------------------------------------------------------------------------
def test_patch_single_touches_only_that_event(client):
    make_series(client)
    client.patch(f"/api/events/{first_id(client, '2026-11-09')}?scope=single", json={"title": "Edited"})
    assert [e["title"] for e in events_in(client)].count("Edited") == 1


def test_patch_all_changes_the_whole_series(client):
    make_series(client)
    resp = client.patch(f"/api/events/{first_id(client, '2026-11-09')}?scope=all", json={"tag": "game"})
    assert resp.json()["affected"] == 5
    assert {e["tag"] for e in events_in(client)} == {"game"}


def test_patch_following_edits_the_tail_and_splits_the_series(client):
    make_series(client)
    resp = client.patch(f"/api/events/{first_id(client, '2026-11-16')}?scope=following", json={"title": "New job"})
    assert resp.json()["affected"] == 3
    by_day = {e["day"]: e for e in events_in(client)}
    assert [by_day[d]["title"] for d in DAYS] == ["Movie night"] * 2 + ["New job"] * 3
    old, new = by_day["2026-11-02"]["series_id"], by_day["2026-11-16"]["series_id"]
    assert old != new and by_day["2026-11-09"]["series_id"] == old and by_day["2026-11-30"]["series_id"] == new
    # the split is real: an "entire series" edit on the old part can't reach the new part
    client.patch(f"/api/events/{first_id(client, '2026-11-02')}?scope=all", json={"tag": "busy"})
    assert [by["tag"] for by in events_in(client)] == ["busy", "busy", "movie", "movie", "movie"]


def test_bulk_edit_does_not_flatten_individual_times(client):
    make_series(client)
    odd = first_id(client, "2026-11-09")
    client.patch(f"/api/events/{odd}?scope=single", json={"start_min": 60, "end_min": 120})
    client.patch(f"/api/events/{odd}?scope=all", json={"tag": "game"})  # tag only
    times = {e["day"]: (e["start_min"], e["end_min"]) for e in events_in(client)}
    assert times["2026-11-09"] == (60, 120)
    assert times["2026-11-02"] == (1200, 1320)


def test_patch_validation(client):
    ev = client.post("/api/events", json=event_payload()).json()
    url = f"/api/events/{ev['id']}"
    assert client.patch(url, json={}).status_code == 400                                   # nothing to update
    assert client.patch(url, json={"tag": "nonsense"}).status_code == 400
    assert client.patch(url, json={"start_min": 100}).status_code == 400                   # times travel together
    assert client.patch(url, json={"start_min": 500, "end_min": 400}).status_code == 400
    assert client.patch(f"{url}?scope=bogus", json={"title": "x"}).status_code == 400
    assert client.patch("/api/events/9999", json={"title": "x"}).status_code == 404


def test_scope_on_a_lone_event_behaves_as_single(client):
    ev = client.post("/api/events", json=event_payload()).json()
    resp = client.patch(f"/api/events/{ev['id']}?scope=all", json={"title": "x"})
    assert resp.json()["affected"] == 1


# ---- delete ------------------------------------------------------------------------------
def test_delete_single(client):
    make_series(client)
    resp = client.delete(f"/api/events/{first_id(client, '2026-11-09')}")
    assert resp.json()["deleted"] == 1 and len(events_in(client)) == 4


def test_delete_following_and_all(client):
    make_series(client)
    assert client.delete(f"/api/events/{first_id(client, '2026-11-16')}?scope=following").json()["deleted"] == 3
    assert [e["day"] for e in events_in(client)] == DAYS[:2]
    assert client.delete(f"/api/events/{first_id(client, '2026-11-02')}?scope=all").json()["deleted"] == 2
    assert events_in(client) == []


def test_delete_missing_is_idempotent_and_bad_scope_rejected(client):
    assert client.delete("/api/events/9999").json() == {"ok": True, "deleted": 0}
    assert client.delete("/api/events/9999?scope=bogus").status_code == 400
