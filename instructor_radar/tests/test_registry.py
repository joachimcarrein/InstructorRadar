import pytest

from app.providers import available, get_provider
from app.providers.biqsdrive import ALLOWED, BiqsDriveProvider, _request


def test_registry_lists_providers():
    assert "biqsdrive" in available()
    assert "demo" in available()


def test_get_provider():
    provider = get_provider("biqsdrive")
    assert isinstance(provider, BiqsDriveProvider)
    assert provider.name == "biqsdrive"
    for method in ("login", "fetch_events", "fetch_student", "logout"):
        assert callable(getattr(provider, method))


def test_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("nope")


def test_config_yaml_lists_every_real_provider():
    from pathlib import Path

    config = (Path(__file__).parents[1] / "config.yaml").read_text(encoding="utf-8")
    for name in available():
        if name != "demo":
            assert name in config


async def test_only_read_only_endpoints_allowed():
    import re

    actions = {m.group(1) for _, path in ALLOWED if (m := re.search(r"action=(\w+)", path))}
    # edit_customer is the web app's (read-only) "load student" call; everything else must be a get_*.
    assert all(a.startswith("get_") or a == "edit_customer" for a in actions), actions
    assert all(method == "GET" or path in ("/login.php", "/events.php") or "action=" in path for method, path in ALLOWED)
    with pytest.raises(AssertionError):
        await _request(None, "POST", "/php/crud_customer.php?action=anonymiseStudent&id=1")
