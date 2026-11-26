"""Narrowing a listing the way the CLI narrows one."""

import operator
import re
import types
import unittest.mock as mock

import pytest

from stratus import auth, resources

PROJECT = "54766a28ae56492591852dc1b53e9b66"
LOGGED_IN = {
    "auth_url": "https://keystone.test/v3",
    "username": "admin",
    "user_domain_name": "Default",
    "token": "a-token",
}

# What the CLI offers for each kind, checked against its own --help.
NARROWABLE = {"servers", "images", "networks", "volumes"}
WIDENABLE = {"servers", "volumes"}


def primary_calls(resource):
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
    for resource in resources.CATALOGUE.values():
        index, _ = primary_calls(resource)
        operator.attrgetter(index)(connection).return_value = []
    with mock.patch("stratus.auth.connection", return_value=connection):
        yield connection


def query_sent(cloud, kind):
    index, _ = primary_calls(resources.CATALOGUE[kind])
    return operator.attrgetter(index)(cloud).call_args.kwargs


def headers(page):
    return re.findall(r"<th>(.*?)</th>", page)


class TestWhatReachesTheCloud:
    @pytest.mark.parametrize("kind", sorted(NARROWABLE))
    def test_a_name_is_passed_along(self, client, cloud, kind):
        client.get(f"/projects/{PROJECT}/{kind}?name=plum")
        assert query_sent(cloud, kind)["name"] == "plum"

    @pytest.mark.parametrize("kind", sorted(NARROWABLE))
    def test_a_status_is_passed_along(self, client, cloud, kind):
        client.get(f"/projects/{PROJECT}/{kind}?status=ACTIVE")
        assert query_sent(cloud, kind)["status"] == "ACTIVE"

    @pytest.mark.parametrize("kind", sorted(resources.CATALOGUE))
    def test_an_undeclared_parameter_is_dropped(self, client, cloud, kind):
        """Otherwise an address bar hands keywords straight to the SDK."""
        client.get(
            f"/projects/{PROJECT}/{kind}"
            "?all_tenants=1&deleted=1&limit=99999&sort_key=id&nonsense=x"
        )
        sent = query_sent(cloud, kind)
        for uninvited in ("all_tenants", "deleted", "limit", "sort_key", "nonsense"):
            assert uninvited not in sent

    @pytest.mark.parametrize("kind", sorted(resources.CATALOGUE))
    def test_an_empty_filter_is_not_a_filter(self, client, cloud, kind):
        client.get(f"/projects/{PROJECT}/{kind}?name=&status=%20%20")
        sent = query_sent(cloud, kind)
        assert "name" not in sent and "status" not in sent

    def test_whitespace_around_a_paste_is_forgiven(self, client, cloud):
        client.get(f"/projects/{PROJECT}/servers?name=%20plum%0A")
        assert query_sent(cloud, "servers")["name"] == "plum"

    @pytest.mark.parametrize("kind", sorted(WIDENABLE))
    def test_all_projects_reaches_the_ones_that_have_it(self, client, cloud, kind):
        client.get(f"/projects/{PROJECT}/{kind}?all_projects=1")
        assert query_sent(cloud, kind)["all_projects"] is True

    @pytest.mark.parametrize(
        "kind", sorted(set(resources.CATALOGUE) - WIDENABLE)
    )
    def test_and_not_the_ones_that_do_not(self, client, cloud, kind):
        """Glance and neutron have no such flag; the SDK would reject it."""
        client.get(f"/projects/{PROJECT}/{kind}?all_projects=1")
        assert "all_projects" not in query_sent(cloud, kind)

    def test_flavors_take_no_filters_at_all(self, client, cloud):
        """`flavor list` has neither --name nor --status."""
        client.get(f"/projects/{PROJECT}/flavors?name=m1.nano&status=x")
        sent = query_sent(cloud, "flavors")
        assert sent == {"is_public": True}


class TestTheExtraColumn:
    def a_server(self, project):
        return types.SimpleNamespace(
            id=f"s-{project}",
            name="plum",
            status="ACTIVE",
            addresses={},
            image=None,
            flavor=types.SimpleNamespace(original_name="m1.nano", id="42"),
            project_id=project,
        )

    def test_servers_gain_a_project_id_across_projects(self, client, cloud):
        cloud.compute.servers.return_value = [self.a_server("other")]
        page = client.get(
            f"/projects/{PROJECT}/servers?all_projects=1"
        ).get_data(as_text=True)
        assert headers(page)[-1] == "Project ID"
        assert "other" in page

    def test_and_not_within_one(self, client, cloud):
        cloud.compute.servers.return_value = [self.a_server(PROJECT)]
        page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
        assert "Project ID" not in headers(page)

    def test_volumes_do_not_gain_one(self, client, cloud):
        """`volume list --all-projects` adds no column, unlike server list."""
        page = client.get(
            f"/projects/{PROJECT}/volumes?all_projects=1"
        ).get_data(as_text=True)
        assert headers(page) == ["ID", "Name", "Status", "Size", "Attached to"]


class TestTheForm:
    @pytest.mark.parametrize("kind", sorted(NARROWABLE))
    def test_it_offers_what_the_kind_understands(self, client, cloud, kind):
        page = client.get(f"/projects/{PROJECT}/{kind}").get_data(as_text=True)
        assert 'name="name"' in page
        assert 'name="status"' in page

    @pytest.mark.parametrize("kind", sorted(WIDENABLE))
    def test_it_offers_all_projects_where_there_is_one(self, client, cloud, kind):
        page = client.get(f"/projects/{PROJECT}/{kind}").get_data(as_text=True)
        assert 'name="all_projects"' in page

    def test_flavors_get_no_form(self, client, cloud):
        page = client.get(f"/projects/{PROJECT}/flavors").get_data(as_text=True)
        assert 'class="filters"' not in page

    def test_it_remembers_what_was_asked(self, client, cloud):
        page = client.get(
            f"/projects/{PROJECT}/servers?name=plum&all_projects=1"
        ).get_data(as_text=True)
        assert 'value="plum"' in page
        assert "checked" in page

    def test_a_filtered_listing_offers_a_way_back(self, client, cloud):
        page = client.get(f"/projects/{PROJECT}/servers?name=plum").get_data(
            as_text=True
        )
        assert f'href="/projects/{PROJECT}/servers"' in page

    def test_an_unfiltered_one_does_not(self, client, cloud):
        page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
        assert 'class="clear"' not in page
