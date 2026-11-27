"""A form posted from somewhere else is not a form this application sent.

A browser attaches its cookies to whatever request it makes, including one
another site provoked. So a POST arriving with a good session proves the
browser has a session, and nothing about who drew the form. A secret the
session knows, written into every form and checked on the way back, is
what proves that.

`SameSite=Lax` already refuses the cross-site POST this guards against,
but that is one header resting on one browser's reading of it, and a
token costs almost nothing.
"""

import secrets

import flask

FIELD = "csrf_token"
LENGTH = 32

# The methods that are supposed to change nothing, and so need no proof.
SAFE = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def token():
    """The secret for this session, minted the first time a form wants it."""
    held = flask.session.get(FIELD)
    if not held:
        held = secrets.token_urlsafe(LENGTH)
        flask.session[FIELD] = held
    return held


def guard():
    """Turn away anything unsafe that cannot show the secret."""
    if flask.request.method in SAFE:
        return None
    held = flask.session.get(FIELD)
    given = flask.request.form.get(FIELD, "")
    # compare_digest rather than ==, so that the time taken says nothing
    # about how much of the token was right.
    if not held or not secrets.compare_digest(given, held):
        return flask.render_template("stale.html"), 400
    return None


def register(app):
    app.before_request(guard)
    app.jinja_env.globals["csrf_token"] = token
