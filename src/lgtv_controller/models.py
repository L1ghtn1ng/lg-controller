"""Typed HTTP request and response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RemoteCommand = Literal[
    "amazon",
    "asterisk",
    "audio_description",
    "aspect_ratio",
    "back",
    "blue",
    "channel_down",
    "channel_up",
    "closed_captions",
    "dash",
    "digit_0",
    "digit_1",
    "digit_2",
    "digit_3",
    "digit_4",
    "digit_5",
    "digit_6",
    "digit_7",
    "digit_8",
    "digit_9",
    "down",
    "enter",
    "exit",
    "fast_forward",
    "green",
    "guide",
    "home",
    "info",
    "input_hub",
    "left",
    "list",
    "live_zoom",
    "magnifier_zoom",
    "media_close",
    "menu",
    "mute_toggle",
    "my_apps",
    "netflix",
    "pause",
    "play",
    "power_off",
    "power_toggle",
    "program",
    "quick_menu",
    "recent",
    "record",
    "red",
    "rewind",
    "right",
    "sap",
    "screen_off",
    "screen_on",
    "screen_remote",
    "stop",
    "teletext",
    "text_option",
    "three_d_mode",
    "up",
    "volume_down",
    "volume_up",
    "yellow",
]

SoundOutput = Literal[
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
]


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """A bounded command selected from the exposed remote controls."""

    command: RemoteCommand


@dataclass(frozen=True, slots=True)
class VolumeRequest:
    """An absolute TV volume request."""

    level: int


@dataclass(frozen=True, slots=True)
class MuteRequest:
    """An explicit mute state request."""

    muted: bool


@dataclass(frozen=True, slots=True)
class LaunchRequest:
    """An installed application identifier."""

    app_id: str


@dataclass(frozen=True, slots=True)
class InputRequest:
    """An advertised external-input identifier."""

    input_id: str


@dataclass(frozen=True, slots=True)
class ChannelRequest:
    """A channel identifier returned by the TV."""

    channel_id: str


@dataclass(frozen=True, slots=True)
class SoundOutputRequest:
    """A bounded webOS sound-output identifier."""

    output: SoundOutput


@dataclass(frozen=True, slots=True)
class TextRequest:
    """Text to insert into the TV's focused input field."""

    text: str
    replace: bool = False


@dataclass(frozen=True, slots=True)
class DeleteTextRequest:
    """A bounded number of focused-input characters to remove."""

    count: int = 1


@dataclass(frozen=True, slots=True)
class AlertRequest:
    """A bounded modal alert displayed by webOS."""

    message: str
    button_label: str = "OK"


@dataclass(frozen=True, slots=True)
class ThreeDRequest:
    """An explicit 3D display-mode state."""

    enabled: bool


@dataclass(frozen=True, slots=True)
class ToastRequest:
    """A short notification to display on the TV."""

    message: str


@dataclass(frozen=True, slots=True)
class AppView:
    """One launchable TV application."""

    app_id: str
    title: str


@dataclass(frozen=True, slots=True)
class InputView:
    """One TV input advertised by webOS."""

    input_id: str
    label: str
    connected: bool


@dataclass(frozen=True, slots=True)
class ChannelView:
    """One channel returned by the TV's channel catalog."""

    channel_id: str
    name: str
    number: str


@dataclass(frozen=True, slots=True)
class StatusView:
    """Safe controller and TV status returned to the browser."""

    host: str
    paired: bool
    connected: bool
    encrypted: bool
    pairing: bool
    is_on: bool
    is_screen_on: bool
    power_state: str | None
    volume: int | None
    muted: bool | None
    current_app_id: str | None
    current_app_title: str | None
    sound_output: str | None
    software_version: str | None
    last_error: str | None
    apps: list[AppView] = field(default_factory=list)
    inputs: list[InputView] = field(default_factory=list)
    channels: list[ChannelView] = field(default_factory=list)
    current_channel_id: str | None = None
    current_channel_name: str | None = None
    current_channel_number: str | None = None
    services: list[str] = field(default_factory=list)
    supports_3d: bool = False
    alert_active: bool = False


@dataclass(frozen=True, slots=True)
class ResultView:
    """A successful controller mutation result."""

    ok: bool
    message: str
