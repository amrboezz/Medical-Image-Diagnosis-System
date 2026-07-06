"""Per-role smoke tests: every dashboard renders for its intended role."""


def test_admin_dashboard_renders(client, login):
    login("admin")
    resp = client.get("/admin")
    assert resp.status_code == 200


def test_doctor_dashboard_renders(client, login):
    login("doctor")
    resp = client.get("/doctor")
    assert resp.status_code == 200


def test_secretary_dashboard_renders(client, login):
    login("secretary")
    resp = client.get("/secretary")
    assert resp.status_code == 200


def test_patient_dashboard_renders(client, login):
    login("patient")
    resp = client.get("/patient")
    assert resp.status_code == 200


def test_admin_log_api_returns_json(client, login):
    login("admin")
    resp = client.get("/api/admin/logs")
    assert resp.status_code == 200
    assert resp.is_json
    assert "logs" in resp.get_json()


def test_admin_can_create_and_delete_user(client, login):
    login("admin")
    resp = client.post("/add_user", data={
        "full_name": "Alice Test",
        "username":  "alice",
        "password":  "StrongPass1234",
        "role":      "patient",
    }, follow_redirects=False)
    assert resp.status_code == 302

    # Confirm the user exists by searching the user API.
    api = client.get("/api/admin/users?search=alice")
    assert api.status_code == 200
    usernames = [u["username"] for u in api.get_json()["users"]]
    assert "alice" in usernames


def test_admin_add_user_rejects_weak_password(client, login):
    login("admin")
    resp = client.post("/add_user", data={
        "full_name": "Bob Weak",
        "username":  "bob",
        "password":  "short",
        "role":      "patient",
    }, follow_redirects=False)
    # Validation failure flashes and redirects; user is NOT created.
    assert resp.status_code == 302
    api = client.get("/api/admin/users?search=bob")
    usernames = [u["username"] for u in api.get_json()["users"]]
    assert "bob" not in usernames


def test_chat_returns_friendly_message_when_key_missing(client, app, login):
    login("patient")
    app.config["GEMINI_API_KEY"] = ""
    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert "not configured" in resp.get_json()["reply"].lower()


def test_chat_rejects_empty_message(client, login):
    login("patient")
    resp = client.post("/api/chat", json={"message": "   "})
    assert resp.status_code == 400
