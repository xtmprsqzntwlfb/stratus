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
import hashlib
import json
import os
import pathlib
import secrets
import tempfile
import threading
import time

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


class FileStore:
    """Session records as files, for when one process is not enough.

    An in-memory store is private to the process holding it, so behind
    `gunicorn -w 4` a session would be found only by the worker that made
    it and logging in would appear to come and go. These are shared by
    every worker on the host, and need nothing installed to be so.

    The name out of the cookie never becomes a path. It is hashed first,
    so whatever a browser sends lands on one harmless filename in this
    directory and cannot reach outside it.

    Expiry is kept as the file's own modification time, which makes
    sweeping a stat for each rather than a read.
    """

    def __init__(self, directory):
        self.directory = pathlib.Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        # The contents are bearer tokens. Nobody else's business.
        self.directory.chmod(0o700)

    def _path(self, name):
        return self.directory / hashlib.sha256(name.encode()).hexdigest()

    def read(self, name):
        path = self._path(name)
        try:
            if path.stat().st_mtime <= time.time():
                path.unlink(missing_ok=True)
                return None
            return json.loads(path.read_text())
        except (OSError, ValueError):
            # Gone, unreadable, or half written by a worker that died.
            # None of those is a session.
            return None

    def write(self, name, contents, expires):
        self._sweep()
        path = self._path(name)
        moment = expires.timestamp()
        handle, temporary = tempfile.mkstemp(dir=self.directory, suffix=".part")
        with os.fdopen(handle, "w") as writing:
            json.dump(contents, writing)
        os.chmod(temporary, 0o600)
        os.utime(temporary, (moment, moment))
        # Renaming is atomic, so another worker reading this name sees
        # either the record it had or this one, never half of one.
        os.replace(temporary, path)

    def drop(self, name):
        self._path(name).unlink(missing_ok=True)

    def _sweep(self):
        moment = time.time()
        for path in self.directory.iterdir():
            if path.suffix == ".part":
                continue  # somebody else is mid-write
            try:
                if path.stat().st_mtime <= moment:
                    path.unlink()
            except OSError:
                pass  # swept by another worker in the meantime

    def __len__(self):
        return len([p for p in self.directory.iterdir() if p.suffix != ".part"])


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
    app.session_interface = ServerSide(store if store is not None else chosen(app))


def chosen(app):
    """The store a deployment asked for.

    A path means files, shared by every worker on the host. Nothing means
    memory, which is right for one process and wrong for two.
    """
    directory = app.config.get("SESSION_STORE_PATH")
    return FileStore(directory) if directory else ExpiringStore()


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
