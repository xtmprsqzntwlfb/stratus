# Stratus

A lightweight web interface for OpenStack.

Stratus shows you what the `openstack` command-line client shows you, in a
browser. It is built on the same library the CLI uses, `openstacksdk`, and it
deliberately stops where the CLI stops: if `openstack server list` does not
report a field, no Stratus page invents one.

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

## Running it

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
STRATUS_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))') \
OS_AUTH_URL=https://keystone.example.com:5000/v3 \
.venv/bin/flask --app stratus run
```

`OS_AUTH_URL` only pre-fills the login form, so you can leave it unset and type
the URL instead. `STRATUS_SECRET_KEY` signs the session cookie; without it
Stratus generates a random key at startup, which means every restart logs you
out. Any Flask setting can be passed the same way, prefixed with `STRATUS_`.

## Status

Early. Right now Stratus can log in to Keystone and log out again. See the
commit log for what has landed since.

## License

MIT, see `LICENSE`.
