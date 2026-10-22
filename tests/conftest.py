import pytest

import stratus


@pytest.fixture
def app():
    return stratus.create_app(
        TESTING=True,
        SECRET_KEY="test",
        AUTH_URL="https://keystone.test/v3",
        USER_DOMAIN_NAME="Default",
    )


@pytest.fixture
def client(app):
    return app.test_client()
