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


def readable(value, prefix=""):
    """A value as a page should show it rather than as Python repr()s it.

    Nested dictionaries and lists are what the CLI runs through its own
    formatting columns, and printing a raw ``{'disk': 0, 'ram': 0}`` into a
    page is the one thing neither of them does.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        # Every key is kept, including the ones with nothing behind them,
        # because the CLI prints those too and a field that is empty is
        # worth telling apart from a field that is absent. A dictionary
        # inside a dictionary flattens onto a dotted name, as the CLI
        # flattens it, so that the one = in an entry is the real one.
        parts = []
        for key, item in sorted(value.items()):
            name = f"{prefix}{key}"
            if isinstance(item, dict) and item:
                parts.append(readable(item, prefix=f"{name}."))
            else:
                parts.append(f"{name}={readable(item)}")
        return ", ".join(parts)
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(str(readable(item)) for item in value)
    return value


def pairs_of(resource, columns):
    """(label, value) for each field, for a show page.

    Values go out as they are. `openstack project show` runs none of its
    fields through a formatting column, so an empty options prints as {}
    there and the page says the same.
    """
    return [(column.label, column.of(resource)) for column in columns]


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
        # The create-time parameter, not the answer: compute reports what a
        # server actually has in has_config_drive. The CLI renames that one
        # over the top of this one, which amounts to the same thing.
        "config_drive",
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

# Keys the CLI runs through a formatting column before printing. The rest it
# prints as Python renders them, which is why an empty list shows as nothing
# in the tags row and as [] in the server_groups row just below it. Matching
# that means knowing which row is which.
SERVER_SHOW_FORMATTED = frozenset(
    {
        "addresses",
        "attached_volumes",
        "flavor",
        "metadata",
        "scheduler_hints",
        "security_groups",
        "tags",
    }
)


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


# Bookkeeping openstacksdk hangs on every resource, which no API returns.
SDK_BOOKKEEPING = frozenset({"location"})


def fields_of(item, skips=frozenset(), optional=frozenset(), ignore_none=False):
    """A resource as a dict, under openstacksdk's own names.

    The CLI renames these to what each service called them before printing,
    so a server's `created_at` reaches a terminal as `created` and its
    `power_state` as `OS-EXT-STS:power_state`. Those names are fossils of
    API extensions folded into the APIs years ago, and carrying them into a
    browser buys nothing, so the SDK's names stand. Which fields appear
    still follows the CLI.

    ``ignore_none`` drops attributes the service did not send. Glance needs
    it, because the SDK's image class declares every property an image
    could ever carry and a real one sets a quarter of them. Compute and
    neutron do not, because the nulls they send are answers.
    """
    shown = {}
    for key, value in item.to_dict(ignore_none=ignore_none).items():
        if key in SDK_BOOKKEEPING or key in skips:
            continue
        if key in optional and value is None:
            continue
        shown[key] = value
    return shown


def rendered(shown, formatted=frozenset()):
    """Sorted (label, value) pairs, formatting only what needs it.

    Everything else goes out as it is, so a None prints as None and an
    empty list as [], which is what the CLI prints for a field it does not
    run through a formatting column of its own.
    """
    return sorted(
        (key, readable(value) if key in formatted else value)
        for key, value in shown.items()
    )


def server_details(connection, server):
    """`openstack server show`."""
    shown = fields_of(server, skips=SERVER_SHOW_SKIPS, optional=SERVER_SHOW_OPTIONAL)

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

    # Attached volumes are the one place the CLI throws empty keys away,
    # and it drops the SDK's location with them. A volume otherwise arrives
    # with half a dozen blanks that say nothing about the attachment.
    volumes = shown.get("attached_volumes")
    if volumes:
        shown["attached_volumes"] = [
            {
                key: item
                for key, item in volume.items()
                if item is not None and key != "location"
            }
            for volume in volumes
        ]

    shown["addresses"] = addresses_of(shown.get("addresses"))
    if "power_state" in shown:
        shown["power_state"] = power_state(shown["power_state"])

    return rendered(shown, SERVER_SHOW_FORMATTED)


def image_details(connection, image):
    """`openstack image show`."""
    shown = fields_of(image, ignore_none=True)
    return rendered(shown, containers_in(shown))


def network_details(connection, network):
    """`openstack network show`."""
    # tenant_id is project_id under the name neutron used to use, and
    # if_match is a request header the SDK keeps on the resource.
    shown = fields_of(network, skips={"if_match", "tenant_id"})
    return rendered(shown, containers_in(shown))


def containers_in(shown):
    """The keys holding a list or a dict, which are the ones worth joining."""
    return {
        key
        for key, value in shown.items()
        if isinstance(value, (dict, list, tuple, set, frozenset))
    }


class Resource(typing.NamedTuple):
    """One kind of thing a project holds, and the two pages showing it."""

    slug: str  # the URL segment, and the plural the CLI uses
    heading: str
    index: typing.Any  # connection -> the items
    fetch: typing.Any  # connection, id -> one item
    columns: typing.Any  # the list columns, or connection, items -> them
    details: typing.Any  # connection, item -> (label, value) pairs
    empty: str
    # Set where the CLI sorts a listing itself rather than printing it in
    # the order the service sent. Most do not; `image list` defaults to
    # --sort name:asc and reorders what glance returned.
    sort: typing.Any = None

    def columns_for(self, connection, items):
        if callable(self.columns):
            return self.columns(connection, items)
        return self.columns

    def ordered(self, items):
        return sorted(items, key=self.sort) if self.sort else items


CATALOGUE = {
    resource.slug: resource
    for resource in (
        Resource(
            slug="servers",
            heading="Servers",
            index=lambda connection: connection.compute.servers(),
            fetch=lambda connection, name: connection.compute.get_server(name),
            columns=lambda connection, items: server_list(
                image_names(connection, items)
            ),
            details=server_details,
            empty="No servers in this project.",
        ),
        Resource(
            slug="images",
            heading="Images",
            index=lambda connection: connection.image.images(),
            fetch=lambda connection, name: connection.image.get_image(name),
            columns=(
                Column("ID", "id"),
                Column("Name", "name"),
                Column("Status", "status"),
            ),
            details=image_details,
            empty="No images this project can see.",
            sort=lambda image: str(image.name),
        ),
        Resource(
            slug="networks",
            heading="Networks",
            index=lambda connection: connection.network.networks(),
            fetch=lambda connection, name: connection.network.get_network(name),
            columns=(
                Column("ID", "id"),
                Column("Name", "name"),
                Column("Subnets", lambda net: ", ".join(net.subnet_ids or ())),
            ),
            details=network_details,
            empty="No networks this project can see.",
        ),
    )
}
