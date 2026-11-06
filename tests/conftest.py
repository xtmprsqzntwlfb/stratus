import os

import pytest

import stratus


@pytest.fixture
def app(monkeypatch):
    # Whatever this machine's local_settings.py says about a real cloud is
    # none of the tests' business, so point the loader at an empty file.
    monkeypatch.setenv(stratus.LOCAL_SETTINGS_VARIABLE, os.devnull)
    return stratus.create_app(
        TESTING=True,
        SECRET_KEY="test",
        AUTH_URL="https://keystone.test/v3",
        USER_DOMAIN_NAME="Default",
    )


@pytest.fixture
def client(app):
    return app.test_client()
