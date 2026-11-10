"""Routes. One blueprint, because there is only ever going to be one."""

import typing

import flask
import keystoneauth1.exceptions

from . import auth

bp = flask.Blueprint("ui", __name__)


class Column(typing.NamedTuple):
    """One field of a resource, labelled the way the CLI labels it.

    The CLI's own name for a field and openstacksdk's attribute name are not
    always the same word, so both are written down.
    """

    label: str
    attribute: str

    def of(self, resource):
        return getattr(resource, self.attribute, None)


def rows_of(resources, columns, link=None):
    """One row per resource, for a list page.

    ``link`` turns a resource into the address its row points at. By
    convention the first cell carries it, the first column being the
    identifier in every listing the CLI prints.
    """
    return [
        {
            "cells": [column.of(resource) for column in columns],
            "link": link(resource) if link else None,
        }
        for resource in resources
    ]


def pairs_of(resource, columns):
    """(label, value) for each field, for a show page."""
    return [(column.label, column.of(resource)) for column in columns]


# What `openstack project list` prints.
PROJECT_LIST = (Column("ID", "id"), Column("Name", "name"))

# What `openstack project show` prints, in its order, which is alphabetical
# by the CLI's name for the field rather than by the SDK's.
PROJECT_SHOW = (
    Column("description", "description"),
    Column("domain_id", "domain_id"),
    Column("enabled", "is_enabled"),
    Column("id", "id"),
    Column("is_domain", "is_domain"),
    Column("name", "name"),
    Column("options", "options"),
    Column("parent_id", "parent_id"),
    Column("tags", "tags"),
)


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


@bp.app_errorhandler(keystoneauth1.exceptions.Unauthorized)
def token_no_longer_works(refusal):
    """Tokens expire, and when one does the session holding it is worthless."""
    auth.log_out()
    flask.flash("That session has expired. Log in again.", "error")
    return flask.redirect(flask.url_for("ui.login"))


@bp.app_errorhandler(404)
def not_found(error):
    return flask.render_template("not_found.html"), 404


@bp.route("/")
@auth.login_required
def index():
    return flask.redirect(flask.url_for("ui.projects"))


@bp.route("/projects")
@auth.login_required
def projects():
    """`openstack project list --my-projects`.

    Plain `project list` asks for every project on the cloud and is refused
    anyone who is not an administrator. The projects a user can actually
    reach are the ones their own token can be scoped to, which is the same
    set the CLI reaches for with --my-projects.
    """
    connection = auth.connection()
    mine = connection.identity.user_projects(connection.session.get_user_id())
    rows = rows_of(
        mine,
        PROJECT_LIST,
        link=lambda found: flask.url_for("ui.project", project_id=found.id),
    )
    return flask.render_template("projects.html", columns=PROJECT_LIST, rows=rows)


@bp.route("/projects/<project_id>")
@auth.login_required
def project(project_id):
    """`openstack project show`, on a connection scoped to that project.

    The project is named in the path rather than remembered as a current
    one, so that a page says which project it is about the way a CLI
    invocation does, and two of them can be open at once.
    """
    connection = auth.connection(project_id)
    try:
        found = connection.identity.get_project(project_id)
    except keystoneauth1.exceptions.Unauthorized:
        if not auth.token_still_works():
            raise  # the session is over, and the handler above says so
        # The token is fine, so it is the project that is not: either no
        # such project or not one this account may enter. Keystone will not
        # say which, and neither should this.
        flask.abort(404)
    return flask.render_template(
        "project.html", project=found, fields=pairs_of(found, PROJECT_SHOW)
    )


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
