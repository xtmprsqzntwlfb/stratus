"""The trail says which project you are in, not merely that you are in one."""

import operator
import re
import unittest.mock as mock

import keystoneauth1.exceptions
import pytest

from stratus import auth, resources

PROJECT = "54766a28ae56492591852dc1b53e9b66"
LOGGED_IN = {
    "auth_url": "https://keystone.test/v3",
    "username": "admin",
    "user_domain_name": "Default",
    "token": "a-token",
}
KINDS = sorted(resources.CATALOGUE)


def primary_calls(resource):
    """The proxy calls behind a resource's listing and its show page."""
    listing = mock.MagicMock()
    list(resource.index(listing))
    showing = mock.MagicMock()
    resource.fetch(showing, "an-id")
    return listing.mock_calls[0][0], showing.mock_calls[0][0]


@pytest.fixture
def cloud(client):
    with client.session_transaction() as session:
        session[auth.CLOUD] = LOGGED_IN
    connection = mock.MagicMock()
    connection.session.get_user_id.return_value = "a-user"
    connection.session.auth.get_access.return_value.project_name = "admin"

    shown = mock.MagicMock(is_public=True)
    shown.id, shown.name = "an-id", "a-thing"
    shown.to_dict.return_value = {"id": "an-id"}
    for resource in resources.CATALOGUE.values():
        index, fetch = primary_calls(resource)
        operator.attrgetter(index)(connection).return_value = []
        operator.attrgetter(fetch)(connection).return_value = shown

    with mock.patch("stratus.auth.connection", return_value=connection):
        yield connection


def trail(client, url):
    page = client.get(url).get_data(as_text=True)
    crumbs = re.search(r'<p class="crumbs">(.*?)</p>', page, re.S).group(1)
    return [
        re.sub("<[^>]*>", "", link).strip()
        for link in re.findall(r"<a [^>]*>(.*?)</a>", crumbs, re.S)
    ]


@pytest.mark.parametrize("kind", KINDS)
def test_a_listing_names_the_project(client, cloud, kind):
    assert trail(client, f"/projects/{PROJECT}/{kind}") == ["Projects", "admin"]


@pytest.mark.parametrize("kind", KINDS)
def test_an_item_names_the_project_and_the_kind(client, cloud, kind):
    assert trail(client, f"/projects/{PROJECT}/{kind}/an-id") == [
        "Projects",
        "admin",
        resources.CATALOGUE[kind].heading,
    ]


def test_the_bare_word_project_is_gone(client, cloud):
    assert "project" not in trail(client, f"/projects/{PROJECT}/servers")


def test_the_name_costs_no_request_of_its_own(client, cloud):
    """It rides on the token the scoping already fetched."""
    client.get(f"/projects/{PROJECT}/servers")
    cloud.identity.get_project.assert_not_called()


def test_the_id_stands_in_when_the_token_cannot_say(client, cloud):
    cloud.session.auth.get_access.side_effect = (
        keystoneauth1.exceptions.ConnectFailure("refused")
    )
    assert trail(client, f"/projects/{PROJECT}/servers") == ["Projects", PROJECT]


def test_an_unnamed_project_falls_back_to_its_id(client, cloud):
    cloud.session.auth.get_access.return_value.project_name = None
    assert trail(client, f"/projects/{PROJECT}/servers") == ["Projects", PROJECT]


def test_a_missing_name_raises_no_banner(client, cloud):
    """An id in the trail is a label, not a gap worth warning about."""
    cloud.session.auth.get_access.return_value.project_name = None
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    assert "Shown without" not in page
