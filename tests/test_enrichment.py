"""An extra lookup may fail. The page it decorates may not."""

import types
import unittest.mock as mock

import keystoneauth1.exceptions
import openstack.exceptions
import pytest

from stratus import auth, errors, resources

PROJECT = "54766a28ae56492591852dc1b53e9b66"
LOGGED_IN = {
    "auth_url": "https://keystone.test/v3",
    "username": "admin",
    "user_domain_name": "Default",
    "token": "a-token",
}

# Every way a cloud can refuse, from both trees. The keystoneauth ones are
# the point: a service that is merely unreachable raises from there, and
# none of them is an SDKException.
REFUSALS = [
    openstack.exceptions.EndpointNotFound("gone"),
    openstack.exceptions.NotFoundException("gone"),
    openstack.exceptions.ForbiddenException("no"),
    openstack.exceptions.ServiceDisabledException("off"),
    keystoneauth1.exceptions.ConnectFailure("refused"),
    keystoneauth1.exceptions.ConnectTimeout("slow"),
    keystoneauth1.exceptions.SSLError("bad cert"),
    keystoneauth1.exceptions.ServiceUnavailable(),
    keystoneauth1.exceptions.DiscoveryFailure("no versions"),
]


@pytest.fixture
def cloud(client):
    with client.session_transaction() as session:
        session[auth.CLOUD] = LOGGED_IN
    connection = mock.MagicMock()
    connection.session.get_user_id.return_value = "a-user"
    with mock.patch("stratus.auth.connection", return_value=connection):
        yield connection


def a_server():
    return types.SimpleNamespace(
        id="s-1",
        name="plum",
        status="ACTIVE",
        addresses={},
        image=types.SimpleNamespace(id="img-1"),
        flavor=types.SimpleNamespace(original_name="m1.nano", id="42"),
    )


def a_volume():
    return types.SimpleNamespace(
        id="v-1",
        name="root",
        status="in-use",
        size=1,
        attachments=[{"server_id": "s-1", "device": "/dev/vda"}],
    )


@pytest.mark.parametrize("refusal", REFUSALS, ids=lambda e: type(e).__name__)
class TestAListingSurvivesIt:
    def test_servers_fall_back_to_the_image_id(self, client, cloud, refusal):
        cloud.compute.servers.return_value = [a_server()]
        cloud.image.get_image.side_effect = refusal
        response = client.get(f"/projects/{PROJECT}/servers")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert "plum" in page
        assert "img-1" in page

    def test_volumes_fall_back_to_the_server_id(self, client, cloud, refusal):
        cloud.block_storage.volumes.return_value = [a_volume()]
        cloud.compute.servers.side_effect = refusal
        response = client.get(f"/projects/{PROJECT}/volumes")
        assert response.status_code == 200
        assert "Attached to s-1 on /dev/vda" in response.get_data(as_text=True)


@pytest.mark.parametrize("refusal", REFUSALS, ids=lambda e: type(e).__name__)
class TestAShowPageSurvivesIt:
    def test_a_server_falls_back_to_the_image_id(self, cloud, refusal):
        server = mock.MagicMock()
        server.to_dict.return_value = {"id": "s-1", "image": {"id": "img-1"}}
        cloud.image.get_image.side_effect = refusal
        assert dict(resources.server_details(cloud, server))["image"] == "img-1"

    def test_a_private_flavor_leaves_its_access_list_blank(self, cloud, refusal):
        flavor = mock.MagicMock(is_public=False, id="secret")
        flavor.to_dict.return_value = {"id": "secret"}
        cloud.compute.get_flavor_access.side_effect = refusal
        shown = dict(resources.flavor_details(cloud, flavor))
        assert shown["access_project_ids"] == ""


class TestTheContract:
    def test_a_resource_without_an_enrichment_wants_nothing(self, cloud):
        assert resources.CATALOGUE["images"].enrich is None
        assert resources.CATALOGUE["images"].extras(cloud, []) == {}

    def test_an_enrichment_that_fails_yields_nothing_not_an_error(self, cloud):
        resource = resources.CATALOGUE["servers"]
        cloud.image.get_image.side_effect = keystoneauth1.exceptions.ConnectFailure(
            "refused"
        )
        assert resource.extras(cloud, [a_server()]) == {}

    def test_the_wrapper_catches_both_trees_and_nothing_else(self):
        """A bug in here is not weather and must not be swallowed."""
        assert errors.optionally(lambda: "fine", "fallback") == "fine"
        for refusal in REFUSALS:
            def raise_it(e=refusal):
                raise e

            assert errors.optionally(raise_it, "fallback") == "fallback"
        with pytest.raises(TypeError):
            errors.optionally(lambda: 1 + "one", "fallback")

    def test_one_unreadable_image_costs_only_its_own_name(self, client, cloud):
        """Per image, so a single deleted one does not blank the column."""
        second = a_server()
        second.id, second.name = "s-2", "cherry"
        second.image = types.SimpleNamespace(id="img-2")
        cloud.compute.servers.return_value = [a_server(), second]
        def answer_for(identifier):
            # Keyed by id, not by call order: the ids come out of a set.
            if identifier == "img-1":
                raise openstack.exceptions.NotFoundException("gone")
            return types.SimpleNamespace(id=identifier, name="cirros")

        cloud.image.get_image.side_effect = answer_for
        page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
        assert "cirros" in page  # the one that answered
        assert "img-1" in page  # the one that did not

    def test_the_primary_call_still_fails_the_page(self, client, cloud):
        """Enrichment is forgiven. The listing itself is not."""
        cloud.compute.servers.side_effect = keystoneauth1.exceptions.ConnectFailure(
            "refused"
        )
        assert client.get(f"/projects/{PROJECT}/servers").status_code == 503


class TestSayingSo:
    """A blank from a failure must not read as a blank that is true."""

    def test_the_page_names_what_it_could_not_fetch(self, client, cloud):
        cloud.compute.servers.return_value = [a_server()]
        cloud.image.get_image.side_effect = keystoneauth1.exceptions.ConnectFailure(
            "refused"
        )
        page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
        flowed = " ".join(page.split())  # the notice wraps in the markup
        assert "Shown without image names" in flowed
        assert "did not answer" in flowed

    def test_a_whole_page_says_nothing_when_nothing_failed(self, client, cloud):
        cloud.compute.servers.return_value = [a_server()]
        cloud.image.get_image.return_value = types.SimpleNamespace(
            id="img-1", name="cirros"
        )
        page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
        assert "Shown without" not in page

    def test_a_flavor_says_what_it_could_not_find_out(self, client, cloud):
        flavor = mock.MagicMock(is_public=False, id="secret", name="secret")
        flavor.to_dict.return_value = {"id": "secret", "name": "secret"}
        cloud.compute.get_flavor.return_value = flavor
        cloud.compute.get_flavor_access.side_effect = (
            keystoneauth1.exceptions.ConnectFailure("refused")
        )
        page = client.get(f"/projects/{PROJECT}/flavors/secret").get_data(as_text=True)
        assert "which projects may use this flavor" in page

    def test_one_gap_is_named_once_however_many_times_it_happens(
        self, client, cloud
    ):
        second = a_server()
        second.id, second.image = "s-2", types.SimpleNamespace(id="img-2")
        cloud.compute.servers.return_value = [a_server(), second]
        cloud.image.get_image.side_effect = keystoneauth1.exceptions.ConnectFailure(
            "refused"
        )
        page = client.get(f"/projects/{PROJECT}/servers").get_data(as_text=True)
        assert page.count("Shown without image names") == 1

    def test_a_gap_does_not_follow_the_next_request(self, client, cloud):
        cloud.compute.servers.return_value = [a_server()]
        cloud.image.get_image.side_effect = keystoneauth1.exceptions.ConnectFailure(
            "refused"
        )
        assert "Shown without" in client.get(
            f"/projects/{PROJECT}/servers"
        ).get_data(as_text=True)
        cloud.image.get_image.side_effect = None
        cloud.image.get_image.return_value = types.SimpleNamespace(
            id="img-1", name="cirros"
        )
        assert "Shown without" not in client.get(
            f"/projects/{PROJECT}/servers"
        ).get_data(as_text=True)

    def test_the_log_says_so_loudly_enough_to_be_seen(self, client, cloud, caplog):
        """INFO is dropped by a default root logger. A gap is a warning."""
        import logging

        cloud.compute.servers.return_value = [a_server()]
        cloud.image.get_image.side_effect = keystoneauth1.exceptions.ConnectFailure(
            "refused"
        )
        with caplog.at_level(logging.WARNING):
            client.get(f"/projects/{PROJECT}/servers")
        assert "could not fetch image names" in caplog.text

    def test_the_log_line_carries_the_request_id(self, client, cloud, caplog):
        import logging

        cloud.compute.servers.return_value = [a_server()]
        cloud.image.get_image.side_effect = keystoneauth1.exceptions.ConnectFailure(
            "refused"
        )
        with caplog.at_level(logging.WARNING):
            client.get(f"/projects/{PROJECT}/servers")
        warned = [r for r in caplog.records if "could not fetch" in r.message]
        assert warned and warned[0].args[1] != "untagged"
