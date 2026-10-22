"""Stratus, a lightweight web interface for OpenStack."""

import flask

from . import config, views

__version__ = "0.1.0"


def create_app(**overrides):
    app = flask.Flask(__name__)
    # Block tags indent with the markup around them without padding the
    # output with the blank lines that would otherwise leave.
    app.jinja_options = {"trim_blocks": True, "lstrip_blocks": True}
    app.config.from_object(config)
    app.config.from_prefixed_env("STRATUS")
    app.config.update(overrides)
    app.register_blueprint(views.bp)
    return app
