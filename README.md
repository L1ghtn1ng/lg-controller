# LG webOS Controller

A local Flasgo web interface for an LG webOS TV. The controller uses the TV's supported SSAP WebSocket API for remote-control operations on one explicitly configured television.

Tested on an LG OLED55B9PLA.

## Security model

- The web server is intended to bind only to `127.0.0.1` and also rejects non-loopback clients at the application boundary.
- Browser mutations require Flasgo's signed double-submit CSRF token and a same-origin request.
- Host headers are limited to `localhost` and `127.0.0.1`; CORS and API documentation are disabled.
- Every TV WebSocket is rewritten to `wss://<LGTV_HOST>:3001` and verified against `LGTV_CERT_SHA256`.
- The UI exposes a fixed command allowlist. Application and input identifiers must also be present in the catalog returned by the TV.
- The client key and Flasgo signing secret are written atomically under `~/.config/lgtv-controller` with owner-only permissions.

The TV uses a self-signed certificate, so the configured fingerprint is the trust anchor. If the TV is factory-reset or its certificate changes, inspect the new certificate before changing `LGTV_CERT_SHA256`.

## Controls

- All known webOS pointer-button semantics, including number and colour keys, guide, menus, captions, audio description, SAP, teletext, recording, zoom, app shortcuts, media controls, and confirmed power actions.
- Catalog-bound application launch/close, input selection, and direct channel selection. The channel catalog is available only while the TV publishes it, usually when Live TV is active.
- Absolute volume, mute, and a bounded set of documented sound-output identifiers.
- Focused-field text insertion, replacement, deletion, and enter actions.
- Toast notifications and controller-owned modal alerts.
- Read-only advertised service discovery and model-gated 3D controls.

The controller does not expose arbitrary SSAP payloads, private Luna calls, external picture calibration, or settings writes, because those lack a stable model-independent contract.

## Setup

Python 3.14 and [uv](https://docs.astral.sh/uv/) are required. The application reads process environment variables only; it does not load `.env` itself.

Copy `env.example` and replace the example values with this TV's IPv4 address, Wi-Fi MAC, subnet broadcast, and certificate fingerprint. The IPv4 address and Wi-Fi MAC are in the television's network settings; Wake-on-LAN needs the Wi-Fi MAC, not Ethernet. The broadcast address is the TV subnet's `/24` broadcast, for example `192.168.0.255`.

Obtain `LGTV_CERT_SHA256` while the TV is awake:

```bash
openssl s_client -connect 192.168.0.1:3001 </dev/null 2>/dev/null \
  | openssl x509 -noout -fingerprint -sha256
```

Strip colons from the fingerprint; the value must be 64 hexadecimal characters.

```bash
cp env.example .env
# edit .env with this TV's IPv4, Wi-Fi MAC, /24 broadcast, and cert fingerprint
uv sync --locked --all-groups
uv run --env-file .env flasgo run lgtv_controller.app:app --host 127.0.0.1 --port 8080
```

Open <http://127.0.0.1:8080>. Select **Pair TV**, then approve the prompt on the television. The key is reused on later starts.

Wake-on-LAN uses the configured Wi-Fi MAC and broadcast address. The television must have its mobile wake setting enabled for that control to work.

## Configuration

Shipped values are examples, not a live device. Set environment variables before starting the server:

| Variable | Example | Purpose |
| --- | --- | --- |
| `LGTV_HOST` | `192.168.0.1` | Exact IPv4 address of the TV |
| `LGTV_CERT_SHA256` | 64-character SHA-256 hex | WSS trust anchor |
| `LGTV_MAC` | `AA:BB:CC:DD:EE:FF` | Wake-on-LAN target |
| `LGTV_BROADCAST` | `192.168.0.255` | Wake-on-LAN broadcast address |
| `LGTV_STATE_DIR` | `~/.config/lgtv-controller` | Private application state |

Only environment configuration is accepted; browser requests cannot change the TV host, certificate, MAC address, or broadcast target.

## Validation

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run pytest
LGTV_STATE_DIR=/tmp/lgtv-controller-check uv run flasgo check lgtv_controller.app:app
LGTV_STATE_DIR=/tmp/lgtv-controller-check uv run flasgo routes lgtv_controller.app:app --policy
```

The application intentionally uses non-secure cookies over loopback HTTP. Do not bind it to `0.0.0.0`; a LAN-facing deployment needs HTTPS and user authentication in addition to the current controls.

## License

MIT. This project is not affiliated with LG Electronics.
