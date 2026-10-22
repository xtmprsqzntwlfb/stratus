"""Routes. One blueprint, because there is only ever going to be one."""

import typing

import flask

from . import auth

bp = flask.Blueprint("ui", __name__)


class Field(typing.NamedTuple):
    """One input on the login form."""

    name: str
    label: str
    kind: str = "text"
    default: str = ""  # name of the config setting that pre-fills it
    hint: str = ""

    @property
    def secret(self):
        return self.kind == "password"


# The form, the parameters sent to Keystone and what gets re-rendered after a
# failure are all this one declaration, so they cannot drift apart.
LOGIN_FORM = (
    Field(
        "auth_url",
        "Identity endpoint",
        kind="url",
        default="AUTH_URL",
        hint="https://keystone.example.com:5000/v3",
    ),
    Field("username", "User name"),
    Field("password", "Password", kind="password"),
    Field("user_domain_name", "Domain", default="USER_DOMAIN_NAME"),
)


def _submitted():
    """Credentials as typed, with the stray whitespace of a paste removed."""
    typed = {}
    for field in LOGIN_FORM:
        value = flask.request.form.get(field.name, "")
        typed[field.name] = value if field.secret else value.strip()
    return typed


def _prefilled():
    settings = flask.current_app.config
    return {field.name: settings.get(field.default, "") for field in LOGIN_FORM}


def _onward(destination):
    """Follow a ``next`` only where it stays inside Stratus."""
    looks_internal = destination and destination.startswith("/")
    looks_absolute = destination and destination.startswith("//")
    if looks_internal and not looks_absolute:
        return destination
    return flask.url_for("ui.index")


@bp.route("/")
@auth.login_required
def index():
    return flask.render_template("index.html", cloud=auth.cloud())


@bp.route("/login", methods=["GET", "POST"])
def login():
    values = _prefilled()
    if flask.request.method == "POST":
        values = _submitted()
        try:
            auth.log_in(values)
        except auth.AuthError as refusal:
            flask.flash(str(refusal), "error")
        else:
            return flask.redirect(_onward(flask.request.args.get("next")))
    return flask.render_template("login.html", fields=LOGIN_FORM, values=values)


@bp.route("/logout", methods=["POST"])
def logout():
    auth.log_out()
    return flask.redirect(flask.url_for("ui.login"))
