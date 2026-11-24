"""Turning a resource into the rows and pairs a page prints.

Nothing here knows what a server or a volume is. It knows that the CLI
labels a field one way and openstacksdk names it another, that a listing
is rows and a show page is pairs, and that a value meant for a terminal
needs a little work before it is meant for a browser. What to print, and
of what, is declared next door in resources.py.
"""

import typing

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

def containers_in(shown):
    """The keys holding a list or a dict, which are the ones worth joining."""
    return {
        key
        for key, value in shown.items()
        if isinstance(value, (dict, list, tuple, set, frozenset))
    }