"""The server list and the server page, against what the CLI prints."""

import types
import unittest.mock as mock

import openstack.exceptions
import pytest

from stratus import auth, resources

PROJECT = "81741bf155af4b1685825d7e8850a56b"
IMAGE = "3c1b0b36-2a0e-4e2c-9a1a-1f1d1f6b0f11"

LOGGED_IN = {
    "auth_url": "https://keystone.test/v3",
    "username": "demo",
    "user_domain_name": "Default",
    "token": "a-token",
}


def a_server(**overrides):
    fields = {
        "id": "7b7f9b2e-1111-2222-3333-444455556666",
        "name": "worker",
        "status": "ACTIVE",
        "addresses": {"private": [{"addr": "10.0.0.5"}, {"addr": "fd00::5"}]},
        "image": types.SimpleNamespace(id=IMAGE),
        "flavor": types.SimpleNamespace(original_name="m1.nano", id="42"),
    }
    fields.update(overrides)
    return types.SimpleNamespace(**fields)


@pytest.fixture
def cloud(client):
    with client.session_transaction() as session:
        session[auth.CLOUD] = LOGGED_IN
    connection = mock.MagicMock()
    connection.session.get_user_id.return_value = "a-user"
    connection.compute.servers.return_value = [a_server()]
    connection.image.get_image.return_value = types.SimpleNamespace(
        id=IMAGE, name="cirros-0.6.3-x86_64-disk"
    )
    with mock.patch("stratus.auth.connection", return_value=connection):
        yield connection


def test_the_server_list_needs_a_login(client):
    response = client.get(f"/projects/{PROJECT}/servers")
    assert response.headers["Location"].startswith("/login?next=")


def test_the_list_is_scoped_to_the_project_in_the_path(client, cloud):
    with mock.patch("stratus.auth.connection", return_value=cloud) as connect:
        client.get(f"/projects/{PROJECT}/servers")
    connect.assert_called_once_with(PROJECT)


def test_the_list_prints_the_columns_the_cli_prints(client, cloud):
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    for label in ("ID", "Name", "Status", "Networks", "Image", "Flavor"):
        assert f"<th>{label}</th>" in page
    assert page.count("<th>") == 6


def test_addresses_are_joined_the_way_the_cli_joins_them(client, cloud):
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    assert "private=10.0.0.5, fd00::5" in page


def test_several_networks_are_separated_by_semicolons(client, cloud):
    cloud.compute.servers.return_value = [
        a_server(
            addresses={
                "public": [{"addr": "172.24.4.9"}],
                "private": [{"addr": "10.0.0.5"}],
            }
        )
    ]
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    # Sorted by network name, as the CLI sorts them.
    assert "private=10.0.0.5; public=172.24.4.9" in page


def test_the_image_column_shows_a_name_not_an_id(client, cloud):
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    assert "cirros-0.6.3-x86_64-disk" in page


def test_each_image_is_fetched_once_however_many_servers_use_it(client, cloud):
    cloud.compute.servers.return_value = [a_server(id="a"), a_server(id="b")]
    client.get(f"/projects/{PROJECT}/servers")
    cloud.image.get_image.assert_called_once_with(IMAGE)
    cloud.image.images.assert_not_called()  # never list the whole cloud


def test_a_vanished_image_falls_back_to_its_id(client, cloud):
    cloud.image.get_image.side_effect = openstack.exceptions.NotFoundException()
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    assert IMAGE in page


def test_a_volume_booted_server_says_so_as_the_cli_does(client, cloud):
    cloud.compute.servers.return_value = [a_server(image=None)]
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    assert resources.NO_IMAGE in page


def test_the_flavor_column_needs_no_extra_request(client, cloud):
    """Compute embeds the flavor from microversion 2.47."""
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    assert "m1.nano" in page
    cloud.compute.find_flavor.assert_not_called()
    cloud.compute.flavors.assert_not_called()


def test_an_older_cloud_falls_back_to_the_flavor_id():
    """Before microversion 2.47 compute sends an id and no name."""
    older = a_server(flavor=types.SimpleNamespace(original_name=None, id="42"))
    assert resources.flavor_of(older) == "42"
    assert resources.flavor_of(a_server()) == "m1.nano"
    assert resources.flavor_of(a_server(flavor=None)) == ""


def test_a_project_with_no_servers_is_told_so(client, cloud):
    cloud.compute.servers.return_value = []
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    assert "No servers in this project" in page


def test_each_server_links_to_its_page(client, cloud):
    page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
    assert f'href="/projects/{PROJECT}/servers/{a_server().id}"' in page


def test_a_missing_server_is_not_found(client, cloud):
    cloud.compute.get_server.side_effect = openstack.exceptions.NotFoundException()
    response = client.get(f"/projects/{PROJECT}/servers/nope")
    assert response.status_code == 404


class TestServerShow:
    """`openstack server show` prints the whole resource, renamed and sorted."""

    def details(self, connection, **overrides):
        raw = {
            "id": "7b7f",
            "name": "worker",
            "status": "ACTIVE",
            "created_at": "2026-11-12T10:00:00Z",
            "updated_at": "2026-11-12T10:01:00Z",
            "power_state": 1,
            "project_id": "a-project",
            "is_locked": False,
            "has_config_drive": "",
            "image": {"id": IMAGE},
            "flavor": {"original_name": "m1.nano"},
            "links": ["dropped"],
            "location": "dropped",
            "image_id": "dropped",
            "flavor_id": "dropped",
            "fault": None,
        }
        raw.update(overrides)
        server = mock.MagicMock()
        server.to_dict.return_value = raw
        return dict(resources.server_details(connection, server))

    def test_sdk_only_keys_are_dropped(self, cloud):
        shown = self.details(cloud)
        for key in ("links", "location", "image_id", "flavor_id"):
            assert key not in shown

    def test_fields_are_renamed_to_what_the_api_calls_them(self, cloud):
        shown = self.details(cloud)
        assert shown["created"] == "2026-11-12T10:00:00Z"
        assert shown["updated"] == "2026-11-12T10:01:00Z"
        assert shown["OS-EXT-STS:power_state"] == "Running"
        assert shown["locked"] is False
        assert shown["config_drive"] == ""
        assert "created_at" not in shown
        assert "power_state" not in shown

    def test_project_id_keeps_its_name(self, cloud):
        """The CLI maps it to tenant_id and then back, so it does not move."""
        shown = self.details(cloud)
        assert shown["project_id"] == "a-project"
        assert "tenant_id" not in shown

    def test_metadata_is_printed_as_properties(self, cloud):
        shown = self.details(cloud, metadata={"role": "web"})
        assert shown["properties"] == {"role": "web"}
        assert "metadata" not in shown

    def test_the_power_state_is_a_word_not_a_number(self, cloud):
        assert self.details(cloud, power_state=4)["OS-EXT-STS:power_state"] == "Shutdown"
        assert self.details(cloud, power_state=99)["OS-EXT-STS:power_state"] == "N/A"

    def test_addresses_are_joined_as_on_the_list_page(self, cloud):
        shown = self.details(
            cloud, addresses={"private": [{"addr": "10.0.0.5"}]}
        )
        assert shown["addresses"] == "private=10.0.0.5"

    def test_an_absent_optional_field_is_left_out(self, cloud):
        assert "fault" not in self.details(cloud)
        assert "fault" in self.details(cloud, fault={"message": "boom"})

    def test_the_image_is_named_and_identified(self, cloud):
        assert self.details(cloud)["image"] == f"cirros-0.6.3-x86_64-disk ({IMAGE})"

    def test_a_volume_booted_server_says_so(self, cloud):
        assert self.details(cloud, image={})["image"] == resources.NO_IMAGE

    def test_fields_come_out_in_alphabetical_order(self, cloud):
        server = mock.MagicMock()
        server.to_dict.return_value = {"name": "n", "id": "i", "image": {}}
        labels = [label for label, _ in resources.server_details(cloud, server)]
        assert labels == sorted(labels)
