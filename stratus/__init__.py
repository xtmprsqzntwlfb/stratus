"""Stratus, a lightweight web interface for OpenStack."""

import os

import flask

from . import config, views

__version__ = "0.1.0"

# Deployment settings, beside this file and kept out of version control, in
# the manner of Horizon's local_settings.py. STRATUS_LOCAL_SETTINGS points
# somewhere else when the package is installed rather than run from a
# checkout.
LOCAL_SETTINGS = "local_settings.py"
LOCAL_SETTINGS_VARIABLE = "STRATUS_LOCAL_SETTINGS"


def _load_local_settings(app):
    elsewhere = os.environ.get(LOCAL_SETTINGS_VARIABLE)
    if elsewhere:
        # Asked for by name, so a missing file is a mistake worth hearing
        # about rather than a cloud that silently is not configured.
        app.config.from_pyfile(elsewhere)
    else:
        app.config.from_pyfile(LOCAL_SETTINGS, silent=True)


def create_app(**overrides):
    app = flask.Flask(__name__)
    # Let block tags indent with the markup around them without padding the
    # output with the blank lines that would otherwise leave.
    app.jinja_options = {"trim_blocks": True, "lstrip_blocks": True}
    app.config.from_object(config)
    _load_local_settings(app)
    app.config.from_prefixed_env("STRATUS")
    app.config.update(overrides)
    app.register_blueprint(views.bp)
    return app
