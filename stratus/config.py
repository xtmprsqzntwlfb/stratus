"""Built-in defaults, and the bottom of three layers of configuration.

Each layer overrides the one before it:

1. this module, holding defaults that let Stratus start with no setup,
2. ``local_settings.py`` beside it, describing one deployment,
3. ``STRATUS_`` environment variables, for a single run.

A name has to be in capitals to count as a setting, in all three.
"""

import secrets

# Where Keystone lives, pre-filling the login form. Empty means the form
# starts blank and whoever logs in types the endpoint themselves.
AUTH_URL = ""

# Keystone domain of the user, unless the login form says otherwise.
USER_DOMAIN_NAME = "Default"

# Signing key for the session cookie, which is where the Keystone token
# lives. A generated key is fine for running Stratus on your own machine; it
# just means a restart logs everyone out. Set it in local_settings.py to
# survive one.
SECRET_KEY = secrets.token_bytes(32)

# True, or a path to a CA bundle, or False to accept any TLS certificate.
VERIFY = True

# The token is a bearer credential: keep the cookie out of reach of scripts
# and off requests that another site sets off.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
