"""LG TV transport and controller tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import aiohttp
import pytest
from aiowebostv import endpoints as webos_endpoints
from aiowebostv.models import WebOsTvInfo, WebOsTvState

from lgtv_controller.config import AppConfig
from lgtv_controller.storage import StateStore
from lgtv_controller.tv import (
    CertificateVerificationError,
    ControllerError,
    InvalidControlError,
    PairingRequiredError,
    SecureWebOsClient,
    TVController,
)

CLIENT_KEY = "b" * 32


class RecordingSession:
    """Record aiohttp WebSocket connection arguments."""

    def __init__(self) -> None:
        self.uri: str | None = None
        self.options: dict[str, Any] = {}
        self.connection = object()

    async def ws_connect(self, uri: str, **options: Any) -> object:
        self.uri = uri
        self.options = options
        return self.connection


class FakeWebOsClient:
    """Minimal in-memory webOS client for controller tests."""

    def __init__(self, client_key: str | None) -> None:
        self.client_key: str | None = client_key or CLIENT_KEY
        self.connected = False
        self.requests: list[tuple[str, dict[str, Any] | None]] = []
        self.buttons: list[str] = []
        self.tv_info = WebOsTvInfo(
            software={"sw_version": "05.50.00"},
            system={"features": {"3d": True}},
        )
        self.tv_state = WebOsTvState(
            power_state={"state": "Active"},
            current_app_id="youtube.leanback.v4",
            sound_output="external_arc",
            muted=False,
            volume=21,
            apps={
                "youtube.leanback.v4": {
                    "id": "youtube.leanback.v4",
                    "title": "YouTube",
                }
            },
            inputs={
                "HDMI_1": {
                    "id": "HDMI_1",
                    "label": "Console",
                    "connected": True,
                }
            },
            current_channel={
                "channelId": "channel-1",
                "channelName": "BBC One",
                "channelNumber": "1",
            },
            channels=[
                {
                    "channelId": "channel-1",
                    "channelName": "BBC One",
                    "channelNumber": "1",
                }
            ],
            is_on=True,
            is_screen_on=True,
        )

    async def connect(self) -> bool:
        self.connected = True
        return True

    async def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    async def request(self, uri: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append((uri, payload))
        if uri == webos_endpoints.GET_SERVICES:
            return {"services": [{"name": "audio"}, {"name": "tv"}]}
        if uri == webos_endpoints.CREATE_ALERT:
            return {"returnValue": True, "alertId": "alert-1"}
        return {"returnValue": True}

    async def button(self, name: str) -> None:
        self.buttons.append(name)


class ClientFactory:
    """Create and retain fake webOS clients."""

    def __init__(self) -> None:
        self.clients: list[FakeWebOsClient] = []

    def __call__(self, _host: str, client_key: str | None, _digest: bytes) -> FakeWebOsClient:
        client = FakeWebOsClient(client_key)
        self.clients.append(client)
        return client


def _controller(tmp_path: Path) -> tuple[TVController, StateStore, ClientFactory]:
    config = AppConfig.create(state_dir=tmp_path / "state")
    store = StateStore(
        config.state_dir,
        tv_host=config.tv_host,
        certificate_sha256=config.certificate_sha256,
    )
    factory = ClientFactory()
    return TVController(config, store, client_factory=factory), store, factory


@pytest.mark.asyncio
async def test_secure_client_rewrites_pointer_socket_and_pins_certificate() -> None:
    config = AppConfig.create(state_dir=Path("/tmp/lgtv-controller-test"))
    client = SecureWebOsClient(config.tv_host, CLIENT_KEY, config.certificate_digest)
    session = RecordingSession()
    client.client_session = cast("Any", session)

    result = await client._ws_connect(
        f"ws://{config.tv_host}:3000/resources/input?token=one",
        8_192,
    )

    assert result is session.connection
    assert session.uri == f"wss://{config.tv_host}:3001/resources/input?token=one"
    assert isinstance(session.options["ssl"], aiohttp.Fingerprint)
    assert session.options["max_msg_size"] == 8_192


@pytest.mark.asyncio
async def test_secure_client_rejects_pointer_socket_for_other_host() -> None:
    config = AppConfig.create(state_dir=Path("/tmp/lgtv-controller-test"))
    client = SecureWebOsClient(config.tv_host, CLIENT_KEY, config.certificate_digest)
    client.client_session = cast("Any", RecordingSession())

    with pytest.raises(CertificateVerificationError, match="unexpected host"):
        await client._ws_connect("ws://192.0.2.9:3000/resources/input", 8_192)


@pytest.mark.asyncio
async def test_pairing_persists_key_and_status_exposes_bounded_catalog(tmp_path: Path) -> None:
    controller, store, factory = _controller(tmp_path)

    await controller.pair()
    status = await controller.status()

    assert store.load_client_key() == CLIENT_KEY
    assert status.connected is True
    assert status.encrypted is True
    assert status.software_version == "05.50.00"
    assert status.apps[0].app_id == "youtube.leanback.v4"
    assert status.inputs[0].input_id == "HDMI_1"
    assert status.channels[0].channel_id == "channel-1"
    assert status.current_channel_name == "BBC One"
    assert status.services == ["audio", "tv"]
    assert status.supports_3d is True
    assert factory.clients[-1].connected is True


@pytest.mark.asyncio
async def test_status_uses_encrypted_hello_version_when_firmware_endpoint_is_unavailable(tmp_path: Path) -> None:
    controller, _store, factory = _controller(tmp_path)
    await controller.pair()
    factory.clients[-1].tv_info.software = {}
    factory.clients[-1].tv_info.hello = {
        "deviceOS": "webOS",
        "deviceOSReleaseVersion": "4.10.2",
    }

    assert (await controller.status()).software_version == "webOS 4.10.2"


@pytest.mark.asyncio
async def test_commands_and_catalog_values_are_allowlisted(tmp_path: Path) -> None:
    controller, _store, factory = _controller(tmp_path)
    await controller.pair()
    client = factory.clients[-1]

    await controller.send_command("volume_up")
    await controller.send_command("home")
    await controller.send_command("red")
    await controller.send_command("digit_7")
    await controller.set_volume(35)
    await controller.set_muted(muted=True)
    await controller.launch_app("youtube.leanback.v4")
    await controller.select_input("HDMI_1")
    await controller.set_channel("channel-1")
    await controller.set_sound_output("external_arc")
    await controller.close_app("youtube.leanback.v4")
    await controller.insert_text("Search", replace=True)
    await controller.delete_text(2)
    await controller.send_text_enter()
    await controller.create_alert("Research alert", "Dismiss")
    assert (await controller.status()).alert_active is True
    await controller.close_alert()
    await controller.set_3d(enabled=True)
    await controller.show_toast("  Hello TV  ")

    assert (webos_endpoints.VOLUME_UP, None) in client.requests
    assert "HOME" in client.buttons
    assert "RED" in client.buttons
    assert "7" in client.buttons
    assert (webos_endpoints.SET_VOLUME, {"volume": 35}) in client.requests
    assert (webos_endpoints.SET_MUTE, {"mute": True}) in client.requests
    assert (webos_endpoints.LAUNCH_APP, {"id": "youtube.leanback.v4"}) in client.requests
    assert (webos_endpoints.SET_INPUT, {"inputId": "HDMI_1"}) in client.requests
    assert (webos_endpoints.SET_CHANNEL, {"channelId": "channel-1"}) in client.requests
    assert (webos_endpoints.CHANGE_SOUND_OUTPUT, {"output": "external_arc"}) in client.requests
    assert (webos_endpoints.LAUNCHER_CLOSE, {"id": "youtube.leanback.v4"}) in client.requests
    assert (webos_endpoints.INSERT_TEXT, {"text": "Search", "replace": True}) in client.requests
    assert (webos_endpoints.SEND_DELETE, {"count": 2}) in client.requests
    assert (webos_endpoints.SEND_ENTER, None) in client.requests
    assert (
        webos_endpoints.CREATE_ALERT,
        {"message": "Research alert", "buttons": [{"label": "Dismiss"}]},
    ) in client.requests
    assert (webos_endpoints.CLOSE_ALERT, {"alertId": "alert-1"}) in client.requests
    assert (webos_endpoints.SET_3D_ON, None) in client.requests
    assert (webos_endpoints.SHOW_MESSAGE, {"message": "Hello TV"}) in client.requests

    with pytest.raises(InvalidControlError, match="did not advertise"):
        await controller.launch_app("com.example.hidden")
    with pytest.raises(InvalidControlError, match="did not advertise"):
        await controller.select_input("HDMI_9")
    with pytest.raises(InvalidControlError, match="did not advertise"):
        await controller.set_channel("channel-9")
    with pytest.raises(InvalidControlError, match="no active alert"):
        await controller.close_alert()


@pytest.mark.asyncio
async def test_invalid_volume_and_notification_are_rejected_before_tv_call(tmp_path: Path) -> None:
    controller, _store, factory = _controller(tmp_path)
    await controller.pair()
    requests_before = len(factory.clients[-1].requests)

    with pytest.raises(InvalidControlError, match="between 0 and 100"):
        await controller.set_volume(101)
    with pytest.raises(InvalidControlError, match="printable"):
        await controller.show_toast("line one\nline two")
    with pytest.raises(InvalidControlError, match="Input text"):
        await controller.insert_text("", replace=False)
    with pytest.raises(InvalidControlError, match="between 1 and 100"):
        await controller.delete_text(0)

    assert len(factory.clients[-1].requests) == requests_before


@pytest.mark.asyncio
async def test_connect_requires_pairing_and_reconnects_from_stored_key(tmp_path: Path) -> None:
    controller, store, factory = _controller(tmp_path)

    status = await controller.status()
    with pytest.raises(PairingRequiredError, match="Pair this controller"):
        await controller.connect()

    assert status.connected is False
    assert status.paired is False

    store.save_client_key(CLIENT_KEY)
    controller = TVController(controller.config, store, client_factory=factory)
    await controller.connect()
    await controller.connect()
    await controller.disconnect()
    await controller.send_command("play")

    assert len(factory.clients) == 2
    assert factory.clients[-1].requests[-1] == (webos_endpoints.MEDIA_PLAY, None)

    await controller.forget_pairing()
    assert store.load_client_key() is None
    assert (await controller.status()).paired is False


@pytest.mark.asyncio
async def test_pairing_state_and_command_failures_are_bounded(tmp_path: Path) -> None:
    controller, _store, factory = _controller(tmp_path)
    controller._pairing = True

    with pytest.raises(PairingRequiredError, match="already in progress"):
        await controller.pair()

    controller._pairing = False
    await controller.pair()
    client = factory.clients[-1]

    async def failing_request(_uri: str, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raise aiohttp.ClientConnectionError

    cast("Any", client).request = failing_request
    with pytest.raises(ControllerError, match="did not accept"):
        await controller.set_volume(20)

    assert (await controller.status()).last_error == "The TV did not accept the command."


@pytest.mark.asyncio
async def test_invalid_identifiers_and_unknown_command_are_rejected(tmp_path: Path) -> None:
    controller, _store, _factory = _controller(tmp_path)

    with pytest.raises(InvalidControlError, match="Application identifier is invalid"):
        await controller.launch_app("contains space")
    with pytest.raises(InvalidControlError, match="Input identifier is invalid"):
        await controller.select_input("\N{SNOWMAN}")
    with pytest.raises(InvalidControlError, match="Unsupported"):
        await controller.send_command(cast("Any", "not-a-command"))
    with pytest.raises(InvalidControlError, match="Sound output is invalid"):
        await controller.set_sound_output(cast("Any", "raw_output"))

    controller._supports_3d = False
    with pytest.raises(InvalidControlError, match="does not advertise 3D"):
        await controller.set_3d(enabled=True)
