"""Authentication, done the way the command-line client does it.

python-openstackclient never assembles keystoneauth plugins by hand. It
collects auth parameters into a dict, hands them to openstacksdk's config
layer, and lets that build the region, the session and the connection. The
only difference here is where the parameters come from: a login form instead
of clouds.yaml and the environment, both of which are switched off below.

So a connection is the primary object in this module, and the token is
something read off one, rather than a separate thing that gets passed around.
"""

import functools

import flask
import keystoneauth1.exceptions
import openstack.config
import openstack.connection

APP_NAME = "stratus"
APP_VERSION = "0.1.0"

# One session key, so logging out is a single deletion and no half-identity
# can survive it.
CLOUD = "cloud"

# Failures specific enough to explain. Order matters: the first match wins,
# so subclasses belong above their parents. Anything unlisted keeps its own
# wording, and anything that is not a ClientException is a bug worth a 500.
EXPLANATIONS = (
    (keystoneauth1.exceptions.Unauthorized, "{auth_url} rejected those credentials."),
    (
        keystoneauth1.exceptions.DiscoveryFailure,
        "{auth_url} is not a version 3 identity endpoint.",
    ),
    (keystoneauth1.exceptions.SSLError, "The TLS certificate of {auth_url} is bad."),
    (keystoneauth1.exceptions.ConnectionError, "Nothing answered at {auth_url}."),
)


class AuthError(Exception):
    """Carries a message already fit to show the user."""


def _explain(failure, auth_url):
    for kind, wording in EXPLANATIONS:
        if isinstance(failure, kind):
            return wording.format(auth_url=auth_url)
    return f"{auth_url} refused the request: {failure}"


def _connect(method, **parameters):
    """Build a connection from auth parameters, the way the CLI would."""
    region = openstack.config.get_cloud_region(
        load_yaml_config=False,
        load_envvars=False,
        auth_type=method,
        auth=parameters,
        verify=flask.current_app.config["VERIFY"],
        app_name=APP_NAME,
        app_version=APP_VERSION,
    )
    return openstack.connection.Connection(config=region)


def log_in(credentials):
    """Trade a password for a token and keep it. Raises AuthError if not."""
    connection = _connect("v3password", **credentials)
    try:
        token = connection.session.get_token()
    except keystoneauth1.exceptions.ClientException as failure:
        raise AuthError(_explain(failure, credentials["auth_url"]))

    remembered = {key: value for key, value in credentials.items() if key != "password"}
    remembered["token"] = token
    flask.session[CLOUD] = remembered


def log_out():
    flask.session.pop(CLOUD, None)


def cloud():
    """What is known about the logged-in user, or None."""
    return flask.session.get(CLOUD)


def connection(project_id=None):
    """A connection for the current user, scoped to one project or to none.

    Nothing is cached between requests. A token in a cookie is cheap to turn
    back into a connection, and caching one would mean holding server state
    that this deliberately does not have.
    """
    known = cloud()
    parameters = {"auth_url": known["auth_url"], "token": known["token"]}
    if project_id is not None:
        # A project id is unique across domains, so scoping by one needs no
        # accompanying domain. Scoping by name would.
        parameters["project_id"] = project_id
    return _connect("v3token", **parameters)


def token_still_works():
    """Whether Keystone still recognises the token in the session.

    Worth asking because Keystone answers 401 both to a token that has
    expired and to a request to scope a good token somewhere it may not go,
    and those two deserve opposite responses.
    """
    try:
        connection().session.get_user_id()
    except keystoneauth1.exceptions.Unauthorized:
        return False
    return True


def login_required(view):
    @functools.wraps(view)
    def guarded(*arguments, **keywords):
        if cloud() is None:
            return flask.redirect(flask.url_for("ui.login", next=flask.request.path))
        return view(*arguments, **keywords)

    return guarded
