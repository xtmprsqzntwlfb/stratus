"""The application a real server runs.

`flask run` builds the app itself and is for development. Anything else
wants one object to import, so:

    gunicorn stratus.wsgi:application
    waitress-serve --call stratus:create_app

Settings come from the same three layers as always, so a deployment is
still described by local_settings.py or by STRATUS_ variables, and this
module holds no configuration of its own.
"""

from . import create_app

application = create_app()
