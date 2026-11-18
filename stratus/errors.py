"""The one place where a cloud's failures turn into pages.

openstacksdk and keystoneauth raise out of two separate trees, neither
descended from the other, and between them a request can fail a dozen ways
that are nobody's bug: a token that aged out mid-session, a project the
account may not enter, a service missing from the catalogue, one that is
listed but not answering, one answering 503. Left alone every one of those
is a 500, and a page full of someone else's stack trace.

So they are all mapped here, once. Views call the cloud without a try
block of their own, and whatever comes back lands in one of four places:

    the token is finished      log out and send them to the login form
    denied, or not there       404, saying no more than that
    the service is not well    503, naming it, with the rest of the site
                               still standing
    anything else              500, and a request id to find it in the log

Only three handlers are registered, one per tree plus a catch-all,
because Flask walks an exception's MRO to pick a handler and both trees
sit above Exception. The sorting happens in ``respond_to``, so the rules
read as one list rather than as a scatter of decorators.
"""

import contextlib
import logging
import uuid

import flask
import keystoneauth1.exceptions
import openstack.exceptions

from . import auth

log = logging.getLogger(__name__)

# Trouble at the far end rather than with the request: no endpoint, no
# route to it, TLS that will not agree, or a service answering 5xx.
UNWELL = (
    openstack.exceptions.ConfigException,  # includes a disabled service
    openstack.exceptions.EndpointNotFound,
    openstack.exceptions.ResourceTimeout,
    openstack.exceptions.ServiceDiscoveryException,
    keystoneauth1.exceptions.ConnectionError,  # refused, timed out, bad TLS
    keystoneauth1.exceptions.DiscoveryFailure,
    keystoneauth1.exceptions.EndpointNotFound,
    keystoneauth1.exceptions.HttpServerError,
)

# A refusal and an absence get the same answer, so that nobody can map
# what exists by reading which of the two comes back.
DENIED_OR_ABSENT = (
    openstack.exceptions.ForbiddenException,
    openstack.exceptions.NotFoundException,
    keystoneauth1.exceptions.Forbidden,
    keystoneauth1.exceptions.NotFound,
)


def register(app):
    app.before_request(_tag)
    app.register_error_handler(404, lambda error: not_found())
    app.register_error_handler(openstack.exceptions.SDKException, respond_to)
    app.register_error_handler(keystoneauth1.exceptions.ClientException, respond_to)
    app.register_error_handler(Exception, respond_to)


def respond_to(failure):
    """Sort one failure into one of the four answers."""
    if _token_is_finished(failure):
        return session_over()
    if _denied_or_absent(failure):
        return not_found()
    if _unwell(failure):
        return unavailable(failure)
    return unexpected(failure)


def _status(failure):
    """The HTTP status, under whichever name the tree gives it."""
    return getattr(failure, "status_code", None) or getattr(
        failure, "http_status", None
    )


def _token_is_finished(failure):
    return (
        isinstance(failure, keystoneauth1.exceptions.Unauthorized)
        or _status(failure) == 401
    )


def _denied_or_absent(failure):
    return isinstance(failure, DENIED_OR_ABSENT) or _status(failure) in (403, 404)


def _unwell(failure):
    status = _status(failure)
    return isinstance(failure, UNWELL) or (status is not None and status >= 500)


def session_over():
    auth.log_out()
    flask.flash("That session has expired. Log in again.", "error")
    return flask.redirect(flask.url_for("ui.login"))


def not_found():
    return flask.render_template("not_found.html"), 404


def unavailable(failure):
    log.warning(
        "the %s service did not answer [%s]: %s", subject(), request_id(), failure
    )
    return flask.render_template("unavailable.html", subject=subject()), 503


def unexpected(failure):
    # exception(), not error(), so the traceback reaches the log under the
    # same id the page is showing. That pairing is the whole point of it.
    log.exception("unhandled failure [%s]", request_id())
    return flask.render_template("failure.html", request_id=request_id()), 500


def _tag():
    flask.g.request_id = uuid.uuid4().hex[:12]


def request_id():
    return getattr(flask.g, "request_id", "untagged")


def about(service):
    """Name the service this request is about to lean on."""
    flask.g.service = service


def subject():
    return getattr(flask.g, "service", "cloud")


@contextlib.contextmanager
def scoped(project_id):
    """A connection into one project, and the two meanings of its refusal.

    Keystone answers 401 both to a token that has expired and to a request
    to scope a good token into a project it may not enter, and those want
    opposite answers. Asking the unscoped token its own user id tells them
    apart, and costs a request only on the path that already failed.
    """
    # Until the scope is settled, keystone is the service in question.
    about("identity")
    connection = auth.connection(project_id)
    try:
        # Rescope now rather than on the body's first call, so that a
        # refusal reaching this handler is known to be about the project
        # and not about whatever the page went on to ask for. It costs no
        # extra request: the body would force the same exchange, and the
        # plugin holds on to the result either way.
        connection.session.get_token()
    except keystoneauth1.exceptions.Unauthorized:
        if not auth.token_still_works():
            raise  # genuinely finished, and respond_to will say so
        # The token is fine, so it is the project that is not: either no
        # such project, or not one this account may enter. Keystone will
        # not say which, and neither does this.
        flask.abort(404)
    # Anything the body raises is a failure of the service it was talking
    # to, so it goes to respond_to unread.
    yield connection
