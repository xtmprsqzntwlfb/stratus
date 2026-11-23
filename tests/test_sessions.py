"""The cookie carries a name. The token stays here."""

import base64
import datetime
import unittest.mock as mock

import pytest

from stratus import auth, sessions

CREDENTIALS = {
    "auth_url": "https://keystone.test/v3",
    "username": "demo",
    "password": "swordfish",
    "user_domain_name": "Default",
}
TOKEN = "gAAAAABq83-a-very-secret-bearer-token"


@pytest.fixture
def keystone():
    granted = mock.Mock(
        auth_token=TOKEN,
        expires=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    )
    with mock.patch(
        "keystoneauth1.identity.base.BaseIdentityPlugin.get_access",
        return_value=granted,
    ) as get_access:
        yield get_access


def log_in(client):
    return client.post("/login", data=CREDENTIALS)


def cookie_header(response):
    return response.headers.get("Set-Cookie", "")


def cookie_value(client):
    held = client.get_cookie("stratus")
    return held.value if held else None


class TestTheTokenDoesNotLeave:
    def test_the_cookie_does_not_carry_the_token(self, client, keystone):
        response = log_in(client)
        assert TOKEN not in cookie_header(response)
        assert TOKEN not in str(response.headers)

    def test_nor_does_any_decoding_of_it_reveal_one(self, client, keystone):
        """A signed cookie is readable; this one must have nothing to read."""
        log_in(client)
        raw = cookie_value(client)
        padded = raw + "=" * (-len(raw) % 4)
        for attempt in (
            raw.encode(),
            base64.urlsafe_b64decode(padded.encode(), ),
        ):
            assert TOKEN.encode() not in attempt
            assert b"auth_url" not in attempt

    def test_the_cookie_is_only_an_opaque_name(self, client, keystone):
        log_in(client)
        raw = cookie_value(client)
        assert len(raw) >= 40  # 32 bytes, url-safe encoded
        assert "." not in raw  # not a signed payload, just a name

    def test_the_token_is_on_the_server(self, app, client, keystone):
        log_in(client)
        held = app.session_interface.store.read(cookie_value(client))
        assert held["cloud"]["token"] == TOKEN


class TestCookiePolicy:
    def test_it_is_closed_to_scripts(self, client, keystone):
        assert "HttpOnly" in cookie_header(log_in(client))

    def test_it_does_not_travel_in_clear(self, client, keystone):
        assert "Secure" in cookie_header(log_in(client))

    def test_it_does_not_ride_another_site_s_request(self, client, keystone):
        assert "SameSite=Lax" in cookie_header(log_in(client))

    def test_secure_can_be_turned_off_for_a_plain_http_server(
        self, app, client, keystone
    ):
        app.config["SESSION_COOKIE_SECURE"] = False
        assert "Secure" not in cookie_header(log_in(client))


class TestNames:
    def test_logging_in_takes_a_new_name(self, client, keystone):
        """Session fixation: a name held before the login is not kept."""
        client.set_cookie("stratus", "a-name-planted-beforehand")
        log_in(client)
        assert cookie_value(client) != "a-name-planted-beforehand"

    def test_the_old_record_is_forgotten_on_login(self, app, client, keystone):
        log_in(client)
        first = cookie_value(client)
        log_in(client)
        assert app.session_interface.store.read(first) is None

    def test_a_name_nobody_knows_is_not_a_session(self, client, keystone):
        client.set_cookie("stratus", "a-name-of-my-own-choosing")
        assert client.get("/projects").headers["Location"].startswith("/login")

    def test_two_logins_do_not_share_a_name(self, app, keystone):
        names = set()
        for _ in range(2):
            with app.test_client() as separate:
                log_in(separate)
                names.add(cookie_value(separate))
        assert len(names) == 2


class TestEnding:
    def test_logging_out_forgets_the_record_here(self, app, client, keystone):
        log_in(client)
        name = cookie_value(client)
        client.post("/logout")
        assert app.session_interface.store.read(name) is None

    def test_an_expired_record_is_no_session(self, app, client, keystone):
        log_in(client)
        name = cookie_value(client)
        app.session_interface.store.write(
            name,
            {"cloud": {"token": TOKEN}},
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=1),
        )
        assert client.get("/projects").headers["Location"].startswith("/login")

    def test_the_record_dies_with_the_token(self, app, keystone):
        """Keystone hands out an hour; the record must not outlast it."""
        soon = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=5
        )
        with app.test_request_context():
            session = sessions.Session({sessions.EXPIRY: soon.isoformat()})
            assert app.session_interface.expiry_of(app, session) == soon

    def test_a_session_without_a_token_falls_back_to_the_lifetime(self, app):
        with app.test_request_context():
            when = app.session_interface.expiry_of(app, sessions.Session({"a": 1}))
        assert when > datetime.datetime.now(datetime.timezone.utc)


class TestStore:
    def test_it_forgets_what_has_expired(self):
        store = sessions.ExpiringStore()
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(1)
        store.write("gone", {"a": 1}, past)
        assert store.read("gone") is None
        assert len(store) == 0

    def test_it_keeps_what_has_not(self):
        store = sessions.ExpiringStore()
        ahead = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(1)
        store.write("here", {"a": 1}, ahead)
        assert store.read("here") == {"a": 1}

    def test_a_record_is_a_copy_not_a_handle(self):
        """Nothing a request does to its session leaks into the store."""
        store = sessions.ExpiringStore()
        ahead = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(1)
        contents = {"a": 1}
        store.write("here", contents, ahead)
        contents["a"] = 2
        store.read("here")["a"] = 3
        assert store.read("here") == {"a": 1}

    def test_passing_traffic_sweeps_the_dead(self):
        store = sessions.ExpiringStore()
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(1)
        ahead = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(1)
        for n in range(5):
            store.write(f"old-{n}", {}, past)
        store.write("new", {}, ahead)
        assert len(store) == 1
