"""Auth gate and role-based redirect tests."""


def test_login_get_renders_form(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"login" in resp.data.lower() or b"username" in resp.data.lower()


def test_login_with_bad_password_shows_error(client):
    resp = client.post("/", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 200
    assert b"Invalid" in resp.data


def test_login_redirects_admin_to_admin_dashboard(login):
    resp = login("admin")
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]


def test_login_redirects_doctor_to_doctor_dashboard(login):
    resp = login("doctor")
    assert resp.status_code == 302
    assert "/doctor" in resp.headers["Location"]


def test_logout_clears_session(client, login):
    login("admin")
    resp = client.get("/logout")
    assert resp.status_code == 302
    # After logout the admin page should kick us back to login.
    assert client.get("/admin").status_code == 302


def test_admin_route_blocks_anonymous(client):
    resp = client.get("/admin")
    assert resp.status_code == 302  # redirected to login


def test_admin_route_blocks_doctor(client, login):
    login("doctor")
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302


def test_doctor_route_blocks_patient(client, login):
    login("patient")
    resp = client.get("/doctor", follow_redirects=False)
    assert resp.status_code == 302
