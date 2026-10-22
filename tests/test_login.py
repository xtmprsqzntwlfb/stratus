import unittest.mock as mock

import keystoneauth1.exceptions
import pytest

CREDENTIALS = {
    "auth_url": "https://keystone.test/v3",
    "username": "demo",
    "password": "secret",
    "user_domain_name": "Default",
}


@pytest.fixture
def keystone():
    """Hand out a token without a network.

    Patched as deep as possible: everything from the form parsing down to
    openstacksdk assembling a session really runs, and only the request over
    the wire is replaced.
    """
    with mock.patch(
        "keystoneauth1.session.Session.get_token", return_value="a-token"
    ) as get_token:
        yield get_token


def test_anonymous_is_sent_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login?next=/"


def test_login_form_is_prefilled_from_config(client):
    page = client.get("/login").get_data(as_text=True)
    assert 'value="https://keystone.test/v3"' in page
    assert 'value="Default"' in page


def test_successful_login_stores_the_token(client, keystone):
    response = client.post("/login", data=CREDENTIALS)
    assert response.headers["Location"] == "/"
    with client.session_transaction() as session:
        assert session["cloud"]["token"] == "a-token"
        assert session["cloud"]["username"] == "demo"


def test_the_password_is_not_kept(client, keystone):
    client.post("/login", data=CREDENTIALS)
    with client.session_transaction() as session:
        assert "password" not in session["cloud"]


def test_surrounding_whitespace_is_forgiven(client, keystone):
    pasted = dict(CREDENTIALS, username="  demo\n", password=" secret ")
    client.post("/login", data=pasted)
    with client.session_transaction() as session:
        assert session["cloud"]["username"] == "demo"


def test_rejected_credentials_are_reported(client, keystone):
    keystone.side_effect = keystoneauth1.exceptions.Unauthorized()
    page = client.post("/login", data=CREDENTIALS).get_data(as_text=True)
    assert "rejected those credentials" in page
    with client.session_transaction() as session:
        assert "cloud" not in session


def test_a_wrong_endpoint_is_reported(client, keystone):
    keystone.side_effect = keystoneauth1.exceptions.DiscoveryFailure()
    page = client.post("/login", data=CREDENTIALS).get_data(as_text=True)
    assert "not a version 3 identity endpoint" in page


def test_an_unexplained_failure_still_says_something(client, keystone):
    keystone.side_effect = keystoneauth1.exceptions.ClientException("teapot")
    page = client.post("/login", data=CREDENTIALS).get_data(as_text=True)
    assert "refused the request: teapot" in page


def test_a_failed_login_keeps_what_was_typed(client, keystone):
    keystone.side_effect = keystoneauth1.exceptions.Unauthorized()
    typed = dict(CREDENTIALS, username="someone")
    page = client.post("/login", data=typed).get_data(as_text=True)
    assert 'value="someone"' in page
    assert "secret" not in page


def test_login_returns_to_the_requested_page(client, keystone):
    response = client.post("/login?next=/servers", data=CREDENTIALS)
    assert response.headers["Location"] == "/servers"


@pytest.mark.parametrize("target", ["//evil.test/", "https://evil.test/", "evil"])
def test_login_does_not_redirect_off_site(client, keystone, target):
    response = client.post(f"/login?next={target}", data=CREDENTIALS)
    assert response.headers["Location"] == "/"


def test_logout_clears_the_session(client, keystone):
    client.post("/login", data=CREDENTIALS)
    response = client.post("/logout")
    assert response.headers["Location"] == "/login"
    with client.session_transaction() as session:
        assert "cloud" not in session
