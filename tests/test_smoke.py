"""Smoke tests for the GeoPort Flask app (no device required).

Run from the repo root:
    .venv\\Scripts\\python -m pytest tests -q
(or any pytest 7+ on PATH)

These exercise the HTTP layer and the non-device state (validation, saved
locations, log tail, health/route status shapes). Device-dependent flows
(connect, set_location, route walking) need a real iOS device.
"""
import importlib.util
import json
import os
import sys

import pytest


@pytest.fixture(scope="module")
def mod(tmp_path_factory):
    """Import src/main.py as a module with its on-disk state in a temp dir.

    - sys.argv is stubbed so the module-level argparse doesn't see pytest's
      arguments.
    - cwd is a temp dir so GeoPort.log lands there.
    - home_dir is a temp dir so saved locations don't touch the real home.
    The __main__ guard keeps app.run() from executing on import.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_py = os.path.join(root, "src", "main.py")

    tmp = tmp_path_factory.mktemp("geoport")
    old_cwd, old_argv = os.getcwd(), sys.argv
    os.chdir(str(tmp))
    sys.argv = [sys.argv[0]]
    try:
        spec = importlib.util.spec_from_file_location("geoport_main", main_py)
        m = importlib.util.module_from_spec(spec)
        # Register before exec: Flask resolves its root/template paths from
        # the module in sys.modules, not from the spec.
        sys.modules["geoport_main"] = m
        spec.loader.exec_module(m)
        m.home_dir = str(tmp)  # keep ~/.geoport writes inside the sandbox
        yield m
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
        sys.modules.pop("geoport_main", None)


@pytest.fixture()
def client(mod):
    return mod.app.test_client()


def test_index_serves_ui(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'class="dark-mode"' in body          # dark mode is the default
    assert "tunnelBanner" in body               # watchdog banner
    assert "savedLocations" in body             # presets UI
    assert "activityLogPanel" in body           # live log panel
    assert "api.geoport.me" not in body         # telemetry removed
    assert "NordVPN" not in body                # promo banner removed
    assert r.headers.get("Cache-Control") == "no-store"


def test_connection_status_shape(client):
    r = client.get("/connection_status")
    assert r.status_code == 200
    data = r.get_json()
    for key in ("status", "udid", "rsd_data", "last_location"):
        assert key in data
    assert data["status"] in ("disconnected", "connecting", "connected")


def test_health_shape(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    for key in ("connected", "tunnel_ok", "location_active",
                "route_active", "route_paused", "route_error"):
        assert key in data


def test_route_status_shape(client):
    r = client.get("/route_status")
    assert r.status_code == 200
    data = r.get_json()
    assert data["points"] == 0
    assert data["active"] is False
    assert 0.0 <= data["progress"] <= 1.0


def test_route_start_validation(client):
    # fewer than 2 points
    r = client.post("/route_start", json={"points": [[1.0, 2.0]]})
    assert r.status_code == 400
    # invalid point shape
    r = client.post("/route_start", json={"points": [["nope"]]})
    assert r.status_code == 400
    # out-of-range speed
    r = client.post("/route_start",
                    json={"points": [[1.0, 2.0], [3.0, 4.0]], "speed_kmh": 999})
    assert r.status_code == 400
    # no device connected -> 400 even with a valid route
    r = client.post("/route_start",
                    json={"points": [[1.0, 2.0], [3.0, 4.0]], "speed_kmh": 5})
    assert r.status_code == 400
    assert "connect" in r.get_json()["error"].lower()


def test_haversine(mod):
    # Sydney -> Melbourne ~ 713 km (great circle)
    d = mod.haversine_m(-33.8688, 151.2093, -37.8136, 144.9631)
    assert 700_000 < d < 730_000
    assert mod.haversine_m(0, 0, 0, 0) == 0


def test_saved_locations_roundtrip(client):
    r = client.post("/locations", json={"name": "Test", "lat": 1.5, "lng": 2.5})
    assert r.status_code == 200
    items = r.get_json()
    assert {"name": "Test", "lat": 1.5, "lng": 2.5} in items

    # upsert: same name replaces
    r = client.post("/locations", json={"name": "Test", "lat": 3.5, "lng": 4.5})
    names = [i["name"] for i in r.get_json()]
    assert names.count("Test") == 1

    # validation
    assert client.post("/locations", json={"name": "", "lat": 0, "lng": 0}).status_code == 400
    assert client.post("/locations", json={"name": "X", "lat": 999, "lng": 0}).status_code == 400

    # delete
    r = client.delete("/locations/Test")
    assert r.status_code == 200
    assert [i["name"] for i in r.get_json()] == []
    assert client.get("/locations").get_json() == []


def test_log_tail(client):
    r = client.get("/log_tail?lines=5")
    assert r.status_code == 200
    assert r.content_type.startswith("text/plain")
    assert len(r.data.decode("utf-8").strip().splitlines()) <= 5


def test_token_off_by_default(client):
    # Without GEOPORT_TOKEN, mutating endpoints must not 401.
    r = client.post("/route_stop")
    assert r.status_code != 401


def test_api_md_lists_new_endpoints(mod):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    api_md = open(os.path.join(root, "API.md"), encoding="utf-8").read()
    for ep in ("/route_start", "/route_stop", "/route_status", "/health",
               "/locations", "/log_tail", "/connection_status"):
        assert ep in api_md
