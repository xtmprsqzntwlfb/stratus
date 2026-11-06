"""The three configuration layers, and which of them wins."""

import pytest

import stratus


@pytest.fixture
def local_settings(tmp_path, monkeypatch):
    """Write a local_settings.py and make create_app read that one."""

    def write(text):
        path = tmp_path / "local_settings.py"
        path.write_text(text)
        monkeypatch.setenv(stratus.LOCAL_SETTINGS_VARIABLE, str(path))
        return path

    return write


def test_defaults_alone_are_enough_to_start(monkeypatch):
    import os

    monkeypatch.setenv(stratus.LOCAL_SETTINGS_VARIABLE, os.devnull)
    app = stratus.create_app()
    assert app.config["AUTH_URL"] == ""
    assert app.config["USER_DOMAIN_NAME"] == "Default"


def test_local_settings_override_the_defaults(local_settings):
    local_settings('AUTH_URL = "http://cloud.test/identity/v3"\n')
    assert stratus.create_app().config["AUTH_URL"] == "http://cloud.test/identity/v3"


def test_local_settings_are_ordinary_python(local_settings):
    """Horizon builds its endpoint out of OPENSTACK_HOST, so this must too."""
    local_settings(
        'OPENSTACK_HOST = "cloud.test"\n'
        'AUTH_URL = f"http://{OPENSTACK_HOST}/identity/v3"\n'
    )
    assert stratus.create_app().config["AUTH_URL"] == "http://cloud.test/identity/v3"


def test_lowercase_names_are_not_settings(local_settings):
    local_settings('helper = "scratch"\nAUTH_URL = "http://cloud.test/v3"\n')
    assert "helper" not in stratus.create_app().config


def test_the_environment_overrides_local_settings(local_settings, monkeypatch):
    local_settings('AUTH_URL = "http://cloud.test/identity/v3"\n')
    monkeypatch.setenv("STRATUS_AUTH_URL", "http://other.test/v3")
    assert stratus.create_app().config["AUTH_URL"] == "http://other.test/v3"


def test_a_missing_file_is_only_silent_when_unasked_for(tmp_path, monkeypatch):
    monkeypatch.setenv(stratus.LOCAL_SETTINGS_VARIABLE, str(tmp_path / "absent.py"))
    with pytest.raises(FileNotFoundError):
        stratus.create_app()


def test_running_without_local_settings_is_allowed(monkeypatch):
    """A checkout with no local_settings.py still starts."""
    monkeypatch.delenv(stratus.LOCAL_SETTINGS_VARIABLE, raising=False)
    monkeypatch.setattr(stratus, "LOCAL_SETTINGS", "no_such_settings.py")
    assert stratus.create_app().config["USER_DOMAIN_NAME"] == "Default"
