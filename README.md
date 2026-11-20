# Stratus

A lightweight web interface for OpenStack.

Stratus shows you what the `openstack` command-line client shows you, in a
browser. It is built on the same library the CLI uses, `openstacksdk`, and it
deliberately stops where the CLI stops.

## Non-goals

These are design constraints, not a backlog:

- **No features beyond the CLI.** No dashboards, no graphs, no quotas
  summaries, no cost reports, no orchestration of multi-step workflows.
- **No JavaScript.** Every page is server-rendered HTML. There is no build
  step, no bundler and no `node_modules`.
- **No database.** Stratus stores nothing. The only state is your Keystone
  token, in a signed cookie.
- **No plugin system.** Adding a resource means adding a declaration, not
  installing a package.

## Running it locally

Install it, and copy the settings template:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp stratus/local_settings.py.example stratus/local_settings.py
```

Point `OPENSTACK_HOST` in `stratus/local_settings.py` at your cloud:

```python
OPENSTACK_HOST = "10.0.0.1"
AUTH_URL = f"http://{OPENSTACK_HOST}/identity/v3"
```

`AUTH_URL` is a separate line because where Keystone sits depends on the
deployment. DevStack proxies everything through Apache, so it answers under
`/identity/v3` on port 80, while a cloud running Keystone on its own port
answers at `https://{OPENSTACK_HOST}:5000/v3`. Both are in the template, one
of them commented out. Horizon makes you write this line too.

Then start it:

```sh
.venv/bin/flask --app stratus run
```

Stratus is at <http://127.0.0.1:5000/>, and it asks for the same user name,
password and domain the `openstack` client would. The endpoint only pre-fills
the login form, so you can leave it unset and type it in instead.

## How it talks to the cloud

Through `openstacksdk`, and through the same part of it the CLI uses. The
command-line client does not build authentication plugins or sessions itself:
it gathers auth parameters and hands them to the SDK's config layer, which
assembles the connection. Stratus does that too, with the login form standing
in for `clouds.yaml` and the environment, both of which it switches off so a
sourced `openrc` cannot quietly override what you typed.

Logging in asks for an *unscoped* token, and that token is the whole of the
session. Each request turns it back into a connection scoped to whatever
project the page is about. Nothing is cached in the process.

### Where the field names differ

Which fields a page shows, and which it leaves out, follows the CLI. What
they are *called* does not always. Before printing a server, the CLI renames
openstacksdk's attributes to the names nova used when half of them lived in
API extensions, so `created_at` reaches a terminal as `created` and
`power_state` as `OS-EXT-STS:power_state`. Those prefixes are fossils and
carrying them into a browser buys nothing, so Stratus keeps the SDK's names.

Values that mean nothing raw are still worked out the way the CLI works them
out: a power state is `Running` rather than `1`, addresses read
`private=10.0.0.5, fd00::5`, and a server with no image says `N/A (booted
from volume)` in those words, because people grep for them. Nested values
render as `key=value` pairs rather than as a Python dictionary, keeping the
empty ones as the CLI keeps them.

## When the cloud misbehaves

Clouds fail in ways that are nobody's bug, and `stratus/errors.py` is the one
place that decides what each failure looks like:

| What happened | What you get |
| --- | --- |
| The token aged out | Logged out, back to the login form |
| Denied, or not there | A plain 404, saying no more than that |
| A service is missing or silent | 503 naming that service, rest of the site standing |
| Anything else | 500, and a request id to find the traceback by |

The last row is what a deployment does. Under `flask run --debug` the failure
is logged under its id and then re-raised, so the interactive debugger gets
the one thing you started that server to see.

A refusal and an absence answer alike on purpose, so that nobody can map what
exists by reading which of the two comes back.

A project page offers only the kinds of thing the cloud actually runs. It
decides from the service catalogue the token already carries, so a cloud
without cinder shows no Volumes link rather than a link to a 503, and
deciding costs no requests. A service that is listed but silent is a
different matter and still gets as far as its own page.

One service falling over takes down only the pages that need it. The side
lookups are forgiving too: a server list still draws when glance cannot be
reached, showing image ids in place of names, and a volume list still draws
when nova cannot be reached, showing server ids in place of names.

## Settings

Three layers, each overriding the one before:

| Layer | For |
| --- | --- |
| `stratus/config.py` | Defaults, so Stratus starts with no setup at all |
| `stratus/local_settings.py` | One deployment. Plain Python, names in capitals |
| `STRATUS_*` environment | One run, for instance `STRATUS_AUTH_URL=...` |

The middle layer is not in version control, as in Horizon. Set
`STRATUS_LOCAL_SETTINGS` to read it from somewhere other than the package
directory; unlike the default file, a path named that way must exist, because
a typo there is a mistake rather than a cloud nobody meant to configure.

Nothing is read from `OS_*` variables or `clouds.yaml`.

## Status

Early. Stratus can log in, list the projects an account can reach, and list
and show the servers, images, networks, flavors and volumes in one of them.

Each kind of resource is a declaration in `stratus/resources.py` saying what
the CLI prints for it and how to fetch it, and one pair of routes renders
them all. Adding volumes or flavors means adding a declaration, not a page.

A project is named in the path, as in `/projects/<id>`, rather than being a
current project held in the session. That follows the CLI, where scope is an
argument to each command rather than a mode you switch into, and it means a
page says which project it is about and two of them can be open at once.

## License

MIT, see `LICENSE`.
