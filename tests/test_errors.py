"""Every way the cloud can fail, and the page it turns into."""

import types
import unittest.mock as mock

import keystoneauth1.exceptions
import openstack.exceptions
import pytest

from stratus import auth

PROJECT = "54766a28ae56492591852dc1b53e9b66"
SERVERS = f"/projects/{PROJECT}/servers"
LOGGED_IN = {
    "auth_url": "https://keystone.test/v3",
    "username": "admin",
    "user_domain_name": "Default",
    "token": "a-token",
}


@pytest.fixture
def cloud(client):
    with client.session_transaction() as session:
        session[auth.CLOUD] = LOGGED_IN
    connection = mock.MagicMock()
    connection.session.get_user_id.return_value = "a-user"
    connection.compute.servers.return_value = []
    with mock.patch("stratus.auth.connection", return_value=connection):
        yield connection


def failing(cloud, error):
    cloud.compute.servers.side_effect = error


class TestTokenIsFinished:
    """A token that has aged out ends the session wherever it shows up."""

    def test_keystone_saying_so(self, client, cloud):
        failing(cloud, keystoneauth1.exceptions.Unauthorized())
        assert client.get(SERVERS).headers["Location"] == "/login"
        with client.session_transaction() as session:
            assert auth.CLOUD not in session

    def test_another_service_saying_so(self, client, cloud):
        """A 401 out of nova means the same thing as one out of keystone."""
        failing(cloud, openstack.exceptions.HttpException("no", http_status=401))
        assert client.get(SERVERS).headers["Location"] == "/login"
        with client.session_transaction() as session:
            assert auth.CLOUD not in session


class TestDeniedOrAbsent:
    """A refusal and an absence answer alike, so neither maps the cloud."""

    @pytest.mark.parametrize(
        "error",
        [
            openstack.exceptions.ForbiddenException("no"),
            openstack.exceptions.NotFoundException("no"),
            keystoneauth1.exceptions.Forbidden(),
            keystoneauth1.exceptions.NotFound(),
            openstack.exceptions.HttpException("no", http_status=403),
            openstack.exceptions.HttpException("no", http_status=404),
        ],
    )
    def test_all_of_them_are_a_plain_404(self, client, cloud, error):
        failing(cloud, error)
        response = client.get(SERVERS)
        assert response.status_code == 404

    def test_the_page_gives_nothing_away(self, client, cloud):
        failing(cloud, openstack.exceptions.ForbiddenException("no"))
        page = client.get(SERVERS).get_data(as_text=True)
        assert "Forbidden" not in page
        assert "denied" not in page.lower()

    def test_the_session_survives_a_refusal(self, client, cloud):
        failing(cloud, openstack.exceptions.ForbiddenException("no"))
        client.get(SERVERS)
        with client.session_transaction() as session:
            assert auth.CLOUD in session


class TestServiceUnwell:
    @pytest.mark.parametrize(
        "error",
        [
            openstack.exceptions.EndpointNotFound("gone"),
            openstack.exceptions.ServiceDiscoveryException("gone"),
            openstack.exceptions.ServiceDisabledException("off"),
            openstack.exceptions.ResourceTimeout("slow"),
            keystoneauth1.exceptions.ConnectFailure("refused"),
            keystoneauth1.exceptions.ConnectTimeout("slow"),
            keystoneauth1.exceptions.SSLError("bad cert"),
            keystoneauth1.exceptions.DiscoveryFailure("no versions"),
            keystoneauth1.exceptions.ServiceUnavailable(),
            keystoneauth1.exceptions.GatewayTimeout(),
            openstack.exceptions.HttpException("boom", http_status=500),
            openstack.exceptions.HttpException("boom", http_status=503),
        ],
    )
    def test_all_of_them_are_a_503(self, client, cloud, error):
        failing(cloud, error)
        assert client.get(SERVERS).status_code == 503

    def test_the_page_names_the_service(self, client, cloud):
        failing(cloud, openstack.exceptions.EndpointNotFound("gone"))
        page = client.get(SERVERS).get_data(as_text=True)
        assert "compute service is not answering" in page

    def test_each_resource_names_its_own_service(self, client, cloud):
        cloud.block_storage.volumes.side_effect = (
            openstack.exceptions.EndpointNotFound("gone")
        )
        page = client.get(f"/projects/{PROJECT}/volumes").get_data(as_text=True)
        assert "block storage service is not answering" in page

    def test_one_dead_service_leaves_the_others_alone(self, client, cloud):
        """The point of the whole thing: cinder falling over is not fatal."""
        cloud.block_storage.volumes.side_effect = (
            openstack.exceptions.EndpointNotFound("gone")
        )
        cloud.image.images.return_value = []
        assert client.get(f"/projects/{PROJECT}/volumes").status_code == 503
        assert client.get(f"/projects/{PROJECT}/images").status_code == 200
        assert client.get(SERVERS).status_code == 200

    def test_the_session_survives_an_outage(self, client, cloud):
        failing(cloud, keystoneauth1.exceptions.ConnectFailure("refused"))
        client.get(SERVERS)
        with client.session_transaction() as session:
            assert auth.CLOUD in session


class TestUnexpected:
    @pytest.fixture(autouse=True)
    def deployed(self, app):
        """As a deployment runs: a bug becomes a page, not a traceback.

        Under `flask run --debug`, and in these tests by default, the same
        bug is re-raised instead so the debugger can have it.
        """
        app.config["PROPAGATE_EXCEPTIONS"] = False

    def test_an_ordinary_bug_is_a_500(self, client, cloud):
        failing(cloud, TypeError("a real bug"))
        assert client.get(SERVERS).status_code == 500

    def test_a_bug_is_raised_for_the_debugger_when_asked(self, app, client, cloud):
        """What `flask run --debug` needs: the exception, not an apology."""
        app.config["PROPAGATE_EXCEPTIONS"] = True
        failing(cloud, TypeError("a real bug"))
        with pytest.raises(TypeError, match="a real bug"):
            client.get(SERVERS)

    def test_the_page_carries_an_id_that_reaches_the_log(self, client, cloud, caplog):
        failing(cloud, TypeError("a real bug"))
        page = client.get(SERVERS).get_data(as_text=True)
        shown = page.split('class="ticket">')[1].split("<")[0].strip()
        assert len(shown) == 12
        assert shown in caplog.text

    def test_the_traceback_reaches_the_log_too(self, client, cloud, caplog):
        failing(cloud, TypeError("a real bug"))
        client.get(SERVERS)
        assert "TypeError" in caplog.text
        assert "a real bug" in caplog.text

    def test_two_requests_are_told_apart(self, client, cloud):
        failing(cloud, TypeError("a real bug"))
        ids = []
        for _ in range(2):
            page = client.get(SERVERS).get_data(as_text=True)
            ids.append(page.split('class="ticket">')[1].split("<")[0].strip())
        assert ids[0] != ids[1]

    def test_a_bad_request_is_not_mistaken_for_an_outage(self, client, cloud):
        """A 400 is this application's fault, not the service's."""
        failing(cloud, openstack.exceptions.BadRequestException("no", http_status=400))
        assert client.get(SERVERS).status_code == 500


class TestScoping:
    def test_a_project_that_cannot_be_entered_is_a_404(self, client, cloud):
        """Rescoping is refused, but the token itself is still good."""
        cloud.session.get_token.side_effect = keystoneauth1.exceptions.Unauthorized()
        response = client.get(f"/projects/{PROJECT}")
        assert response.status_code == 404
        with client.session_transaction() as session:
            assert auth.CLOUD in session

    def test_a_finished_token_still_ends_the_session(self, client, cloud):
        cloud.session.get_token.side_effect = keystoneauth1.exceptions.Unauthorized()
        cloud.session.get_user_id.side_effect = (
            keystoneauth1.exceptions.Unauthorized()
        )
        assert client.get(f"/projects/{PROJECT}").headers["Location"] == "/login"

    def test_a_refusal_from_the_service_is_not_blamed_on_the_project(
        self, client, cloud
    ):
        """Scoping worked, so a later 401 means the token, not the project."""
        cloud.compute.servers.side_effect = keystoneauth1.exceptions.Unauthorized()
        assert client.get(SERVERS).headers["Location"] == "/login"


class TestSideLookups:
    """A page's secondary call must not take the page down with it."""

    def test_a_dead_glance_still_leaves_a_server_list(self, client, cloud):
        cloud.compute.servers.return_value = [
            types.SimpleNamespace(
                id="s-1",
                name="plum",
                status="ACTIVE",
                addresses={},
                image=types.SimpleNamespace(id="img-1"),
                flavor=types.SimpleNamespace(original_name="m1.nano", id="42"),
            )
        ]
        cloud.image.get_image.side_effect = openstack.exceptions.EndpointNotFound("x")
        response = client.get(SERVERS)
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert "plum" in page
        assert "img-1" in page  # the id stands in for the name it could not get

    def test_a_dead_nova_still_leaves_a_volume_list(self, client, cloud):
        cloud.block_storage.volumes.return_value = [
            types.SimpleNamespace(
                id="v-1",
                name="root",
                status="in-use",
                size=1,
                attachments=[{"server_id": "s-1", "device": "/dev/vda"}],
            )
        ]
        cloud.compute.servers.side_effect = openstack.exceptions.EndpointNotFound("x")
        response = client.get(f"/projects/{PROJECT}/volumes")
        assert response.status_code == 200
        assert "Attached to s-1 on /dev/vda" in response.get_data(as_text=True)
