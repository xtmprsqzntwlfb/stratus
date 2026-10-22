"""The connections handed to the rest of Stratus carry the right scope."""

import pytest

from stratus import auth

CREDENTIALS = {
    "auth_url": "https://keystone.test/v3",
    "username": "demo",
    "password": "secret",
    "user_domain_name": "Default",
}
LOGGED_IN = {
    "auth_url": "https://keystone.test/v3",
    "username": "demo",
    "user_domain_name": "Default",
    "token": "a-token",
}


@pytest.fixture
def signed_in(app):
    """A request context in which someone holds a token."""
    with app.test_request_context():
        import flask

        flask.session[auth.CLOUD] = LOGGED_IN
        yield


def test_logging_in_asks_for_no_project(app):
    with app.test_request_context():
        plugin = auth._connect("v3password", **CREDENTIALS).config.get_auth()
    assert plugin.auth_url == "https://keystone.test/v3"
    # No project and no domain scope, so Keystone answers with an unscoped
    # token, which is the only kind the session is allowed to hold.
    assert getattr(plugin, "project_id", None) is None
    assert getattr(plugin, "project_name", None) is None
    assert getattr(plugin, "domain_id", None) is None


def test_an_unscoped_connection_reuses_the_token(signed_in):
    # The plugin keeps the token private; this is how it reports it.
    plugin = auth.connection().config.get_auth().get_cache_id_elements()
    assert plugin["token_token"] == "a-token"
    assert plugin["project_id"] is None


def test_a_project_connection_is_scoped_to_it(signed_in):
    plugin = auth.connection(project_id="p1").config.get_auth()
    assert plugin.get_cache_id_elements()["token_token"] == "a-token"
    assert plugin.project_id == "p1"


def test_connections_identify_stratus(signed_in):
    session = auth.connection().session
    assert session.app_name == auth.APP_NAME
    assert session.app_version == auth.APP_VERSION


def test_nothing_is_read_from_the_environment(app, monkeypatch):
    """A sourced openrc must not quietly override the login form."""
    monkeypatch.setenv("OS_AUTH_URL", "https://wrong.test/v3")
    monkeypatch.setenv("OS_USERNAME", "someone-else")
    with app.test_request_context():
        plugin = auth._connect("v3password", **CREDENTIALS).config.get_auth()
    assert plugin.auth_url == "https://keystone.test/v3"
