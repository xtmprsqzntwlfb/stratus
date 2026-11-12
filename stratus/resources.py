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


def pairs_of(resource, columns):
    """(label, value) for each field, for a show page."""
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
# fields, so it is described by what to leave out and what to rename instead.

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

# The SDK renames what compute returns; the CLI renames it back. Note that
# project_id is absent: the CLI maps it to tenant_id and then back again a
# hundred lines later, so the two renames cancel and the field keeps its
# name. Copying only the first half of that round trip is a mistake.
SERVER_SHOW_NAMES = {
    "access_ipv4": "accessIPv4",
    "access_ipv6": "accessIPv6",
    "admin_password": "adminPass",
    "attached_volumes": "volumes_attached",
    "availability_zone": "OS-EXT-AZ:availability_zone",
    "compute_host": "OS-EXT-SRV-ATTR:host",
    "created_at": "created",
    "disk_config": "OS-DCF:diskConfig",
    "fault": "fault",
    "has_config_drive": "config_drive",
    "host_id": "hostId",
    "hostname": "OS-EXT-SRV-ATTR:hostname",
    "hypervisor_hostname": "OS-EXT-SRV-ATTR:hypervisor_hostname",
    "instance_name": "OS-EXT-SRV-ATTR:instance_name",
    "is_locked": "locked",
    "kernel_id": "OS-EXT-SRV-ATTR:kernel_id",
    "launch_index": "OS-EXT-SRV-ATTR:launch_index",
    "launched_at": "OS-SRV-USG:launched_at",
    "metadata": "properties",
    "power_state": "OS-EXT-STS:power_state",
    "ramdisk_id": "OS-EXT-SRV-ATTR:ramdisk_id",
    "reservation_id": "OS-EXT-SRV-ATTR:reservation_id",
    "root_device_name": "OS-EXT-SRV-ATTR:root_device_name",
    "task_state": "OS-EXT-STS:task_state",
    "terminated_at": "OS-SRV-USG:terminated_at",
    "updated_at": "updated",
    "user_data": "OS-EXT-SRV-ATTR:user_data",
    "vm_state": "OS-EXT-STS:vm_state",
}


# The CLI prints the power state as a word rather than the number compute
# returns. Index is the number; the gaps are states nova never reports.
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
    """`openstack server show`: every field, renamed and sorted by name."""
    shown = {}
    for key, value in server.to_dict().items():
        if key in SERVER_SHOW_SKIPS:
            continue
        if key in SERVER_SHOW_OPTIONAL and value is None:
            continue
        shown[SERVER_SHOW_NAMES.get(key, key)] = value

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
    if "OS-EXT-STS:power_state" in shown:
        shown["OS-EXT-STS:power_state"] = power_state(shown["OS-EXT-STS:power_state"])

    return sorted(shown.items())
