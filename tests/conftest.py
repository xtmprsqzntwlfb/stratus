import os
import secrets

import flask.testing
import pytest

import stratus
from stratus import csrf


class Client(flask.testing.FlaskClient):
    """A client whose posts carry the CSRF token, as a browser's would.

    The guard stays switched on for every test rather than configured
    away, because a security control that tests never exercise is one
    nobody notices breaking. Tests about the guard itself post their own
    token, or none, and this leaves those alone.
    """

    def post(self, *args, csrf_token=True, **kwargs):
        if not csrf_token:
            return super().post(*args, **kwargs)
        given = kwargs.get("data")
        if given is None:
            kwargs["data"] = {csrf.FIELD: self.token()}
        elif isinstance(given, dict) and csrf.FIELD not in given:
            kwargs["data"] = {**given, csrf.FIELD: self.token()}
        return super().post(*args, **kwargs)

    def token(self):
        with self.session_transaction() as session:
            held = session.get(csrf.FIELD)
            if not held:
                held = secrets.token_urlsafe(csrf.LENGTH)
                session[csrf.FIELD] = held
        return held


@pytest.fixture
def app(monkeypatch):
    # Whatever this machine's local_settings.py says about a real cloud is
    # none of the tests' business, so point the loader at an empty file.
    monkeypatch.setenv(stratus.LOCAL_SETTINGS_VARIABLE, os.devnull)
    built = stratus.create_app(
        TESTING=True,
        SECRET_KEY="test",
        AUTH_URL="https://keystone.test/v3",
        USER_DOMAIN_NAME="Default",
    )
    built.test_client_class = Client
    return built


@pytest.fixture
def client(app):
    return app.test_client()
