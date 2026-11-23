"""Where the token actually lives.

Flask's default session signs its cookie but does not encrypt it, so
everything inside travels in the browser in plain sight. A Keystone token
is a bearer credential: whoever reads one can act as that user until it
expires, with no password involved. Handing that to the browser and
trusting nobody to look is not a boundary, it is a hope.

So the cookie carries one thing, an unguessable name, and the session it
names stays on this side. The store below is a plain expiring dict, which
is enough for the single process `flask run` starts and is the seam to
replace when there is more than one of them: anything with read, write
and drop will do, and `install` takes it.
"""

import datetime
import secrets
import threading

import flask
import flask.sessions
from werkzeug.datastructures import CallbackDict

# Long enough not to interrupt an afternoon, short enough that a forgotten
# browser is not a standing invitation. A record never outlives the token
# inside it either way, whichever moment comes first.
DEFAULT_LIFETIME = datetime.timedelta(hours=12)

# Where the session records the moment its token stops being any use.
EXPIRY = "expires_at"

# 256 bits of name, so that guessing one is not a strategy.
NAME_BYTES = 32


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _aware(moment):
    """Keystone is not consistent about saying UTC, so say it here."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=datetime.timezone.utc)
    return moment


class ExpiringStore:
    """Session records in memory, each dropped at its own moment.

    Locked, because a threaded server reads and writes these from several
    requests at once and a dict is not safe to resize underneath itself.
    """

    def __init__(self):
        self._records = {}
        self._lock = threading.Lock()

    def read(self, name):
        with self._lock:
            found = self._records.get(name)
            if found is None:
                return None
            contents, expires = found
            if expires <= _now():
                del self._records[name]
                return None
            return dict(contents)

    def write(self, name, contents, expires):
        with self._lock:
            self._sweep()
            self._records[name] = (dict(contents), expires)

    def drop(self, name):
        with self._lock:
            self._records.pop(name, None)

    def _sweep(self):
        # Nobody comes back for an expired record, so the only chance to
        # notice one is while passing. Cheap, and it keeps a long-running
        # process from holding dead sessions for as long as it lives.
        moment = _now()
        for name in [n for n, (_, when) in self._records.items() if when <= moment]:
            del self._records[name]

    def __len__(self):
        with self._lock:
            return len(self._records)


class Session(CallbackDict, flask.sessions.SessionMixin):
    """A session that knows the name it answers to."""

    def __init__(self, contents=None, name=None):
        super().__init__(contents or {}, lambda _: setattr(self, "modified", True))
        self.name = name
        self.modified = False


class ServerSide(flask.sessions.SessionInterface):
    """Keeps the session here and gives the browser only its name."""

    session_class = Session

    def __init__(self, store):
        self.store = store

    def open_session(self, app, request):
        name = request.cookies.get(self.get_cookie_name(app))
        if name:
            contents = self.store.read(name)
            if contents is not None:
                return self.session_class(contents, name=name)
        # No cookie, or a name nothing answers to any more. Either way
        # this is a new session, and the name the browser offered is not
        # adopted: a name it chose is a name somebody else could choose.
        return self.session_class()

    def save_session(self, app, session, response):
        cookie = self.get_cookie_name(app)
        flags = {
            "domain": self.get_cookie_domain(app),
            "path": self.get_cookie_path(app),
            "secure": self.get_cookie_secure(app),
            "httponly": self.get_cookie_httponly(app),
            "samesite": self.get_cookie_samesite(app),
        }
        if session.accessed:
            response.vary.add("Cookie")

        if not session:
            if session.name:
                self.store.drop(session.name)
                session.name = None
            if session.modified:
                response.delete_cookie(cookie, **flags)
                response.vary.add("Cookie")
            return

        if not session.modified:
            # Nothing changed, and the record already has an absolute
            # expiry, so there is nothing to write and no cookie to
            # re-send. Keeps Set-Cookie off every stylesheet.
            return

        if session.name is None:
            session.name = secrets.token_urlsafe(NAME_BYTES)
        expires = self.expiry_of(app, session)
        self.store.write(session.name, dict(session), expires)
        response.set_cookie(cookie, session.name, expires=expires, **flags)
        response.vary.add("Cookie")

    def expiry_of(self, app, session):
        """The earlier of the configured lifetime and the token's own end."""
        lifetime = _now() + app.permanent_session_lifetime
        stamped = session.get(EXPIRY)
        if not stamped:
            return lifetime
        return min(lifetime, _aware(datetime.datetime.fromisoformat(stamped)))


def install(app, store=None):
    app.session_interface = ServerSide(store if store is not None else ExpiringStore())


def _store():
    return flask.current_app.session_interface.store


def renew():
    """Start answering to a new name, forgetting the old one.

    Called when someone logs in. Without it, a name planted in the
    browser beforehand would still be the name the session answers to
    afterwards, which is the whole of session fixation.
    """
    session = flask.session
    if getattr(session, "name", None):
        _store().drop(session.name)
    session.name = None
    session.modified = True


def destroy():
    """Forget the session here, not just in the browser."""
    session = flask.session
    if getattr(session, "name", None):
        _store().drop(session.name)
        session.name = None
    session.clear()
    session.modified = True
