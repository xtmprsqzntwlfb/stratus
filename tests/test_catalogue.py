"""The registry, and the resources reached through it."""

import types
import unittest.mock as mock

import openstack.exceptions
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
    assert client.get(f"/projects/{PROJECT}/hovercraft").status_code == 404


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


def a_flavor(name, **extra):
    fields = {
        "id": f"id-{name}",
        "name": name,
        "ram": 128,
        "disk": 1,
        "ephemeral": 0,
        "vcpus": 1,
        "is_public": True,
    }
    fields.update(extra)
    return types.SimpleNamespace(**fields)


def a_volume(name, attachments=(), **extra):
    fields = {
        "id": f"id-{name}",
        "name": name,
        "status": "available",
        "size": 1,
        "attachments": list(attachments),
    }
    fields.update(extra)
    return types.SimpleNamespace(**fields)


class TestFlavors:
    def test_the_columns_are_the_ones_the_cli_prints(self, client, cloud):
        cloud.compute.flavors.return_value = [a_flavor("m1.nano")]
        page = client.get(f"/projects/{PROJECT}/flavors").get_data(as_text=True)
        assert headers(page) == [
            "ID",
            "Name",
            "RAM",
            "Disk",
            "Ephemeral",
            "VCPUs",
            "Is Public",
        ]

    def test_only_public_flavors_are_asked_for(self, client, cloud):
        """What the CLI asks for unless told --all or --private."""
        cloud.compute.flavors.return_value = [a_flavor("m1.nano")]
        client.get(f"/projects/{PROJECT}/flavors")
        cloud.compute.flavors.assert_called_once_with(is_public=True)

    def test_the_sdk_copy_of_the_name_is_left_out(self, cloud):
        flavor = mock.MagicMock(is_public=True)
        flavor.to_dict.return_value = {
            "id": "m1.nano",
            "name": "m1.nano",
            "original_name": "m1.nano",
            "extra_specs": {"hw_rng:allowed": True},
        }
        shown = dict(resources.flavor_details(cloud, flavor))
        assert "original_name" not in shown
        assert shown["extra_specs"] == "hw_rng:allowed=True"

    def test_a_public_flavor_is_not_asked_who_may_use_it(self, cloud):
        flavor = mock.MagicMock(is_public=True)
        flavor.to_dict.return_value = {"id": "m1.nano"}
        shown = dict(resources.flavor_details(cloud, flavor))
        assert shown["access_project_ids"] is None
        cloud.compute.get_flavor_access.assert_not_called()

    def test_a_private_flavor_lists_the_projects_allowed_it(self, cloud):
        flavor = mock.MagicMock(is_public=False, id="secret")
        flavor.to_dict.return_value = {"id": "secret"}
        cloud.compute.get_flavor_access.return_value = [
            {"tenant_id": "p-1"},
            {"tenant_id": "p-2"},
        ]
        shown = dict(resources.flavor_details(cloud, flavor))
        assert shown["access_project_ids"] == "p-1, p-2"
        cloud.compute.get_flavor_access.assert_called_once_with("secret")


class TestVolumes:
    def test_the_columns_are_the_ones_the_cli_prints(self, client, cloud):
        cloud.block_storage.volumes.return_value = [a_volume("spare")]
        page = client.get(f"/projects/{PROJECT}/volumes").get_data(as_text=True)
        assert headers(page) == ["ID", "Name", "Status", "Size", "Attached to"]

    def test_an_attachment_names_the_server_it_is_on(self, client, cloud):
        cloud.block_storage.volumes.return_value = [
            a_volume("root", [{"server_id": "s-1", "device": "/dev/vda"}])
        ]
        cloud.compute.servers.return_value = [
            types.SimpleNamespace(id="s-1", name="plum")
        ]
        page = client.get(f"/projects/{PROJECT}/volumes").get_data(as_text=True)
        assert "Attached to plum on /dev/vda" in page

    def test_an_unknown_server_falls_back_to_its_id(self, client, cloud):
        cloud.block_storage.volumes.return_value = [
            a_volume("root", [{"server_id": "s-9", "device": "/dev/vda"}])
        ]
        cloud.compute.servers.return_value = []
        page = client.get(f"/projects/{PROJECT}/volumes").get_data(as_text=True)
        assert "Attached to s-9 on /dev/vda" in page

    def test_servers_are_not_listed_when_nothing_is_attached(self, client, cloud):
        cloud.block_storage.volumes.return_value = [a_volume("spare")]
        client.get(f"/projects/{PROJECT}/volumes")
        cloud.compute.servers.assert_not_called()

    def test_create_only_and_dead_fields_are_left_out(self, cloud):
        volume = mock.MagicMock()
        volume.to_dict.return_value = {
            "id": "v", "name": "root", "size": 1,
            "scheduler_hints": "dropped", "image_id": "dropped",
            "replication_driver_data": "dropped",
            "extended_replication_status": "dropped",
            "encryption_key_id": None,
        }
        shown = dict(resources.volume_details(cloud, volume))
        for gone in ("scheduler_hints", "image_id", "replication_driver_data",
                     "extended_replication_status", "encryption_key_id"):
            assert gone not in shown
        assert shown["size"] == 1


def a_project():
    return types.SimpleNamespace(
        id=PROJECT, name="admin", description="", domain_id="default",
        is_enabled=True, is_domain=False, options={}, parent_id="default", tags=[],
    )


def catalogue(cloud, *types_):
    """Tell the token's catalogue which services this cloud runs."""
    cloud.identity.get_project.return_value = a_project()
    access = cloud.session.auth.get_access.return_value
    access.service_catalog.catalog = [{"type": t} for t in types_]


class TestWhatTheCloudRuns:
    EVERYTHING = ("identity", "compute", "image", "network", "block-storage")

    def page(self, client, cloud, *services):
        catalogue(cloud, *services)
        return client.get(f"/projects/{PROJECT}").get_data(as_text=True)

    def test_a_full_cloud_offers_every_kind(self, client, cloud):
        page = self.page(client, cloud, *self.EVERYTHING)
        for slug in resources.CATALOGUE:
            assert f'href="/projects/{PROJECT}/{slug}"' in page

    def test_a_service_the_cloud_lacks_is_not_linked(self, client, cloud):
        page = self.page(client, cloud, "identity", "compute", "image", "network")
        assert f'href="/projects/{PROJECT}/volumes"' not in page

    def test_and_it_says_why_rather_than_vanishing(self, client, cloud):
        page = self.page(client, cloud, "identity", "compute", "image", "network")
        assert "no block storage service on this cloud" in page

    def test_one_absent_service_leaves_the_others_linked(self, client, cloud):
        """The point of it: no neutron must not cost you servers."""
        page = self.page(client, cloud, "identity", "compute", "image", "block-storage")
        assert f'href="/projects/{PROJECT}/networks"' not in page
        for still_there in ("servers", "images", "volumes", "flavors"):
            assert f'href="/projects/{PROJECT}/{still_there}"' in page

    def test_an_old_cloud_naming_cinder_volumev3_still_counts(self, client, cloud):
        page = self.page(client, cloud, "identity", "compute", "volumev3")
        assert f'href="/projects/{PROJECT}/volumes"' in page

    def test_an_empty_catalogue_offers_everything(self, client, cloud):
        """Unanswerable, so offer the lot rather than withhold in silence."""
        page = self.page(client, cloud)
        for slug in resources.CATALOGUE:
            assert f'href="/projects/{PROJECT}/{slug}"' in page

    def test_deciding_costs_no_requests(self, client, cloud):
        self.page(client, cloud, *self.EVERYTHING)
        cloud.has_service.assert_not_called()
        cloud.compute.servers.assert_not_called()
        cloud.block_storage.volumes.assert_not_called()

    def test_a_listed_service_is_still_reachable_when_it_is_unwell(
        self, client, cloud
    ):
        """Listed but silent is the 503's job, not the project page's."""
        catalogue(cloud, *self.EVERYTHING)
        cloud.block_storage.volumes.side_effect = (
            openstack.exceptions.EndpointNotFound("silent")
        )
        page = client.get(f"/projects/{PROJECT}").get_data(as_text=True)
        assert f'href="/projects/{PROJECT}/volumes"' in page
        assert client.get(f"/projects/{PROJECT}/volumes").status_code == 503
