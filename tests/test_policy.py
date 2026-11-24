"""What an account sees, on every route, for every answer a cloud gives.

Behaviour rather than rules. Stratus holds no policy of its own: keystone,
nova and the rest decide who may see what, and all this can do is turn
their answer into a page. So nothing here asserts a rule. Each case says
what the cloud replied and checks the page that came back, across every
resource in the registry, so a new one is covered the day it is declared.

Three things must hold on every route, whatever the answer:

    no traceback reaches the browser
    a refusal and an absence are indistinguishable
    a page about one project shows nothing from another
"""

import operator
import types
import unittest.mock as mock

import keystoneauth1.exceptions
import openstack.exceptions
import pytest

from stratus import auth, resources

MINE = "proj-a"
THEIRS = "proj-b"

LOGGED_IN = {
    "auth_url": "https://keystone.test/v3",
    "username": "someone",
    "user_domain_name": "Default",
    "token": "a-token",
}

KINDS = sorted(resources.CATALOGUE)


def primary_calls(resource):
    """The proxy calls a resource's list and show cannot do without.

    Taken from the declaration rather than written down again, so that
    these tests follow the registry instead of trailing behind it.
    """
    listing = mock.MagicMock()
    list(resource.index(listing))
    showing = mock.MagicMock()
    resource.fetch(showing, "an-id")
    return listing.mock_calls[0][0], showing.mock_calls[0][0]


# Every route a logged-in account can reach, and the call behind it.
def routes():
    yield "the project list", "/projects", "identity.user_projects"
    yield "a project", f"/projects/{MINE}", "identity.get_project"
    for kind in KINDS:
        index, fetch = primary_calls(resources.CATALOGUE[kind])
        yield f"the {kind} listing", f"/projects/{MINE}/{kind}", index
        yield f"a {kind[:-1]}", f"/projects/{MINE}/{kind}/an-id", fetch


ROUTES = list(routes())
ROUTE_IDS = [name for name, _, _ in ROUTES]


def listed(kind, project):
    """Something a listing can render, belonging to one project."""
    shape = {
        "servers": dict(
            status="ACTIVE",
            addresses={},
            image=None,
            flavor=types.SimpleNamespace(original_name="m1.nano", id="42"),
        ),
        "images": dict(status="active"),
        "networks": dict(subnet_ids=[]),
        "flavors": dict(ram=1, disk=1, ephemeral=0, vcpus=1, is_public=True),
        "volumes": dict(status="available", size=1, attachments=[]),
    }[kind]
    return types.SimpleNamespace(
        id=f"{kind}-{project}", name=f"{kind}-of-{project}", **shape
    )


def shown(kind, project):
    item = mock.MagicMock(is_public=True)
    item.id = f"{kind}-{project}"
    item.name = f"{kind}-of-{project}"
    item.to_dict.return_value = {"id": item.id, "name": item.name}
    return item


def a_project(identifier):
    return types.SimpleNamespace(
        id=identifier,
        name=f"project-{identifier}",
        description="",
        domain_id="default",
        is_enabled=True,
        is_domain=False,
        options={},
        parent_id="default",
        tags=[],
    )


def furnish(connection, project):
    """Stock a connection with everything belonging to one project."""
    connection.session.get_user_id.return_value = "a-user"
    connection.identity.user_projects.return_value = [
        a_project(MINE),
        a_project(THEIRS),
    ]
    connection.identity.get_project.return_value = a_project(project or MINE)
    connection.session.auth.get_access.return_value.service_catalog.catalog = [
        {"type": t}
        for t in ("identity", "compute", "image", "network", "block-storage")
    ]
    for kind, resource in resources.CATALOGUE.items():
        index, fetch = primary_calls(resource)
        operator.attrgetter(index)(connection).return_value = [
            listed(kind, project or MINE)
        ]
        operator.attrgetter(fetch)(connection).return_value = shown(
            kind, project or MINE
        )
    return connection


class Cloud:
    """A cloud that answers, with each project holding only its own.

    Breakage is held here rather than set on a connection, and applied
    whenever one is handed out, so that it reaches connections made later
    too. Setting it per connection quietly passes the moment a test asks
    for a project it has not broken yet.
    """

    def __init__(self):
        self.made = {}
        self.broken = {}
        self.scope_refused = None

    def __call__(self, project_id=None):
        connection = self.made.get(project_id)
        if connection is None:
            connection = self.made[project_id] = furnish(
                mock.MagicMock(), project_id
            )
        connection.session.get_token.side_effect = self.scope_refused
        for call, failure in self.broken.items():
            operator.attrgetter(call)(connection).side_effect = failure
        return connection

    def breaks(self, call, failure):
        self.broken[call] = failure

    def mends(self, call):
        self.broken.pop(call, None)
        for connection in self.made.values():
            operator.attrgetter(call)(connection).side_effect = None

    def refuses_scope(self, failure=None):
        self.scope_refused = failure or keystoneauth1.exceptions.Unauthorized()

    def allows_scope(self):
        self.scope_refused = None


@pytest.fixture
def cloud(client):
    with client.session_transaction() as session:
        session[auth.CLOUD] = LOGGED_IN
    answering = Cloud()
    with mock.patch("stratus.auth.connection", side_effect=answering):
        yield answering


def body(response):
    return response.get_data(as_text=True)


def assert_no_traceback(response):
    page = body(response)
    for giveaway in ("Traceback", 'File "', "Werkzeug Debugger", "line 1, in"):
        assert giveaway not in page, f"{giveaway!r} reached the browser"


# What the cloud said, and what the page must become.
REFUSALS = {
    "401": (openstack.exceptions.HttpException("no", http_status=401), "login"),
    "403": (openstack.exceptions.ForbiddenException("no"), 404),
    "404": (openstack.exceptions.NotFoundException("no"), 404),
    "no endpoint": (openstack.exceptions.EndpointNotFound("gone"), 503),
    "timeout": (keystoneauth1.exceptions.ConnectTimeout("slow"), 503),
}


@pytest.mark.parametrize("name, url, call", ROUTES, ids=ROUTE_IDS)
class TestAnAccountThatMayRead:
    """A member and a reader see the same thing: these pages only read."""

    def test_the_page_is_drawn(self, client, cloud, name, url, call):
        response = client.get(url)
        assert response.status_code == 200
        assert_no_traceback(response)

    def test_it_shows_this_project_and_no_other(self, client, cloud, name, url, call):
        if url == "/projects":
            pytest.skip("the project list names every project, that being its job")
        assert THEIRS not in body(client.get(url))


@pytest.mark.parametrize("name, url, call", ROUTES, ids=ROUTE_IDS)
@pytest.mark.parametrize("answer", list(REFUSALS), ids=list(REFUSALS))
class TestWhenTheCloudRefuses:
    def test_the_outcome_is_the_intended_one(
        self, client, cloud, answer, name, url, call
    ):
        failure, expected = REFUSALS[answer]
        cloud.breaks(call, failure)
        response = client.get(url)
        if expected == "login":
            assert response.status_code == 302
            assert response.headers["Location"].startswith("/login")
        else:
            assert response.status_code == expected

    def test_no_traceback_reaches_the_browser(
        self, client, cloud, answer, name, url, call
    ):
        failure, _ = REFUSALS[answer]
        cloud.breaks(call, failure)
        assert_no_traceback(client.get(url))

    def test_nothing_of_the_cloud_s_wording_is_repeated(
        self, client, cloud, answer, name, url, call
    ):
        """An exception's text can name hosts, projects and endpoints."""
        failure, _ = REFUSALS[answer]
        cloud.breaks(call, failure)
        page = body(client.get(url))
        for leak in ("ForbiddenException", "NotFoundException", "HttpException"):
            assert leak not in page


@pytest.mark.parametrize("name, url, call", ROUTES, ids=ROUTE_IDS)
class TestNoExistenceLeak:
    def test_a_refusal_and_an_absence_read_alike(self, client, cloud, name, url, call):
        """Otherwise the difference between them maps the cloud."""
        cloud.breaks(call, openstack.exceptions.ForbiddenException("no"))
        denied = client.get(url)
        cloud.breaks(call, openstack.exceptions.NotFoundException("no"))
        absent = client.get(url)
        assert denied.status_code == absent.status_code
        assert body(denied) == body(absent)

    def test_and_neither_names_what_was_asked_for(self, client, cloud, name, url, call):
        cloud.breaks(call, openstack.exceptions.ForbiddenException("no"))
        assert "an-id" not in body(client.get(url))


@pytest.mark.parametrize("kind", KINDS)
class TestAProjectThatMayNotBeEntered:
    """Keystone refuses the rescope, but the token itself is still good."""

    def test_the_listing_is_a_404(self, client, cloud, kind):
        cloud.refuses_scope()
        response = client.get(f"/projects/{THEIRS}/{kind}")
        assert response.status_code == 404
        assert_no_traceback(response)

    def test_the_item_is_a_404(self, client, cloud, kind):
        cloud.refuses_scope()
        assert client.get(f"/projects/{THEIRS}/{kind}/an-id").status_code == 404

    def test_the_session_is_not_ended_by_it(self, client, cloud, kind):
        cloud.refuses_scope()
        client.get(f"/projects/{THEIRS}/{kind}")
        with client.session_transaction() as session:
            assert auth.CLOUD in session

    def test_it_reads_the_same_as_a_project_that_is_not_there(
        self, client, cloud, kind
    ):
        cloud.refuses_scope()
        refused = client.get(f"/projects/{THEIRS}/{kind}")
        cloud.allows_scope()
        index, _ = primary_calls(resources.CATALOGUE[kind])
        cloud.breaks(index, openstack.exceptions.NotFoundException("no"))
        missing = client.get(f"/projects/no-such-project/{kind}")
        assert refused.status_code == missing.status_code == 404
        assert body(refused) == body(missing)


class TestTheTokenItself:
    @pytest.mark.parametrize("kind", KINDS)
    def test_an_expired_token_ends_the_session_everywhere(self, client, cloud, kind):
        cloud.refuses_scope()
        cloud.breaks("session.get_user_id", keystoneauth1.exceptions.Unauthorized())
        response = client.get(f"/projects/{MINE}/{kind}")
        assert response.headers["Location"] == "/login"
        with client.session_transaction() as session:
            assert auth.CLOUD not in session

    @pytest.mark.parametrize("name, url, call", ROUTES, ids=ROUTE_IDS)
    def test_no_route_is_reachable_without_one(self, client, name, url, call):
        response = client.get(url)
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")
