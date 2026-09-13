"""Flasgo HTTP application for the local TV controller."""

from __future__ import annotations

from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from flasgo import Body, Flasgo, Request, Response

from .config import AppConfig
from .models import (
    AlertRequest,
    ChannelRequest,
    CommandRequest,
    DeleteTextRequest,
    InputRequest,
    LaunchRequest,
    MuteRequest,
    ResultView,
    SoundOutputRequest,
    StatusView,
    TextRequest,
    ThreeDRequest,
    ToastRequest,
    VolumeRequest,
)
from .storage import StateStore
from .tv import Controller, ControllerError, TVController

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ASSET_PATHS = (PROJECT_ROOT / "static" / "app.css", PROJECT_ROOT / "static" / "app.js")


def _asset_version() -> str:
    digest = sha256()
    for path in _ASSET_PATHS:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def create_app(
    config: AppConfig | None = None,
    controller: Controller | None = None,
) -> Flasgo:
    """Create the loopback-only Flasgo application."""
    runtime_config = config or AppConfig.from_environment()
    state_store = StateStore(
        runtime_config.state_dir,
        tv_host=runtime_config.tv_host,
        certificate_sha256=runtime_config.certificate_sha256,
    )
    tv_controller: Controller = controller or TVController(runtime_config, state_store)

    application = Flasgo(
        static_folder=str(PROJECT_ROOT / "static"),
        settings={
            "DEBUG": False,
            "SECRET_KEY": state_store.load_or_create_web_secret(),
            "ALLOWED_HOSTS": {"127.0.0.1", "localhost"},
            "CSRF_ENABLED": True,
            "CSRF_CHECK_ORIGIN": True,
            "CSRF_REQUIRE_ORIGIN": True,
            "CSRF_COOKIE_SECURE": False,
            "SESSION_COOKIE_SECURE": False,
            "SESSION_COOKIE_HTTP_ONLY": True,
            "SESSION_COOKIE_SAME_SITE": "Strict",
            "MAX_REQUEST_BODY_BYTES": 8_192,
            "MAX_REQUEST_HEAD_BYTES": 8_192,
            "MAX_FORM_FIELDS": 32,
            "MAX_MULTIPART_PARTS": 32,
            "MAX_VALIDATION_DEPTH": 16,
            "MAX_VALIDATION_WORK": 1_000,
            "MAX_VALIDATION_ISSUES": 20,
            "SERVER_LIMIT_CONCURRENCY": 32,
            "ENABLE_DOCS": False,
            "SECURITY_HEADERS": {
                "content-security-policy": (
                    "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
                ),
                "cross-origin-opener-policy": "same-origin",
                "cross-origin-resource-policy": "same-origin",
                "permissions-policy": "camera=(), microphone=(), geolocation=()",
                "referrer-policy": "no-referrer",
                "x-content-type-options": "nosniff",
                "x-frame-options": "DENY",
                "x-xss-protection": "0",
            },
        },
    )
    application.configure_templates(str(PROJECT_ROOT / "templates"))
    application.state.controller = tv_controller

    @application.lifespan
    async def lifespan(_: Flasgo) -> AsyncGenerator[None]:
        yield
        await tv_controller.disconnect()

    @application.before_request
    def require_loopback(request: Request) -> Response | None:
        if request.client_ip is None:
            return Response.json(
                {"error": "Controller access is restricted to this computer."},
                status_code=403,
            )
        try:
            client_address = ip_address(request.client_ip)
        except ValueError:
            return Response.json(
                {"error": "Controller access is restricted to this computer."},
                status_code=403,
            )
        if not client_address.is_loopback:
            return Response.json(
                {"error": "Controller access is restricted to this computer."},
                status_code=403,
            )
        return None

    @application.errorhandler(ControllerError)
    def controller_error(_: Request, error: Exception) -> Response:
        if isinstance(error, ControllerError):
            return Response.json({"error": str(error)}, status_code=error.status_code)
        return Response.json({"error": "Unexpected controller error."}, status_code=500)

    @application.get("/", public=True)
    def index() -> Response:
        return Response.template(
            "index.html",
            templates=application.templates,
            context={
                "title": "LG webOS Controller",
                "tv_host": runtime_config.tv_host,
                "asset_version": _asset_version(),
            },
        )

    @application.get("/api/status", public=True, response_model=StatusView)
    async def status() -> StatusView:
        return await tv_controller.status()

    @application.post("/api/pair", public=True, response_model=ResultView)
    @application.ratelimit(3, per=60)
    async def pair() -> ResultView:
        await tv_controller.pair()
        return ResultView(ok=True, message="Pairing approved and stored.")

    @application.post("/api/connect", public=True, response_model=ResultView)
    @application.ratelimit(10, per=60)
    async def connect() -> ResultView:
        await tv_controller.connect()
        return ResultView(ok=True, message="Connected securely to the TV.")

    @application.post("/api/disconnect", public=True, response_model=ResultView)
    @application.ratelimit(10, per=60)
    async def disconnect() -> ResultView:
        await tv_controller.disconnect()
        return ResultView(ok=True, message="TV connection closed.")

    @application.post("/api/unpair", public=True, response_model=ResultView)
    @application.ratelimit(3, per=60)
    async def unpair() -> ResultView:
        await tv_controller.forget_pairing()
        return ResultView(ok=True, message="Local pairing key removed.")

    @application.post("/api/wake", public=True, response_model=ResultView)
    @application.ratelimit(5, per=60)
    async def wake() -> ResultView:
        await tv_controller.wake()
        return ResultView(ok=True, message="Wake-on-LAN packet sent.")

    @application.post("/api/command", public=True, response_model=ResultView)
    @application.ratelimit(120, per=60)
    async def command(payload: Annotated[CommandRequest, Body()]) -> ResultView:
        await tv_controller.send_command(payload.command)
        return ResultView(ok=True, message="Command sent.")

    @application.post("/api/volume", public=True, response_model=ResultView)
    @application.ratelimit(60, per=60)
    async def volume(payload: Annotated[VolumeRequest, Body()]) -> ResultView:
        await tv_controller.set_volume(payload.level)
        return ResultView(ok=True, message="Volume updated.")

    @application.post("/api/mute", public=True, response_model=ResultView)
    @application.ratelimit(30, per=60)
    async def mute(payload: Annotated[MuteRequest, Body()]) -> ResultView:
        await tv_controller.set_muted(muted=payload.muted)
        return ResultView(ok=True, message="Mute state updated.")

    @application.post("/api/apps/launch", public=True, response_model=ResultView)
    @application.ratelimit(20, per=60)
    async def launch_app(payload: Annotated[LaunchRequest, Body()]) -> ResultView:
        await tv_controller.launch_app(payload.app_id)
        return ResultView(ok=True, message="Application launch requested.")

    @application.post("/api/inputs/select", public=True, response_model=ResultView)
    @application.ratelimit(20, per=60)
    async def select_input(payload: Annotated[InputRequest, Body()]) -> ResultView:
        await tv_controller.select_input(payload.input_id)
        return ResultView(ok=True, message="Input switch requested.")

    @application.post("/api/channels/select", public=True, response_model=ResultView)
    @application.ratelimit(20, per=60)
    async def select_channel(payload: Annotated[ChannelRequest, Body()]) -> ResultView:
        await tv_controller.set_channel(payload.channel_id)
        return ResultView(ok=True, message="Channel switch requested.")

    @application.post("/api/sound-output", public=True, response_model=ResultView)
    @application.ratelimit(12, per=60)
    async def sound_output(payload: Annotated[SoundOutputRequest, Body()]) -> ResultView:
        await tv_controller.set_sound_output(payload.output)
        return ResultView(ok=True, message="Sound output switch requested.")

    @application.post("/api/apps/close", public=True, response_model=ResultView)
    @application.ratelimit(20, per=60)
    async def close_app(payload: Annotated[LaunchRequest, Body()]) -> ResultView:
        await tv_controller.close_app(payload.app_id)
        return ResultView(ok=True, message="Application close requested.")

    @application.post("/api/text", public=True, response_model=ResultView)
    @application.ratelimit(30, per=60)
    async def insert_text(payload: Annotated[TextRequest, Body()]) -> ResultView:
        await tv_controller.insert_text(payload.text, replace=payload.replace)
        return ResultView(ok=True, message="Text sent to the focused TV field.")

    @application.post("/api/text/delete", public=True, response_model=ResultView)
    @application.ratelimit(60, per=60)
    async def delete_text(payload: Annotated[DeleteTextRequest, Body()]) -> ResultView:
        await tv_controller.delete_text(payload.count)
        return ResultView(ok=True, message="Focused TV text deleted.")

    @application.post("/api/text/enter", public=True, response_model=ResultView)
    @application.ratelimit(60, per=60)
    async def text_enter() -> ResultView:
        await tv_controller.send_text_enter()
        return ResultView(ok=True, message="Enter sent to the focused TV field.")

    @application.post("/api/alerts", public=True, response_model=ResultView)
    @application.ratelimit(5, per=60)
    async def create_alert(payload: Annotated[AlertRequest, Body()]) -> ResultView:
        await tv_controller.create_alert(payload.message, payload.button_label)
        return ResultView(ok=True, message="Alert displayed on the TV.")

    @application.post("/api/alerts/close", public=True, response_model=ResultView)
    @application.ratelimit(10, per=60)
    async def close_alert() -> ResultView:
        await tv_controller.close_alert()
        return ResultView(ok=True, message="Controller-created alert closed.")

    @application.post("/api/3d", public=True, response_model=ResultView)
    @application.ratelimit(10, per=60)
    async def set_3d(payload: Annotated[ThreeDRequest, Body()]) -> ResultView:
        await tv_controller.set_3d(enabled=payload.enabled)
        return ResultView(ok=True, message="3D display mode updated.")

    @application.post("/api/toast", public=True, response_model=ResultView)
    @application.ratelimit(10, per=60)
    async def toast(payload: Annotated[ToastRequest, Body()]) -> ResultView:
        await tv_controller.show_toast(payload.message)
        return ResultView(ok=True, message="Notification displayed.")

    return application


app = create_app()
