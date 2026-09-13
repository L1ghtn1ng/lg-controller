"""Flasgo HTTP boundary tests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

from lgtv_controller.app import create_app
from lgtv_controller.config import AppConfig
from lgtv_controller.models import RemoteCommand, SoundOutput, StatusView
from lgtv_controller.tv import ControllerError


class FakeController:
    """Record route-to-controller calls without touching a TV."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.calls: list[tuple[str, object | None]] = []
        self.disconnected = False
        self.connect_error: ControllerError | None = None

    async def status(self) -> StatusView:
        return StatusView(
            host="192.168.0.1",
            paired=True,
            connected=True,
            encrypted=True,
            pairing=False,
            is_on=True,
            is_screen_on=True,
            power_state="Active",
            volume=18,
            muted=False,
            current_app_id="com.webos.app.livetv",
            current_app_title="Live TV",
            sound_output="tv_speaker",
            software_version="05.50.00",
            last_error=None,
        )

    async def pair(self) -> None:
        self.calls.append(("pair", None))

    async def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.calls.append(("connect", None))

    async def disconnect(self) -> None:
        self.disconnected = True
        self.calls.append(("disconnect", None))

    async def forget_pairing(self) -> None:
        self.calls.append(("forget_pairing", None))

    async def wake(self) -> None:
        self.calls.append(("wake", None))

    async def send_command(self, command: RemoteCommand) -> None:
        self.commands.append(command)
        self.calls.append(("send_command", command))

    async def set_volume(self, level: int) -> None:
        self.calls.append(("set_volume", level))

    async def set_muted(self, *, muted: bool) -> None:
        self.calls.append(("set_muted", muted))

    async def launch_app(self, app_id: str) -> None:
        self.calls.append(("launch_app", app_id))

    async def select_input(self, input_id: str) -> None:
        self.calls.append(("select_input", input_id))

    async def set_channel(self, channel_id: str) -> None:
        self.calls.append(("set_channel", channel_id))

    async def set_sound_output(self, output: SoundOutput) -> None:
        self.calls.append(("set_sound_output", output))

    async def close_app(self, app_id: str) -> None:
        self.calls.append(("close_app", app_id))

    async def insert_text(self, text: str, *, replace: bool) -> None:
        self.calls.append(("insert_text", (text, replace)))

    async def delete_text(self, count: int) -> None:
        self.calls.append(("delete_text", count))

    async def send_text_enter(self) -> None:
        self.calls.append(("send_text_enter", None))

    async def create_alert(self, message: str, button_label: str) -> None:
        self.calls.append(("create_alert", (message, button_label)))

    async def close_alert(self) -> None:
        self.calls.append(("close_alert", None))

    async def set_3d(self, *, enabled: bool) -> None:
        self.calls.append(("set_3d", enabled))

    async def show_toast(self, message: str) -> None:
        self.calls.append(("show_toast", message))


def _csrf_headers(client: Any) -> dict[str, str]:
    token = client.cookies["flasgo-csrf"]
    return {
        "origin": "http://localhost",
        "x-csrf-token": token,
    }


def _app(tmp_path: Path) -> tuple[Any, FakeController]:
    controller = FakeController()
    config = AppConfig.create(state_dir=tmp_path / "state")
    return create_app(config, controller), controller


def test_index_has_security_headers_and_seeds_csrf(tmp_path: Path) -> None:
    application, _controller = _app(tmp_path)
    response = application.test_client().get("/")

    assert response.status_code == 200
    assert "LG webOS Controller" in response.text
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "flasgo-csrf=" in response.headers["set-cookie"]
    assert "no-store" in response.headers["cache-control"]
    stylesheet_version = re.search(r"/static/app\.css\?v=([0-9a-f]{12})", response.text)
    script_version = re.search(r"/static/app\.js\?v=([0-9a-f]{12})", response.text)
    assert stylesheet_version is not None
    assert script_version is not None
    assert stylesheet_version.group(1) == script_version.group(1)


def test_host_header_and_missing_csrf_are_rejected(tmp_path: Path) -> None:
    application, _controller = _app(tmp_path)
    client = application.test_client()

    assert client.get("/", headers={"host": "attacker.invalid"}).status_code == 400
    assert client.post("/api/command", json={"command": "home"}).status_code == 403


def test_typed_command_is_dispatched_with_valid_csrf(tmp_path: Path) -> None:
    application, controller = _app(tmp_path)
    client = application.test_client()
    client.get("/")

    response = client.post(
        "/api/command",
        json={"command": "home"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "Command sent."}
    assert controller.commands == ["home"]


def test_unknown_command_and_extra_fields_are_rejected(tmp_path: Path) -> None:
    application, controller = _app(tmp_path)
    client = application.test_client()
    client.get("/")
    headers = _csrf_headers(client)

    unknown = client.post(
        "/api/command",
        json={"command": "raw_ssap"},
        headers=headers,
    )
    extra = client.post(
        "/api/command",
        json={"command": "home", "uri": "ssap://system/turnOff"},
        headers=headers,
    )

    assert unknown.status_code == 422
    assert extra.status_code == 422
    assert controller.commands == []


def test_ui_exposes_every_typed_remote_command() -> None:
    markup = (Path(__file__).parents[1] / "templates" / "index.html").read_text()
    rendered_commands = set(re.findall(r'data-command="([^"]+)"', markup))

    assert rendered_commands == set(get_args(RemoteCommand))


def test_all_bounded_mutation_routes_dispatch_expected_values(tmp_path: Path) -> None:
    application, controller = _app(tmp_path)
    client = application.test_client()
    client.get("/")
    headers = _csrf_headers(client)
    requests = (
        ("/api/pair", None),
        ("/api/connect", None),
        ("/api/disconnect", None),
        ("/api/unpair", None),
        ("/api/wake", None),
        ("/api/volume", {"level": 32}),
        ("/api/mute", {"muted": True}),
        ("/api/apps/launch", {"app_id": "youtube.leanback.v4"}),
        ("/api/inputs/select", {"input_id": "HDMI_1"}),
        ("/api/channels/select", {"channel_id": "channel-1"}),
        ("/api/sound-output", {"output": "external_arc"}),
        ("/api/apps/close", {"app_id": "youtube.leanback.v4"}),
        ("/api/text", {"text": "Search phrase", "replace": True}),
        ("/api/text/delete", {"count": 2}),
        ("/api/text/enter", None),
        ("/api/alerts", {"message": "Research alert", "button_label": "Dismiss"}),
        ("/api/alerts/close", None),
        ("/api/3d", {"enabled": False}),
        ("/api/toast", {"message": "Test notification"}),
    )

    responses = [client.post(path, json=payload, headers=headers) for path, payload in requests]

    assert all(response.status_code == 200 for response in responses)
    assert controller.calls == [
        ("pair", None),
        ("connect", None),
        ("disconnect", None),
        ("forget_pairing", None),
        ("wake", None),
        ("set_volume", 32),
        ("set_muted", True),
        ("launch_app", "youtube.leanback.v4"),
        ("select_input", "HDMI_1"),
        ("set_channel", "channel-1"),
        ("set_sound_output", "external_arc"),
        ("close_app", "youtube.leanback.v4"),
        ("insert_text", ("Search phrase", True)),
        ("delete_text", 2),
        ("send_text_enter", None),
        ("create_alert", ("Research alert", "Dismiss")),
        ("close_alert", None),
        ("set_3d", False),
        ("show_toast", "Test notification"),
    ]


def test_controller_errors_are_returned_as_bounded_json(tmp_path: Path) -> None:
    application, controller = _app(tmp_path)
    client = application.test_client()
    client.get("/")
    controller.connect_error = ControllerError("TV unavailable")

    response = client.post("/api/connect", headers=_csrf_headers(client))

    assert response.status_code == 503
    assert response.json() == {"error": "TV unavailable"}


def test_lifespan_disconnects_controller(tmp_path: Path) -> None:
    application, controller = _app(tmp_path)

    with application.test_client() as client:
        assert client.get("/api/status").status_code == 200

    assert controller.disconnected is True
