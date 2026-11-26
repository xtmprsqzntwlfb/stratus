"""The cookie carries a name. The token stays here."""

import base64
import datetime
import unittest.mock as mock

import pytest

from stratus import sessions

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


@pytest.fixture(params=["memory", "files"])
def store(request, tmp_path):
    """Both stores must behave alike; only their reach differs."""
    if request.param == "memory":
        return sessions.ExpiringStore()
    return sessions.FileStore(tmp_path / "sessions")


def ahead(**kw):
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**kw)


def behind(**kw):
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(**kw)


class TestEitherStore:
    def test_it_keeps_what_has_not_expired(self, store):
        store.write("here", {"a": 1}, ahead(days=1))
        assert store.read("here") == {"a": 1}

    def test_it_forgets_what_has(self, store):
        store.write("gone", {"a": 1}, behind(days=1))
        assert store.read("gone") is None
        assert len(store) == 0

    def test_it_knows_nothing_of_a_name_never_written(self, store):
        assert store.read("never-heard-of-it") is None

    def test_dropping_forgets_it(self, store):
        store.write("here", {"a": 1}, ahead(days=1))
        store.drop("here")
        assert store.read("here") is None

    def test_dropping_what_is_not_there_is_quiet(self, store):
        store.drop("never-heard-of-it")

    def test_a_record_is_a_copy_not_a_handle(self, store):
        contents = {"a": 1}
        store.write("here", contents, ahead(days=1))
        contents["a"] = 2
        store.read("here")["a"] = 3
        assert store.read("here") == {"a": 1}

    def test_passing_traffic_sweeps_the_dead(self, store):
        for n in range(5):
            store.write(f"old-{n}", {}, behind(days=1))
        store.write("new", {}, ahead(days=1))
        assert len(store) == 1

    def test_a_session_survives_the_round_trip(self, store):
        held = {"cloud": {"token": TOKEN, "username": "demo"}, "expires_at": "z"}
        store.write("here", held, ahead(hours=1))
        assert store.read("here") == held


class TestTheFileStore:
    """What it must get right that an in-memory dict gets for free."""

    def test_two_of_them_on_one_directory_see_each_other(self, tmp_path):
        """The whole reason it exists: workers are separate processes."""
        worker = sessions.FileStore(tmp_path / "s")
        other = sessions.FileStore(tmp_path / "s")
        worker.write("shared", {"a": 1}, ahead(days=1))
        assert other.read("shared") == {"a": 1}
        other.drop("shared")
        assert worker.read("shared") is None

    @pytest.mark.parametrize(
        "hostile",
        ["../../etc/passwd", "../escape", "/etc/passwd", "a/b", "..", "."],
    )
    def test_a_name_from_a_cookie_cannot_become_a_path(self, tmp_path, hostile):
        """Whatever a browser sends is hashed before it is a filename."""
        store = sessions.FileStore(tmp_path / "s")
        store.write(hostile, {"a": 1}, ahead(days=1))
        written = [p for p in (tmp_path / "s").iterdir()]
        assert len(written) == 1
        assert written[0].parent == tmp_path / "s"
        assert written[0].name.isalnum()
        assert store.read(hostile) == {"a": 1}

    def test_nothing_escapes_the_directory_even_on_read(self, tmp_path):
        store = sessions.FileStore(tmp_path / "s")
        (tmp_path / "secret").write_text('{"token": "not yours"}')
        assert store.read("../secret") is None

    def test_a_record_is_readable_only_by_its_owner(self, tmp_path):
        store = sessions.FileStore(tmp_path / "s")
        store.write("here", {"token": TOKEN}, ahead(days=1))
        written = next((tmp_path / "s").iterdir())
        assert oct(written.stat().st_mode)[-3:] == "600"

    def test_the_directory_is_private_too(self, tmp_path):
        sessions.FileStore(tmp_path / "s")
        assert oct((tmp_path / "s").stat().st_mode)[-3:] == "700"

    def test_a_half_written_record_is_no_session(self, tmp_path):
        store = sessions.FileStore(tmp_path / "s")
        store.write("here", {"a": 1}, ahead(days=1))
        next((tmp_path / "s").iterdir()).write_text("{not json")
        assert store.read("here") is None

    def test_a_directory_is_made_when_it_is_missing(self, tmp_path):
        where = tmp_path / "deep" / "down"
        sessions.FileStore(where)
        assert where.is_dir()


class TestChoosingAStore:
    def test_no_path_means_memory(self, app):
        app.config["SESSION_STORE_PATH"] = ""
        assert isinstance(sessions.chosen(app), sessions.ExpiringStore)

    def test_a_path_means_files(self, app, tmp_path):
        app.config["SESSION_STORE_PATH"] = str(tmp_path / "s")
        assert isinstance(sessions.chosen(app), sessions.FileStore)
