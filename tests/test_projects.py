"""The project list and the project page, and what the CLI prints on them."""

import types
import unittest.mock as mock

import keystoneauth1.exceptions
import pytest

from stratus import auth, resources, views

LOGGED_IN = {
    "auth_url": "https://keystone.test/v3",
    "username": "demo",
    "user_domain_name": "Default",
    "token": "a-token",
}

DEMO = types.SimpleNamespace(
    id="81741bf155af4b1685825d7e8850a56b",
    name="demo",
    description="",
    domain_id="default",
    is_enabled=True,
    is_domain=False,
    options={},
    parent_id="default",
    tags=[],
)
OTHER = types.SimpleNamespace(id="bec5bc75c0004a57a01fda1014fb8148", name="other")


@pytest.fixture
def cloud(client):
    """A signed-in client, and the connection the views will be handed."""
    with client.session_transaction() as session:
        session[auth.CLOUD] = LOGGED_IN
    connection = mock.MagicMock()
    connection.session.get_user_id.return_value = "a-user"
    connection.identity.user_projects.return_value = [DEMO, OTHER]
    connection.identity.get_project.return_value = DEMO
    with mock.patch("stratus.auth.connection", return_value=connection):
        yield connection


def test_the_project_list_needs_a_login(client):
    response = client.get("/projects")
    assert response.headers["Location"] == "/login?next=/projects"


def test_the_front_page_goes_to_the_projects(client, cloud):
    assert client.get("/").headers["Location"] == "/projects"


def test_the_list_asks_only_for_reachable_projects(client, cloud):
    """Plain `project list` is refused non-admins, so it must not be used."""
    client.get("/projects")
    cloud.identity.user_projects.assert_called_once_with("a-user")
    cloud.identity.projects.assert_not_called()


def test_the_list_prints_the_columns_the_cli_prints(client, cloud):
    page = client.get("/projects").get_data(as_text=True)
    assert "<th>ID</th>" in page
    assert "<th>Name</th>" in page
    assert page.count("<th>") == 2


def test_each_project_links_to_its_page(client, cloud):
    page = client.get("/projects").get_data(as_text=True)
    assert f'href="/projects/{DEMO.id}"' in page
    assert f'href="/projects/{OTHER.id}"' in page


def test_an_account_with_no_projects_is_told_so(client, cloud):
    cloud.identity.user_projects.return_value = []
    page = client.get("/projects").get_data(as_text=True)
    assert "No projects this account can reach" in page


def test_the_project_page_is_scoped_to_that_project(client, cloud):
    with mock.patch("stratus.auth.connection", return_value=cloud) as connect:
        client.get(f"/projects/{DEMO.id}")
    connect.assert_called_once_with(DEMO.id)


def test_the_project_page_prints_what_project_show_prints(client, cloud):
    page = client.get(f"/projects/{DEMO.id}").get_data(as_text=True)
    printed = [label for label, _ in resources.pairs_of(DEMO, resources.PROJECT_SHOW)]
    assert printed == [
        "description",
        "domain_id",
        "enabled",
        "id",
        "is_domain",
        "name",
        "options",
        "parent_id",
        "tags",
    ]
    for label in printed:
        assert f"<dt>{label}</dt>" in page


def test_the_cli_name_for_a_field_wins_over_the_sdk_name(client, cloud):
    """The CLI calls it `enabled`; openstacksdk calls it `is_enabled`."""
    page = client.get(f"/projects/{DEMO.id}").get_data(as_text=True)
    assert "<dt>enabled</dt><dd>True</dd>" in page
    assert "is_enabled" not in page


def test_an_unreachable_project_is_not_found(client, cloud):
    """Keystone says 401, but the token is good, so the project is at fault."""
    cloud.identity.get_project.side_effect = keystoneauth1.exceptions.Unauthorized()
    response = client.get("/projects/deadbeef")
    assert response.status_code == 404
    with client.session_transaction() as session:
        assert auth.CLOUD in session  # and the session survives it


def test_an_expired_token_ends_the_session(client, cloud):
    """The same 401, but now the token itself no longer works."""
    cloud.identity.get_project.side_effect = keystoneauth1.exceptions.Unauthorized()
    cloud.session.get_user_id.side_effect = keystoneauth1.exceptions.Unauthorized()
    response = client.get("/projects/deadbeef")
    assert response.headers["Location"] == "/login"
    with client.session_transaction() as session:
        assert auth.CLOUD not in session


def test_an_expired_token_on_the_list_ends_the_session(client, cloud):
    cloud.identity.user_projects.side_effect = keystoneauth1.exceptions.Unauthorized()
    response = client.get("/projects")
    assert response.headers["Location"] == "/login"
    with client.session_transaction() as session:
        assert auth.CLOUD not in session
