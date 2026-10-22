"""Defaults for the Flask application.

Anything here can be overridden from the environment with a ``STRATUS_``
prefix, so ``STRATUS_AUTH_URL=...`` wins over ``OS_AUTH_URL``.
"""

import os
import secrets


# Signing key for the session cookie, which is where the Keystone token
# lives. STRATUS_SECRET_KEY overrides this. A generated key is fine for
# running Stratus on your own machine; it just means a restart invalidates
# every session.
SECRET_KEY = secrets.token_bytes(32)

# Pre-fills the login form. The usual OpenStack variable name, so an already
# sourced openrc works.
AUTH_URL = os.environ.get("OS_AUTH_URL", "")

# Keystone domain for the user, unless the login form says otherwise.
USER_DOMAIN_NAME = os.environ.get("OS_USER_DOMAIN_NAME", "Default")

# Path to a CA bundle, or False to skip certificate verification entirely.
VERIFY = os.environ.get("OS_CACERT", True)

# The token is a bearer credential; keep the cookie off plain HTTP requests to
# other sites and out of reach of scripts.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
