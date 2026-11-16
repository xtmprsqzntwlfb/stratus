"""The registry, and the resources reached through it."""

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


def an_image(name, **extra):
    fields = {"id": f"id-{name}", "name": name, "status": "active"}
    fields.update(extra)
    return types.SimpleNamespace(**fields)


def a_network(name, subnets=()):
    return types.SimpleNamespace(id=f"id-{name}", name=name, subnet_ids=list(subnets))


@pytest.fixture
def cloud(client):
    with client.session_transaction() as session:
        session[auth.CLOUD] = LOGGED_IN
    connection = mock.MagicMock()
    connection.session.get_user_id.return_value = "a-user"
    connection.compute.servers.return_value = []
    connection.image.images.return_value = [
        an_image("zzz"),
        an_image("fakeimage"),
        an_image("cirros-0.6.3-x86_64-disk"),
    ]
    connection.network.networks.return_value = [
        a_network("public", ["sub-a", "sub-b"]),
        a_network("shared", ["sub-c"]),
    ]
    with mock.patch("stratus.auth.connection", return_value=connection):
        yield connection


def headers(page):
    import re

    return re.findall(r"<th>(.*?)</th>", page)


def test_an_unknown_kind_is_not_found(client, cloud):
    assert client.get(f"/projects/{PROJECT}/volumes").status_code == 404


def test_every_kind_in_the_registry_has_a_page(client, cloud):
    for slug in resources.CATALOGUE:
        assert client.get(f"/projects/{PROJECT}/{slug}").status_code == 200


def test_the_project_page_links_to_each_kind(client, cloud):
    cloud.identity.get_project.return_value = types.SimpleNamespace(
        id=PROJECT,
        name="admin",
        description="",
        domain_id="default",
        is_enabled=True,
        is_domain=False,
        options={},
        parent_id="default",
        tags=[],
    )
    page = client.get(f"/projects/{PROJECT}").get_data(as_text=True)
    for slug in resources.CATALOGUE:
        assert f'href="/projects/{PROJECT}/{slug}"' in page


class TestImages:
    def test_the_columns_are_the_ones_the_cli_prints(self, client, cloud):
        page = client.get(f"/projects/{PROJECT}/images").get_data(as_text=True)
        assert headers(page) == ["ID", "Name", "Status"]

    def test_images_are_sorted_by_name(self, client, cloud):
        """`image list` defaults to --sort name:asc and reorders glance."""
        page = client.get(f"/projects/{PROJECT}/images").get_data(as_text=True)
        order = [page.index(n) for n in ("cirros-0.6.3", "fakeimage", "zzz")]
        assert order == sorted(order)

    def test_unset_properties_are_left_out(self, cloud):
        """The SDK declares every property an image could carry."""
        image = mock.MagicMock()
        image.to_dict.return_value = {"id": "i", "name": "n", "status": "active"}
        resources.image_details(cloud, image)
        image.to_dict.assert_called_once_with(ignore_none=True)


class TestNetworks:
    def test_the_columns_are_the_ones_the_cli_prints(self, client, cloud):
        page = client.get(f"/projects/{PROJECT}/networks").get_data(as_text=True)
        assert headers(page) == ["ID", "Name", "Subnets"]

    def test_subnets_are_joined(self, client, cloud):
        page = client.get(f"/projects/{PROJECT}/networks").get_data(as_text=True)
        assert "sub-a, sub-b" in page

    def test_networks_keep_the_order_neutron_sent(self, client, cloud):
        """Unlike `image list`, `network list` does not sort."""
        page = client.get(f"/projects/{PROJECT}/networks").get_data(as_text=True)
        assert page.index("public") < page.index("shared")

    def test_the_sdk_only_fields_are_left_out(self, cloud):
        network = mock.MagicMock()
        network.to_dict.return_value = {
            "id": "n",
            "name": "public",
            "if_match": "dropped",
            "tenant_id": "dropped",
            "location": "dropped",
            "project_id": "kept",
        }
        shown = dict(resources.network_details(cloud, network))
        assert shown["project_id"] == "kept"
        for gone in ("if_match", "tenant_id", "location"):
            assert gone not in shown
