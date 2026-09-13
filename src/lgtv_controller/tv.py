"""Certificate-pinned LG webOS client and controller boundary."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from aiowebostv import WebOsClient
from aiowebostv import endpoints as webos_endpoints
from aiowebostv.exceptions import WebOsTvError

from .models import AppView, ChannelView, InputView, RemoteCommand, SoundOutput, StatusView
from .storage import StateFileError, StateStore

if TYPE_CHECKING:
    from aiowebostv.models import WebOsTvInfo, WebOsTvState

    from .config import AppConfig

LOGGER = logging.getLogger(__name__)

_MAIN_WEBSOCKET_PORT = 3001
_MAX_VOLUME = 100
_MAX_TOAST_LENGTH = 120
_MAX_TEXT_LENGTH = 500
_MAX_ALERT_LENGTH = 240
_MAX_ALERT_BUTTON_LENGTH = 32
_MAX_DELETE_COUNT = 100
_MAX_IDENTIFIER_LENGTH = 128
_FIRST_PRINTABLE_ASCII = 32
_FIRST_NON_SPACE_ASCII = 33

_SSAP_COMMANDS: dict[RemoteCommand, str] = {
    "channel_down": webos_endpoints.TV_CHANNEL_DOWN,
    "channel_up": webos_endpoints.TV_CHANNEL_UP,
    "fast_forward": webos_endpoints.MEDIA_FAST_FORWARD,
    "media_close": webos_endpoints.MEDIA_CLOSE,
    "pause": webos_endpoints.MEDIA_PAUSE,
    "play": webos_endpoints.MEDIA_PLAY,
    "power_off": webos_endpoints.POWER_OFF,
    "rewind": webos_endpoints.MEDIA_REWIND,
    "screen_off": webos_endpoints.TURN_OFF_SCREEN,
    "screen_on": webos_endpoints.TURN_ON_SCREEN,
    "stop": webos_endpoints.MEDIA_STOP,
    "volume_down": webos_endpoints.VOLUME_DOWN,
    "volume_up": webos_endpoints.VOLUME_UP,
}

_POINTER_COMMANDS: dict[RemoteCommand, str] = {
    "amazon": "AMAZON",
    "asterisk": "ASTERISK",
    "audio_description": "AD",
    "aspect_ratio": "ASPECT_RATIO",
    "back": "BACK",
    "blue": "BLUE",
    "closed_captions": "CC",
    "dash": "DASH",
    "digit_0": "0",
    "digit_1": "1",
    "digit_2": "2",
    "digit_3": "3",
    "digit_4": "4",
    "digit_5": "5",
    "digit_6": "6",
    "digit_7": "7",
    "digit_8": "8",
    "digit_9": "9",
    "down": "DOWN",
    "enter": "ENTER",
    "exit": "EXIT",
    "green": "GREEN",
    "guide": "GUIDE",
    "home": "HOME",
    "info": "INFO",
    "input_hub": "INPUT_HUB",
    "left": "LEFT",
    "list": "LIST",
    "live_zoom": "LIVE_ZOOM",
    "magnifier_zoom": "MAGNIFIER_ZOOM",
    "menu": "MENU",
    "mute_toggle": "MUTE",
    "my_apps": "MYAPPS",
    "netflix": "NETFLIX",
    "power_toggle": "POWER",
    "program": "PROGRAM",
    "quick_menu": "QMENU",
    "recent": "RECENT",
    "record": "RECORD",
    "red": "RED",
    "right": "RIGHT",
    "sap": "SAP",
    "screen_remote": "SCREEN_REMOTE",
    "teletext": "TELETEXT",
    "text_option": "TEXTOPTION",
    "three_d_mode": "3D_MODE",
    "up": "UP",
    "yellow": "YELLOW",
}

_SOUND_OUTPUTS: frozenset[SoundOutput] = frozenset(
    {
        "bt_soundbar",
        "external_arc",
        "external_optical",
        "external_speaker",
        "headphone",
        "lineout",
        "mobile_phone",
        "soundbar",
        "tv_external_headphone",
        "tv_external_speaker",
        "tv_speaker",
        "tv_speaker_bluetooth",
        "tv_speaker_headphone",
        "wisa_speaker",
    }
)

_PAIRING_PERMISSIONS = (
    "CONTROL_AUDIO",
    "CONTROL_DISPLAY",
    "CONTROL_INPUT_MEDIA_PLAYBACK",
    "CONTROL_INPUT_MEDIA_RECORDING",
    "CONTROL_INPUT_TEXT",
    "CONTROL_INPUT_TV",
    "CONTROL_MOUSE_AND_KEYBOARD",
    "CONTROL_POWER",
    "CONTROL_TV_SCREEN",
    "LAUNCH",
    "READ_APP_STATUS",
    "READ_CURRENT_CHANNEL",
    "READ_INPUT_DEVICE_LIST",
    "READ_INSTALLED_APPS",
    "READ_NETWORK_STATE",
    "READ_POWER_STATE",
    "READ_RUNNING_APPS",
    "READ_SETTINGS",
    "READ_TV_CHANNEL_LIST",
    "READ_UPDATE_INFO",
    "CLOSE",
    "WRITE_NOTIFICATION_ALERT",
    "WRITE_NOTIFICATION_TOAST",
)


class ControllerError(RuntimeError):
    """A safe controller error suitable for an HTTP response."""

    status_code = 503


class PairingRequiredError(ControllerError):
    """Raised when the TV has not approved this controller."""

    status_code = 409


class InvalidControlError(ControllerError):
    """Raised when a requested control value is outside the allowed set."""

    status_code = 422


class CertificateVerificationError(ControllerError):
    """Raised when the TV certificate does not match the configured pin."""

    status_code = 502


class Controller(Protocol):
    """Controller operations consumed by the HTTP boundary."""

    async def pair(self) -> None:
        """Pair with the configured TV."""
        ...

    async def connect(self) -> None:
        """Connect using stored pairing state."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the TV."""
        ...

    async def forget_pairing(self) -> None:
        """Remove local pairing state."""
        ...

    async def wake(self) -> None:
        """Send a Wake-on-LAN packet."""
        ...

    async def send_command(self, command: RemoteCommand) -> None:
        """Send an allowlisted remote command."""
        ...

    async def set_volume(self, level: int) -> None:
        """Set the TV volume."""
        ...

    async def set_muted(self, *, muted: bool) -> None:
        """Set the TV mute state."""
        ...

    async def launch_app(self, app_id: str) -> None:
        """Launch an advertised TV application."""
        ...

    async def select_input(self, input_id: str) -> None:
        """Select an advertised TV input."""
        ...

    async def set_channel(self, channel_id: str) -> None:
        """Select an advertised TV channel."""
        ...

    async def set_sound_output(self, output: SoundOutput) -> None:
        """Select a bounded sound output."""
        ...

    async def close_app(self, app_id: str) -> None:
        """Close an advertised TV application."""
        ...

    async def insert_text(self, text: str, *, replace: bool) -> None:
        """Insert text into the focused TV field."""
        ...

    async def delete_text(self, count: int) -> None:
        """Delete text from the focused TV field."""
        ...

    async def send_text_enter(self) -> None:
        """Send enter to the focused TV field."""
        ...

    async def create_alert(self, message: str, button_label: str) -> None:
        """Display a bounded webOS alert."""
        ...

    async def close_alert(self) -> None:
        """Close the last alert created by this controller."""
        ...

    async def set_3d(self, *, enabled: bool) -> None:
        """Set 3D mode when the TV advertises support."""
        ...

    async def show_toast(self, message: str) -> None:
        """Display a bounded TV notification."""
        ...

    async def status(self) -> StatusView:
        """Return the current bounded TV status."""
        ...


class _Client(Protocol):
    client_key: str | None
    tv_info: WebOsTvInfo
    tv_state: WebOsTvState

    async def connect(self) -> bool: ...

    async def disconnect(self) -> None: ...

    def is_connected(self) -> bool: ...

    async def request(self, uri: str, payload: dict[str, Any] | None = None) -> dict[str, Any]: ...

    async def button(self, name: str) -> None: ...


type ClientFactory = Callable[[str, str | None, bytes], _Client]
type AsyncOperation = Callable[[_Client], Coroutine[Any, Any, None]]


class SecureWebOsClient(WebOsClient):
    """Use only certificate-pinned WSS connections to one configured TV."""

    def __init__(self, host: str, client_key: str | None, certificate_digest: bytes) -> None:
        """Configure one pinned webOS client."""
        self._certificate_digest = certificate_digest
        super().__init__(host, client_key)

    def registration_msg(self) -> dict[str, Any]:
        """Request only the permissions needed by the local control surface."""
        return {
            "id": "register_0",
            "type": "register",
            "payload": {
                "client-key": self.client_key,
                "forcePairing": False,
                "pairingType": "PROMPT",
                "manifest": {
                    "appVersion": "1.0",
                    "manifestVersion": 1,
                    "permissions": list(_PAIRING_PERMISSIONS),
                },
            },
        }

    async def _ws_connect(self, uri: str, max_msg_size: int) -> aiohttp.ClientWebSocketResponse:
        """Rewrite the TV's WebSocket URLs to its pinned TLS endpoint."""
        parsed = urlsplit(uri)
        if parsed.hostname != self.host:
            msg = "TV supplied a pointer socket for an unexpected host."
            raise CertificateVerificationError(msg)
        if self.client_session is None:
            msg = "TV client session was not initialized."
            raise ControllerError(msg)

        secure_uri = urlunsplit(
            (
                "wss",
                f"{self.host}:{_MAIN_WEBSOCKET_PORT}",
                parsed.path or "/",
                parsed.query,
                "",
            )
        )
        async with asyncio.timeout(self.timeout_connect):
            return await self.client_session.ws_connect(
                secure_uri,
                heartbeat=self.heartbeat,
                ssl=aiohttp.Fingerprint(self._certificate_digest),
                max_msg_size=max_msg_size,
            )


class TVController:
    """Serialize TV access and expose a small, validated command surface."""

    def __init__(
        self,
        config: AppConfig,
        store: StateStore,
        *,
        client_factory: ClientFactory = SecureWebOsClient,
    ) -> None:
        """Configure serialized access to one TV."""
        self.config = config
        self.store = store
        self._client_factory = client_factory
        self._client: _Client | None = None
        self._client_key = store.load_client_key()
        self._lock = asyncio.Lock()
        self._pairing = False
        self._last_error: str | None = None
        self._services: list[str] = []
        self._supports_3d = False
        self._active_alert_id: str | None = None

    async def pair(self) -> None:
        """Start TV-prompt pairing and persist the approved client key."""
        if self._pairing:
            msg = "Pairing is already in progress."
            raise PairingRequiredError(msg)
        self._pairing = True
        try:
            async with self._lock:
                await self._disconnect_locked()
                await self._connect_locked(None, save_new_key=True)
        finally:
            self._pairing = False

    async def connect(self) -> None:
        """Connect with the previously approved client key."""
        async with self._lock:
            if self._client is not None and self._client.is_connected():
                return
            if self._client_key is None:
                msg = "Pair this controller with the TV first."
                raise PairingRequiredError(msg)
            await self._connect_locked(self._client_key, save_new_key=False)

    async def disconnect(self) -> None:
        """Close active TV connections without forgetting pairing."""
        async with self._lock:
            await self._disconnect_locked()

    async def forget_pairing(self) -> None:
        """Disconnect and remove the locally stored TV client key."""
        async with self._lock:
            await self._disconnect_locked()
            self.store.forget_client_key()
            self._client_key = None
            self._last_error = None
            self._services = []
            self._supports_3d = False
            self._active_alert_id = None

    async def wake(self) -> None:
        """Send a Wake-on-LAN magic packet for the configured TV MAC."""
        try:
            await asyncio.to_thread(
                _send_magic_packet,
                self.config.tv_mac,
                self.config.broadcast_address,
            )
        except OSError as error:
            self._last_error = "Unable to send the Wake-on-LAN packet."
            raise ControllerError(self._last_error) from error
        self._last_error = None

    async def send_command(self, command: RemoteCommand) -> None:
        """Execute one command from the fixed remote-control allowlist."""
        if endpoint := _SSAP_COMMANDS.get(command):
            await self._run(lambda client: _request_without_result(client, endpoint))
            return
        if button := _POINTER_COMMANDS.get(command):
            await self._run(lambda client: client.button(button))
            return
        msg = "Unsupported remote-control command."
        raise InvalidControlError(msg)

    async def set_volume(self, level: int) -> None:
        """Set an absolute volume in the TV's documented range."""
        if not 0 <= level <= _MAX_VOLUME:
            msg = "Volume must be between 0 and 100."
            raise InvalidControlError(msg)
        await self._run(
            lambda client: _request_without_result(
                client,
                webos_endpoints.SET_VOLUME,
                {"volume": level},
            )
        )

    async def set_muted(self, *, muted: bool) -> None:
        """Set the TV mute state explicitly."""
        await self._run(
            lambda client: _request_without_result(
                client,
                webos_endpoints.SET_MUTE,
                {"mute": muted},
            )
        )

    async def launch_app(self, app_id: str) -> None:
        """Launch an application currently advertised by the TV."""
        normalized = _bounded_identifier(app_id, "Application identifier")

        async def operation(client: _Client) -> None:
            allowed = {item.app_id for item in _app_views(client.tv_state.apps)}
            if normalized not in allowed:
                msg = "The TV did not advertise that application."
                raise InvalidControlError(msg)
            await client.request(webos_endpoints.LAUNCH_APP, {"id": normalized})

        await self._run(operation)

    async def select_input(self, input_id: str) -> None:
        """Switch to an input currently advertised by the TV."""
        normalized = _bounded_identifier(input_id, "Input identifier")

        async def operation(client: _Client) -> None:
            allowed = {item.input_id for item in _input_views(client.tv_state.inputs)}
            if normalized not in allowed:
                msg = "The TV did not advertise that input."
                raise InvalidControlError(msg)
            await client.request(webos_endpoints.SET_INPUT, {"inputId": normalized})

        await self._run(operation)

    async def set_channel(self, channel_id: str) -> None:
        """Switch to a channel currently advertised by the TV."""
        normalized = _bounded_identifier(channel_id, "Channel identifier")

        async def operation(client: _Client) -> None:
            allowed = {item.channel_id for item in _channel_views(client.tv_state.channels or [])}
            if normalized not in allowed:
                msg = "The TV did not advertise that channel."
                raise InvalidControlError(msg)
            await client.request(webos_endpoints.SET_CHANNEL, {"channelId": normalized})

        await self._run(operation)

    async def set_sound_output(self, output: SoundOutput) -> None:
        """Select one known webOS sound-output mode."""
        if output not in _SOUND_OUTPUTS:
            msg = "Sound output is invalid."
            raise InvalidControlError(msg)
        await self._run(
            lambda client: _request_without_result(
                client,
                webos_endpoints.CHANGE_SOUND_OUTPUT,
                {"output": output},
            )
        )

    async def close_app(self, app_id: str) -> None:
        """Close an application currently advertised by the TV."""
        normalized = _bounded_identifier(app_id, "Application identifier")

        async def operation(client: _Client) -> None:
            allowed = {item.app_id for item in _app_views(client.tv_state.apps)}
            if normalized not in allowed:
                msg = "The TV did not advertise that application."
                raise InvalidControlError(msg)
            await client.request(webos_endpoints.LAUNCHER_CLOSE, {"id": normalized})

        await self._run(operation)

    async def insert_text(self, text: str, *, replace: bool) -> None:
        """Insert bounded printable text into the TV's focused field."""
        normalized = _bounded_text(text, maximum=_MAX_TEXT_LENGTH, label="Input text")
        await self._run(
            lambda client: _request_without_result(
                client,
                webos_endpoints.INSERT_TEXT,
                {"text": normalized, "replace": replace},
            )
        )

    async def delete_text(self, count: int) -> None:
        """Delete a bounded number of characters from the focused field."""
        if not 1 <= count <= _MAX_DELETE_COUNT:
            msg = "Delete count must be between 1 and 100."
            raise InvalidControlError(msg)
        await self._run(
            lambda client: _request_without_result(
                client,
                webos_endpoints.SEND_DELETE,
                {"count": count},
            )
        )

    async def send_text_enter(self) -> None:
        """Send the IME enter action to the TV's focused field."""
        await self._run(lambda client: _request_without_result(client, webos_endpoints.SEND_ENTER))

    async def create_alert(self, message: str, button_label: str) -> None:
        """Create a bounded alert and retain only its opaque identifier."""
        alert_message = _bounded_text(message, maximum=_MAX_ALERT_LENGTH, label="Alert message")
        alert_button = _bounded_text(button_label, maximum=_MAX_ALERT_BUTTON_LENGTH, label="Alert button label")

        async def operation(client: _Client) -> None:
            response = await client.request(
                webos_endpoints.CREATE_ALERT,
                {"message": alert_message, "buttons": [{"label": alert_button}]},
            )
            alert_id = response.get("alertId")
            self._active_alert_id = alert_id[:256] if isinstance(alert_id, str) and alert_id else None

        await self._run(operation)

    async def close_alert(self) -> None:
        """Close the last alert created during this controller process."""
        alert_id = self._active_alert_id
        if alert_id is None:
            msg = "This controller has no active alert to close."
            raise InvalidControlError(msg)
        await self._run(
            lambda client: _request_without_result(
                client,
                webos_endpoints.CLOSE_ALERT,
                {"alertId": alert_id},
            )
        )
        self._active_alert_id = None

    async def set_3d(self, *, enabled: bool) -> None:
        """Set 3D mode when the connected model advertises that feature."""
        if not self._supports_3d:
            msg = "This TV does not advertise 3D support."
            raise InvalidControlError(msg)
        endpoint = webos_endpoints.SET_3D_ON if enabled else webos_endpoints.SET_3D_OFF
        await self._run(lambda client: _request_without_result(client, endpoint))

    async def show_toast(self, message: str) -> None:
        """Display a short, text-only TV notification."""
        normalized = message.strip()
        if (
            not normalized
            or len(normalized) > _MAX_TOAST_LENGTH
            or any(ord(character) < _FIRST_PRINTABLE_ASCII for character in normalized)
        ):
            msg = "Notification text must contain 1 to 120 printable characters."
            raise InvalidControlError(msg)
        await self._run(
            lambda client: _request_without_result(
                client,
                webos_endpoints.SHOW_MESSAGE,
                {"message": normalized},
            )
        )

    async def status(self) -> StatusView:
        """Return a bounded snapshot without opening a new TV connection."""
        async with self._lock:
            client = self._client
            connected = client is not None and client.is_connected()
            if not connected or client is None:
                return StatusView(
                    host=self.config.tv_host,
                    paired=self._client_key is not None,
                    connected=False,
                    encrypted=True,
                    pairing=self._pairing,
                    is_on=False,
                    is_screen_on=False,
                    power_state=None,
                    volume=None,
                    muted=None,
                    current_app_id=None,
                    current_app_title=None,
                    sound_output=None,
                    software_version=None,
                    last_error=self._last_error,
                    services=list(self._services),
                    supports_3d=self._supports_3d,
                    alert_active=self._active_alert_id is not None,
                )

            state = client.tv_state
            apps = _app_views(state.apps)
            channels = _channel_views(state.channels or [])
            current_channel_id, current_channel_name, current_channel_number = _channel_fields(state.current_channel)
            current_title = next(
                (item.title for item in apps if item.app_id == state.current_app_id),
                None,
            )
            return StatusView(
                host=self.config.tv_host,
                paired=self._client_key is not None,
                connected=True,
                encrypted=True,
                pairing=self._pairing,
                is_on=state.is_on,
                is_screen_on=state.is_screen_on,
                power_state=_power_state(state.power_state),
                volume=state.volume,
                muted=state.muted,
                current_app_id=state.current_app_id,
                current_app_title=current_title,
                sound_output=state.sound_output,
                software_version=_software_version(client.tv_info.software, client.tv_info.hello),
                last_error=self._last_error,
                apps=apps,
                inputs=_input_views(state.inputs),
                channels=channels,
                current_channel_id=current_channel_id,
                current_channel_name=current_channel_name,
                current_channel_number=current_channel_number,
                services=list(self._services),
                supports_3d=self._supports_3d,
                alert_active=self._active_alert_id is not None,
            )

    async def _run(self, operation: AsyncOperation) -> None:
        async with self._lock:
            if self._client is None or not self._client.is_connected():
                if self._client_key is None:
                    msg = "Pair this controller with the TV first."
                    raise PairingRequiredError(msg)
                await self._connect_locked(self._client_key, save_new_key=False)
            client = cast("_Client", self._client)
            try:
                await operation(client)
            except InvalidControlError:
                raise
            except (TimeoutError, OSError, aiohttp.ClientError, WebOsTvError) as error:
                self._last_error = "The TV did not accept the command."
                LOGGER.warning("LG TV command failed", exc_info=error)
                raise ControllerError(self._last_error) from error
            self._last_error = None

    async def _connect_locked(self, client_key: str | None, *, save_new_key: bool) -> None:
        client = self._client_factory(
            self.config.tv_host,
            client_key,
            self.config.certificate_digest,
        )
        self._client = client
        try:
            connected = await client.connect()
            approved_key = _ensure_approved_connection(connected=connected, client_key=client.client_key)
            await self._load_capabilities(client)
            if save_new_key:
                self.store.save_client_key(approved_key)
                self._client_key = approved_key
        except aiohttp.ServerFingerprintMismatch as error:
            self._last_error = "The TV certificate does not match the configured fingerprint."
            await self._disconnect_locked()
            raise CertificateVerificationError(self._last_error) from error
        except PairingRequiredError:
            await self._disconnect_locked()
            raise
        except StateFileError as error:
            self._last_error = "Pairing succeeded, but the client key could not be stored safely."
            await self._disconnect_locked()
            raise ControllerError(self._last_error) from error
        except (TimeoutError, OSError, aiohttp.ClientError, WebOsTvError) as error:
            self._last_error = "Unable to connect. Keep the TV awake and approve its pairing prompt."
            LOGGER.warning("LG TV connection failed", exc_info=error)
            await self._disconnect_locked()
            raise ControllerError(self._last_error) from error
        self._last_error = None

    async def _load_capabilities(self, client: _Client) -> None:
        """Load read-only model capabilities without making connection success depend on them."""
        self._supports_3d = _supports_3d(client.tv_info.system)
        try:
            response = await client.request(webos_endpoints.GET_SERVICES)
            self._services = _service_names(response.get("services"))
        except TimeoutError, OSError, aiohttp.ClientError, WebOsTvError:
            LOGGER.info("LG TV service catalog unavailable", exc_info=True)
            self._services = []

        if client.tv_state.channels is not None:
            return
        try:
            response = await client.request(webos_endpoints.GET_TV_CHANNELS)
            raw_channels = response.get("channelList")
            if isinstance(raw_channels, list):
                client.tv_state.channels = [item for item in raw_channels if isinstance(item, dict)]
        except TimeoutError, OSError, aiohttp.ClientError, WebOsTvError:
            LOGGER.info("LG TV channel catalog unavailable", exc_info=True)

    async def _disconnect_locked(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            await client.disconnect()
        except TimeoutError, OSError, aiohttp.ClientError, WebOsTvError:
            LOGGER.warning("LG TV disconnect failed", exc_info=True)


async def _request_without_result(
    client: _Client,
    endpoint: str,
    payload: dict[str, Any] | None = None,
) -> None:
    await client.request(endpoint, payload)


def _app_views(raw_apps: dict[str, Any]) -> list[AppView]:
    apps: list[AppView] = []
    for key, raw in raw_apps.items():
        record = raw if isinstance(raw, dict) else {}
        app_id = record.get("id", key)
        title = record.get("title", app_id)
        if isinstance(app_id, str) and isinstance(title, str):
            apps.append(AppView(app_id=app_id[:128], title=title[:128]))
    return sorted(apps, key=lambda item: (item.title.casefold(), item.app_id))


def _input_views(raw_inputs: dict[str, Any]) -> list[InputView]:
    inputs: list[InputView] = []
    for key, raw in raw_inputs.items():
        record = raw if isinstance(raw, dict) else {}
        input_id = record.get("id", key)
        label = record.get("label", input_id)
        connected = record.get("connected", False)
        if isinstance(input_id, str) and isinstance(label, str):
            inputs.append(
                InputView(
                    input_id=input_id[:128],
                    label=label[:128],
                    connected=connected is True,
                )
            )
    return sorted(inputs, key=lambda item: (not item.connected, item.label.casefold(), item.input_id))


def _channel_views(raw_channels: list[dict[str, Any]]) -> list[ChannelView]:
    channels: list[ChannelView] = []
    seen: set[str] = set()
    for raw in raw_channels:
        channel_id = raw.get("channelId", raw.get("id"))
        name = raw.get("channelName", raw.get("name", ""))
        number = raw.get("channelNumber", raw.get("number", ""))
        if not isinstance(channel_id, str) or not channel_id or channel_id in seen:
            continue
        safe_name = name if isinstance(name, str) else ""
        safe_number = number if isinstance(number, str) else str(number) if isinstance(number, int) else ""
        channels.append(
            ChannelView(
                channel_id=channel_id[:128],
                name=(safe_name or safe_number or channel_id)[:128],
                number=safe_number[:32],
            )
        )
        seen.add(channel_id)
    return sorted(channels, key=lambda item: (_channel_sort_key(item.number), item.name.casefold(), item.channel_id))


def _channel_sort_key(number: str) -> tuple[int, ...]:
    parts = number.replace("-", ".").split(".")
    if parts and all(part.isdigit() for part in parts):
        return tuple(int(part) for part in parts)
    return (_MAX_IDENTIFIER_LENGTH + 1,)


def _channel_fields(raw: dict[str, Any] | None) -> tuple[str | None, str | None, str | None]:
    if not isinstance(raw, dict):
        return None, None, None
    views = _channel_views([raw])
    if not views:
        return None, None, None
    channel = views[0]
    return channel.channel_id, channel.name, channel.number or None


def _service_names(raw_services: object) -> list[str]:
    if not isinstance(raw_services, list):
        return []
    names = {
        name[:128] for item in raw_services if isinstance(item, dict) and isinstance((name := item.get("name")), str) and name
    }
    return sorted(names, key=str.casefold)


def _supports_3d(system_info: dict[str, Any]) -> bool:
    features = system_info.get("features")
    return isinstance(features, dict) and features.get("3d") is True


def _power_state(raw: dict[str, Any]) -> str | None:
    for key in ("state", "powerState", "processing"):
        value = raw.get(key)
        if isinstance(value, str):
            return value[:64]
    return None


def _software_version(software: dict[str, Any], hello: dict[str, Any]) -> str | None:
    for key in ("sw_version", "version"):
        value = software.get(key)
        if isinstance(value, str) and value:
            return value[:64]
    major = software.get("major_ver")
    minor = software.get("minor_ver")
    if isinstance(major, str) and isinstance(minor, str):
        return f"{major}.{minor}"[:64]

    release = hello.get("deviceOSReleaseVersion", hello.get("deviceOSVersion"))
    if isinstance(release, str) and release:
        product = hello.get("deviceOS")
        name = product if isinstance(product, str) and product else "webOS"
        return f"{name} {release}"[:64]
    return None


def _bounded_identifier(value: str, label: str) -> str:
    if (
        not value
        or len(value) > _MAX_IDENTIFIER_LENGTH
        or not value.isascii()
        or any(ord(character) < _FIRST_NON_SPACE_ASCII for character in value)
    ):
        msg = f"{label} is invalid."
        raise InvalidControlError(msg)
    return value


def _bounded_text(value: str, *, maximum: int, label: str) -> str:
    if not value.strip() or len(value) > maximum or not value.isprintable():
        msg = f"{label} must contain 1 to {maximum} printable characters."
        raise InvalidControlError(msg)
    return value


def _ensure_approved_connection(*, connected: bool, client_key: str | None) -> str:
    if not connected or client_key is None:
        msg = "The TV did not approve pairing."
        raise PairingRequiredError(msg)
    return client_key


def _send_magic_packet(mac_address: str, broadcast_address: str) -> None:
    hardware_address = bytes.fromhex(mac_address.replace(":", ""))
    packet = b"\xff" * 6 + hardware_address * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as wake_socket:
        wake_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        wake_socket.settimeout(2)
        wake_socket.sendto(packet, (broadcast_address, 9))
