"""Doing something, and proving the form came from here."""

import re
import unittest.mock as mock

import keystoneauth1.exceptions
import openstack.exceptions
import pytest

from stratus import auth, csrf, resources

PROJECT = "54766a28ae56492591852dc1b53e9b66"
SERVER = "9ea4b48b-6421-4e1d-8be7-a5ee7b8d654c"
LOGGED_IN = {
    "auth_url": "https://keystone.test/v3",
    "username": "admin",
    "user_domain_name": "Default",
    "token": "a-token",
}
VERBS = [doing.name for doing in resources.CATALOGUE["servers"].actions]


@pytest.fixture
def cloud(client):
    with client.session_transaction() as session:
        session[auth.CLOUD] = LOGGED_IN
    connection = mock.MagicMock()
    connection.session.get_user_id.return_value = "a-user"
    connection.session.auth.get_access.return_value.project_name = "admin"
    found = mock.MagicMock()
    found.id, found.name = SERVER, "plum"
    found.to_dict.return_value = {"id": SERVER, "name": "plum"}
    connection.compute.get_server.return_value = found
    connection.compute.servers.return_value = []
    with mock.patch("stratus.auth.connection", return_value=connection):
        yield connection


def url(action, kind="servers", item=SERVER):
    return f"/projects/{PROJECT}/{kind}/{item}/{action}"


class TestTheGuard:
    def test_a_post_without_a_token_is_turned_away(self, client, cloud):
        response = client.post(url("stop"), csrf_token=False)
        assert response.status_code == 400
        cloud.compute.stop_server.assert_not_called()

    def test_a_post_with_somebody_else_s_token_is_too(self, client, cloud):
        response = client.post(url("stop"), data={csrf.FIELD: "a-token-i-made-up"})
        assert response.status_code == 400
        cloud.compute.stop_server.assert_not_called()

    def test_the_right_token_gets_through(self, client, cloud):
        assert client.post(url("stop")).status_code == 302
        cloud.compute.stop_server.assert_called_once_with(SERVER)

    def test_logging_out_needs_one_as_well(self, client, cloud):
        assert client.post("/logout", csrf_token=False).status_code == 400
        with client.session_transaction() as session:
            assert auth.CLOUD in session

    def test_logging_in_needs_one_as_well(self, client):
        assert client.post("/login", data={"username": "demo"}, csrf_token=False).status_code == 400

    def test_a_get_needs_none(self, client, cloud):
        assert client.get(f"/projects/{PROJECT}/servers").status_code == 200

    def test_the_refusal_says_what_to_do(self, client, cloud):
        page = client.post(url("stop"), csrf_token=False).get_data(as_text=True)
        assert "expired" in page
        assert "Nothing was done" in page

    def test_every_form_carries_one(self, client, cloud):
        """A form without it is a button that cannot work."""
        for page in (
            client.get(f"/projects/{PROJECT}/servers/{SERVER}"),
            client.get(f"/projects/{PROJECT}/servers"),
        ):
            body = page.get_data(as_text=True)
            posting = len(re.findall(r'<form[^>]*method="post"', body))
            assert posting  # there is something to check
            assert posting == body.count('name="csrf_token"')

    def test_the_token_does_not_survive_a_login(self, client, keystone_granted):
        """Nothing crosses that boundary, a stale secret least of all."""
        before = client.token()
        client.post(
            "/login",
            data={
                "auth_url": "https://keystone.test/v3",
                "username": "demo",
                "password": "swordfish",
                "user_domain_name": "Default",
                csrf.FIELD: before,
            },
        )
        with client.session_transaction() as session:
            assert session.get(csrf.FIELD) != before


@pytest.fixture
def keystone_granted():
    import datetime

    granted = mock.Mock(
        auth_token="a-token",
        expires=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    )
    with mock.patch(
        "keystoneauth1.identity.base.BaseIdentityPlugin.get_access",
        return_value=granted,
    ):
        yield


@pytest.mark.parametrize("verb", VERBS)
class TestThePowerVerbs:
    def test_it_reaches_the_cloud(self, client, cloud, verb):
        client.post(url(verb))
        assert getattr(cloud.compute, f"{verb}_server").called

    def test_it_sends_you_back_to_the_thing(self, client, cloud, verb):
        response = client.post(url(verb))
        assert response.headers["Location"] == f"/projects/{PROJECT}/servers/{SERVER}"

    def test_it_says_what_it_did_by_name(self, client, cloud, verb):
        """The message names the server, not the id that was in the URL."""
        page = client.post(url(verb), follow_redirects=True).get_data(as_text=True)
        said = re.search(r'<p class="flash done">(.*?)</p>', page, re.S)
        assert said and "plum" in said.group(1)

    def test_the_thing_is_looked_up_first(self, client, cloud, verb):
        """As the CLI resolves a name before acting, so a bad id is a 404."""
        cloud.compute.get_server.side_effect = (
            openstack.exceptions.NotFoundException("gone")
        )
        assert client.post(url(verb)).status_code == 404
        assert not getattr(cloud.compute, f"{verb}_server").called

    def test_a_refusal_is_reported_not_raised(self, client, cloud, verb):
        """Nova says 409 for a verb that does not apply. Not a bug."""
        getattr(cloud.compute, f"{verb}_server").side_effect = (
            openstack.exceptions.ConflictException("no", http_status=409)
        )
        response = client.post(url(verb), follow_redirects=True)
        assert response.status_code == 200
        assert "was refused" in response.get_data(as_text=True)

    def test_a_bad_request_is_reported_too(self, client, cloud, verb):
        getattr(cloud.compute, f"{verb}_server").side_effect = (
            openstack.exceptions.BadRequestException("no", http_status=400)
        )
        assert client.post(url(verb), follow_redirects=True).status_code == 200

    def test_a_real_outage_is_still_an_outage(self, client, cloud, verb):
        getattr(cloud.compute, f"{verb}_server").side_effect = (
            keystoneauth1.exceptions.ConnectFailure("refused")
        )
        assert client.post(url(verb)).status_code == 503

    def test_an_expired_token_still_ends_the_session(self, client, cloud, verb):
        getattr(cloud.compute, f"{verb}_server").side_effect = (
            keystoneauth1.exceptions.Unauthorized()
        )
        assert client.post(url(verb)).headers["Location"] == "/login"


class TestWhatHasNoActions:
    @pytest.mark.parametrize(
        "kind", [k for k, r in resources.CATALOGUE.items() if not r.actions]
    )
    def test_a_kind_without_them_offers_none(self, client, cloud, kind):
        assert resources.CATALOGUE[kind].actions == ()

    @pytest.mark.parametrize(
        "kind", [k for k, r in resources.CATALOGUE.items() if not r.actions]
    )
    def test_and_will_not_be_talked_into_one(self, client, cloud, kind):
        assert client.post(url("stop", kind=kind, item="an-id")).status_code == 404

    def test_an_invented_verb_is_not_found(self, client, cloud):
        assert client.post(url("destroy")).status_code == 404
        cloud.compute.delete_server.assert_not_called()

    def test_an_action_cannot_be_reached_by_get(self, client, cloud):
        assert client.get(url("stop")).status_code == 405

    def test_an_action_needs_a_login(self, app):
        anonymous = app.test_client()
        response = anonymous.post(url("stop"))
        assert response.headers["Location"].startswith("/login")
