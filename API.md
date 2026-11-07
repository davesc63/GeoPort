# GeoPort HTTP API

The web UI is just a client of this API — you can drive GeoPort from scripts,
Shortcuts/Tasker, CI, or a phone (see "Remote use" below).

Base URL: `http://127.0.0.1:54321` (the app binds to localhost only).

## Authentication (optional)

Set the `GEOPORT_TOKEN` environment variable before starting the app:

```powershell
$env:GEOPORT_TOKEN = "some-long-secret"
```

With a token set, all mutating requests (POST/DELETE) require it via the
`X-GeoPort-Token` header or a `?token=...` query parameter. Read-only status
endpoints stay open so dashboards can poll. The web UI handles the token
automatically (it is embedded in the page). Without the env var, the API is
unauthenticated on localhost.

## Endpoints

### Status

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | The web UI |
| `/connection_status` | GET | `status` (`disconnected`/`connecting`/`connected`), `udid`, `rsd_data` (tunnel host/port), `last_location` (`{lat,lng}` of the simulated spot, if any) |
| `/health` | GET | Watchdog view: `connected`, `tunnel_ok`, `location_active`, `route_active`, `route_paused`, `route_error` |
| `/route_status` | GET | Route playback: `active`, `paused`, `finished`, `error`, `points`, `index`, `progress` (0–1), `speed_kmh`, `current` `{lat,lng}` |
| `/list_devices` | GET | Devices currently visible to usbmuxd (USB + Wi-Fi) |
| `/log_tail?lines=40` | GET | Tail of `GeoPort.log` (plain text, max 200 lines) |

### Device / connection

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `/connect_device` | POST | `{udid, ios_version, connType: "USB"\|"WIFI", wifiState}` | Pair + open the tunnel (USB TCP tunnel on iOS 17+) |
| `/release_connection` | POST | – | Forget the tunnel for the current device (UI "Disconnect") |
| `/enable_developer_mode` | POST | `{udid, connType}` | Push the developer-mode prompt onto the device |
| `/mount_developer_image` | POST | – | Mount the DVT developer image (pre-iOS 17) |
| `/stop_tunnel` | POST | – | Stop the tunnel thread |

### Location

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `/update_location` | POST | `{lat, lng}` | Remember the coordinates (no device I/O) |
| `/set_location` | POST | – | Start spoofing the remembered location (stops any active route) |
| `/stop_location` | POST | – | Stop spoofing and clear the device location (stops any active route) |

### Route playback (server-side)

The server walks a route at a constant speed, holding **one** RSD/DVT session
open for the whole route. Progress is observable via `/route_status`.

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `/route_start` | POST | `{points: [[lat,lng], …] or [{lat,lng}, …], speed_kmh: 0.5–250, start_index?: n}` | Start walking (default speed 5 km/h; resumes at `start_index`) |
| `/route_stop` | POST | `{hold?: true}` | Stop + clear the device location; `hold: true` = pause (keeps the last point spoofed) |
| `/route_status` | GET | – | See above |

Dwell time per point = distance-to-next-point ÷ speed (great-circle), so a
densely sampled route walks smoothly. On natural completion the device's real
location is restored.

### Saved location presets

Stored in `~/.geoport/locations.json`.

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `/locations` | GET | – | List presets |
| `/locations` | POST | `{name, lat, lng}` | Create/update a preset |
| `/locations/<name>` | DELETE | – | Remove a preset |

### Fuel (external data, best effort)

| Endpoint | Method | Description |
|---|---|---|
| `/api/fuel_types?region=All` | GET | Fuel types available for the region |
| `/api/data/<type>?region=All` | GET | Nearest station for a fuel type |

### Lifecycle

| Endpoint | Method | Description |
|---|---|---|
| `/exit` | POST | Shut down the app (the UI Exit button) |

## Example: drive it with curl

```bash
# status
curl -s http://127.0.0.1:54321/connection_status

# walk a route at 8 km/h (needs a connected device)
curl -s -X POST http://127.0.0.1:54321/route_start \
  -H 'Content-Type: application/json' \
  -d '{"points":[[-10.3333,-53.2],[-10.3340,-53.2010],[-10.3352,-53.2044]], "speed_kmh": 8}'

# pause / stop
curl -s -X POST http://127.0.0.1:54321/route_stop -H 'Content-Type: application/json' -d '{"hold": true}'
curl -s -X POST http://127.0.0.1:54321/route_stop
```
