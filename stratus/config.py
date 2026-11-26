"""Built-in defaults, and the bottom of three layers of configuration.

Each layer overrides the one before it:

1. this module, holding defaults that let Stratus start with no setup,
2. ``local_settings.py`` beside it, describing one deployment,
3. ``STRATUS_`` environment variables, for a single run.

A name has to be in capitals to count as a setting, in all three.
"""

import datetime
import secrets

# Where Keystone lives, pre-filling the login form. Empty means the form
# starts blank and whoever logs in types the endpoint themselves.
AUTH_URL = ""

# Keystone domain of the user, unless the login form says otherwise.
USER_DOMAIN_NAME = "Default"

# Flask's signing key. Nothing signs anything at the moment: the session
# cookie carries an opaque name looked up on the server, so it needs no
# signature, and the session itself never reaches the browser. Kept
# because it is the one setting every Flask extension reaches for, and
# the first thing to need it will be CSRF tokens. A generated key is
# fine until then.
SECRET_KEY = secrets.token_bytes(32)

# True, or a path to a CA bundle, or False to accept any TLS certificate.
VERIFY = True

# The cookie holds only a name for a session kept on the server, but that
# name is as good as the token behind it, so it is guarded the same way:
# never readable by a script, never sent on another site's request, and
# never over plain HTTP.
SESSION_COOKIE_NAME = "stratus"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
# Turn this off only to run the development server over http, and only
# then. A cookie sent in clear is a session anyone on the path can take.
SESSION_COOKIE_SECURE = True

# Where to keep sessions. Empty means in memory, which is private to one
# process: correct for `flask run`, wrong the moment a second worker
# exists, since a session would be found only by the worker that made it.
# A path puts them in files instead, shared by every worker on the host.
SESSION_STORE_PATH = ""

# How long a session may live without its token saying otherwise. The
# record expires with the token when that comes first, which it usually
# does, Keystone handing out hours rather than days.
PERMANENT_SESSION_LIFETIME = datetime.timedelta(hours=12)
