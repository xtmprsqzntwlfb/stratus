"""Routes. One blueprint, because there is only ever going to be one."""

import contextlib
import typing

import flask
import keystoneauth1.exceptions
import openstack.exceptions

from . import auth, resources

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


@bp.app_errorhandler(keystoneauth1.exceptions.Unauthorized)
def token_no_longer_works(refusal):
    """Tokens expire, and when one does the session holding it is worthless."""
    auth.log_out()
    flask.flash("That session has expired. Log in again.", "error")
    return flask.redirect(flask.url_for("ui.login"))


@bp.app_errorhandler(404)
def not_found(error):
    return flask.render_template("not_found.html"), 404


@bp.app_errorhandler(openstack.exceptions.NotFoundException)
def resource_is_gone(missing):
    """A 404 from the cloud is a 404 here.

    Returned rather than raised through abort(), because an abort inside an
    error handler is not dispatched to another one.
    """
    return not_found(missing)


@contextlib.contextmanager
def scoped(project_id):
    """A connection into one project, and the two meanings of its refusal.

    Keystone answers 401 both to a token that has expired and to a request
    to scope a good token into a project it may not enter. Asking the
    unscoped token its own user id is what tells those apart.
    """
    try:
        yield auth.connection(project_id)
    except keystoneauth1.exceptions.Unauthorized:
        if not auth.token_still_works():
            raise  # the session is over, and the handler above says so
        # The token is fine, so it is the project that is not: either no
        # such project, or not one this account may enter. Keystone will not
        # say which, and neither should this.
        flask.abort(404)


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
    rows = resources.rows_of(
        mine,
        resources.PROJECT_LIST,
        link=lambda found: flask.url_for("ui.project", project_id=found.id),
    )
    return flask.render_template(
        "projects.html",
        columns=resources.PROJECT_LIST,
        rows=rows,
        empty="No projects this account can reach.",
    )


@bp.route("/projects/<project_id>")
@auth.login_required
def project(project_id):
    """`openstack project show`, on a connection scoped to that project.

    The project is named in the path rather than remembered as a current
    one, so that a page says which project it is about the way a CLI
    invocation does, and two of them can be open at once.
    """
    with scoped(project_id) as connection:
        found = connection.identity.get_project(project_id)
        return flask.render_template(
            "project.html",
            project=found,
            fields=resources.pairs_of(found, resources.PROJECT_SHOW),
        )


@bp.route("/projects/<project_id>/servers")
@auth.login_required
def servers(project_id):
    """`openstack server list`."""
    with scoped(project_id) as connection:
        found = list(connection.compute.servers())
        columns = resources.server_list(resources.image_names(connection, found))
        rows = resources.rows_of(
            found,
            columns,
            link=lambda server: flask.url_for(
                "ui.server", project_id=project_id, server_id=server.id
            ),
        )
        return flask.render_template(
            "servers.html",
            project_id=project_id,
            columns=columns,
            rows=rows,
            empty="No servers in this project.",
        )


@bp.route("/projects/<project_id>/servers/<server_id>")
@auth.login_required
def server(project_id, server_id):
    """`openstack server show`."""
    with scoped(project_id) as connection:
        found = connection.compute.get_server(server_id)
        return flask.render_template(
            "server.html",
            project_id=project_id,
            server=found,
            fields=resources.server_details(connection, found),
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
