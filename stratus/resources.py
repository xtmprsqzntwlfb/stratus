"""What the CLI prints, written down.

Every list and show page renders one of these declarations, so a page
cannot quietly stop matching the command it is named after. Where the CLI's
name for a field and openstacksdk's attribute name differ, both are here.
"""

import typing

import openstack.exceptions

# What `openstack server list` puts in the Image column for a server booted
# straight from a volume, which therefore has no image. Worth spelling the
# way the CLI spells it, since people grep for it.
NO_IMAGE = "N/A (booted from volume)"


class Column(typing.NamedTuple):
    """One field, labelled the way the CLI labels it.

    ``source`` is an openstacksdk attribute name, or a function of the
    resource for the columns the CLI works out rather than reads.
    """

    label: str
    source: typing.Any

    def of(self, resource):
        if callable(self.source):
            return self.source(resource)
        return getattr(resource, self.source, None)


def rows_of(resources, columns, link=None):
    """One row per resource, for a list page.

    ``link`` turns a resource into the address its row points at. By
    convention the first cell carries it, the first column being the
    identifier in every listing the CLI prints.
    """
    return [
        {
            "cells": [column.of(resource) for column in columns],
            "link": link(resource) if link else None,
        }
        for resource in resources
    ]


def readable(value):
    """A value as a page should show it rather than as Python repr()s it.

    Nested dictionaries and lists are what the CLI runs through its own
    formatting columns, and printing a raw ``{'disk': 0, 'ram': 0}`` into a
    page is the one thing neither of them does.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        pairs = ((key, readable(item)) for key, item in sorted(value.items()))
        # Keys with nothing behind them are noise: a flavor carries a dozen
        # of them. Compared against "" rather than tested for truth, so that
        # a disk of 0 or a public flag of False still counts as an answer.
        return ", ".join(f"{key}={item}" for key, item in pairs if item != "")
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(str(readable(item)) for item in value)
    return value


def pairs_of(resource, columns):
    """(label, value) for each field, for a show page."""
    return [(column.label, readable(column.of(resource))) for column in columns]


# `openstack project list`
PROJECT_LIST = (Column("ID", "id"), Column("Name", "name"))

# `openstack project show`, in its order, which is alphabetical by the CLI's
# name for the field rather than by the SDK's.
PROJECT_SHOW = (
    Column("description", "description"),
    Column("domain_id", "domain_id"),
    Column("enabled", "is_enabled"),
    Column("id", "id"),
    Column("is_domain", "is_domain"),
    Column("name", "name"),
    Column("options", "options"),
    Column("parent_id", "parent_id"),
    Column("tags", "tags"),
)


def networks_of(server):
    """The Networks column: ``net=ip, ip; other=ip``, as the CLI joins it."""
    return addresses_of(server.addresses)


def flavor_of(server):
    """The Flavor column.

    Compute embeds the flavor in the server from microversion 2.47, so this
    costs no extra request. Older clouds return only an id, and there the
    column is left as that id rather than fetched one server at a time.
    """
    flavor = server.flavor
    if flavor is None:
        return ""
    return flavor.original_name or flavor.id or ""


def image_names(connection, servers):
    """Map image id to image name for the images these servers came from.

    `openstack server list` shows image names, which compute does not
    return, so they have to be fetched. Only the distinct images actually in
    front of us are asked for: a cloud can hold far more images than a
    project holds servers, so listing them all to find two is the wrong way
    round.
    """
    wanted = {s.image.id for s in servers if s.image and s.image.id}
    found = {}
    for identifier in wanted:
        try:
            found[identifier] = connection.image.get_image(identifier).name
        except openstack.exceptions.SDKException:
            pass  # deleted since, or not one this account may look at
    return found


def server_list(images):
    """`openstack server list`, given the image names it needs to print."""

    def image_of(server):
        identifier = server.image.id if server.image else None
        if not identifier:
            return NO_IMAGE
        return images.get(identifier, identifier)

    return (
        Column("ID", "id"),
        Column("Name", "name"),
        Column("Status", "status"),
        Column("Networks", networks_of),
        Column("Image", image_of),
        Column("Flavor", flavor_of),
    )


# `openstack server show` prints the whole resource rather than a chosen few
# fields, so it is described by what to leave out rather than what to put in.

# Keys openstacksdk adds for its own convenience, which no API returns.
SERVER_SHOW_SKIPS = frozenset(
    {
        "block_device_mapping",
        "flavor_id",
        "host",
        "image_id",
        "interface_ip",
        "links",
        "location",
        "max_count",
        "min_count",
        "networks",
        "personality",
        "private_v4",
        "private_v6",
        "public_v4",
        "public_v6",
        "volumes",
    }
)

# Keys worth printing only when the server has them.
SERVER_SHOW_OPTIONAL = frozenset({"admin_password", "fault", "security_groups"})


# The power state is a number on the wire and a word in the CLI. Index is
# the number; the gaps are states nova never reports.
POWER_STATES = (
    "NOSTATE",
    "Running",
    "",
    "Paused",
    "Shutdown",
    "",
    "Crashed",
    "Suspended",
)


def power_state(value):
    try:
        return POWER_STATES[value]
    except (IndexError, TypeError):
        return "N/A"


def addresses_of(addresses):
    """The addresses dict, joined the way both list and show join it."""
    return "; ".join(
        "{}={}".format(
            network, ", ".join(a["addr"] for a in entries or () if "addr" in a)
        )
        for network, entries in sorted((addresses or {}).items())
    )


def server_details(connection, server):
    """Every field of a server, under openstacksdk's own names.

    The CLI renames these to what compute called them before printing, so
    `created_at` reaches a terminal as `created` and `power_state` as
    `OS-EXT-STS:power_state`. Those names are fossils of nova API
    extensions that were folded into the API years ago, and carrying them
    into a browser buys nothing, so the SDK's names stand here. The fields
    themselves, and which are left out, still follow the CLI.
    """
    shown = {}
    for key, value in server.to_dict().items():
        if key in SERVER_SHOW_SKIPS:
            continue
        if key in SERVER_SHOW_OPTIONAL and value is None:
            continue
        shown[key] = value

    image = shown.get("image") or {}
    identifier = image.get("id") if isinstance(image, dict) else None
    if identifier:
        try:
            name = connection.image.get_image(identifier).name
            shown["image"] = f"{name} ({identifier})"
        except openstack.exceptions.SDKException:
            shown["image"] = identifier
    else:
        shown["image"] = NO_IMAGE

    shown["addresses"] = addresses_of(shown.get("addresses"))
    if "power_state" in shown:
        shown["power_state"] = power_state(shown["power_state"])

    return sorted((key, readable(value)) for key, value in shown.items())
