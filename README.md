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

## Settings

Which cloud Stratus points at is deployment business, so it lives in a
`local_settings.py` that is not in version control, as it does in Horizon:

```sh
cp stratus/local_settings.py.example stratus/local_settings.py
```

Then edit `OPENSTACK_HOST`. The Keystone endpoint is spelled out in that file
rather than derived from the host, because where it sits depends on the
deployment: DevStack proxies everything through Apache at
`http://HOST/identity/v3`, while a cloud running Keystone on its own port
answers at `https://HOST:5000/v3`. Horizon makes you write that line too.

Settings arrive in three layers, each overriding the one before:

| Layer | For |
| --- | --- |
| `stratus/config.py` | Defaults, so Stratus starts with no setup at all |
| `stratus/local_settings.py` | One deployment. Plain Python, names in capitals |
| `STRATUS_*` environment | One run, for instance `STRATUS_AUTH_URL=...` |

Set `STRATUS_LOCAL_SETTINGS` to read the middle layer from somewhere other
than the package directory. Unlike the default file, a path named that way
must exist, because a typo there is a mistake rather than a cloud nobody
meant to configure.

Nothing is read from `OS_*` variables or `clouds.yaml`. A sourced `openrc`
cannot change where Stratus points.

## Running it

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app stratus run
```

The endpoint in `local_settings.py` only pre-fills the login form, so it can
be left empty and typed in instead.

## Status

Early. Right now Stratus can log in to Keystone and log out again. See the
commit log for what has landed since.

## License

MIT, see `LICENSE`.
