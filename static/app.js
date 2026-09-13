"use strict";

const elements = {
    appSelect: document.querySelector("#app-select"),
    appValue: document.querySelector("#app-value"),
    channelSelect: document.querySelector("#channel-select"),
    channelValue: document.querySelector("#channel-value"),
    closeAlertButton: document.querySelector("#close-alert-button"),
    connectButton: document.querySelector("#connect-button"),
    connectionDetail: document.querySelector("#connection-detail"),
    connectionLabel: document.querySelector("#connection-label"),
    disconnectButton: document.querySelector("#disconnect-button"),
    error: document.querySelector("#error"),
    inputSelect: document.querySelector("#input-select"),
    muteButton: document.querySelector("#mute-button"),
    notice: document.querySelector("#notice"),
    pairButton: document.querySelector("#pair-button"),
    powerValue: document.querySelector("#power-value"),
    softwareValue: document.querySelector("#software-value"),
    soundOutputSelect: document.querySelector("#sound-output-select"),
    soundOutputValue: document.querySelector("#sound-output-value"),
    statusDot: document.querySelector("#status-dot"),
    servicesList: document.querySelector("#services-list"),
    servicesSummary: document.querySelector("#services-summary"),
    threeDControls: document.querySelector("#three-d-controls"),
    unpairButton: document.querySelector("#unpair-button"),
    volumeOutput: document.querySelector("#volume-output"),
    volumeSlider: document.querySelector("#volume-slider"),
    volumeValue: document.querySelector("#volume-value"),
};

let currentStatus = null;
let statusTimer = null;

function csrfToken() {
    const prefix = "flasgo-csrf=";
    const token = document.cookie.split("; ").find((cookie) => cookie.startsWith(prefix));
    return token ? decodeURIComponent(token.slice(prefix.length)) : null;
}

async function api(path, {method = "GET", body = null} = {}) {
    const headers = {"accept": "application/json"};
    if (body !== null) {
        headers["content-type"] = "application/json";
    }
    if (method !== "GET" && method !== "HEAD") {
        const token = csrfToken();
        if (!token) {
            throw new Error("The CSRF token is unavailable. Reload the page.");
        }
        headers["x-csrf-token"] = token;
    }

    const response = await fetch(path, {
        method,
        headers,
        body: body === null ? null : JSON.stringify(body),
        credentials: "same-origin",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(payload.error || `Request failed with status ${response.status}.`);
    }
    return payload;
}

function showNotice(message) {
    elements.error.hidden = true;
    elements.notice.textContent = message;
    elements.notice.hidden = false;
}

function showError(error) {
    elements.notice.hidden = true;
    elements.error.textContent = error instanceof Error ? error.message : "Unexpected controller error.";
    elements.error.hidden = false;
}

function clearMessages() {
    elements.notice.hidden = true;
    elements.error.hidden = true;
}

function setOptions(select, items, valueKey, labelValue, emptyLabel) {
    const previous = select.value;
    select.replaceChildren();
    if (items.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = emptyLabel;
        select.append(option);
        return;
    }
    for (const item of items) {
        const option = document.createElement("option");
        option.value = item[valueKey];
        option.textContent = typeof labelValue === "function" ? labelValue(item) : item[labelValue];
        select.append(option);
    }
    if (items.some((item) => item[valueKey] === previous)) {
        select.value = previous;
    }
}

function renderServices(services) {
    elements.servicesList.replaceChildren();
    elements.servicesSummary.textContent = services.length === 0
        ? "The TV did not return a service catalog."
        : `${services.length} public service families advertised by this TV.`;
    for (const service of services) {
        const item = document.createElement("li");
        item.textContent = service;
        elements.servicesList.append(item);
    }
}

function renderStatus(status) {
    currentStatus = status;
    const connected = status.connected === true;
    const paired = status.paired === true;

    elements.statusDot.classList.toggle("connected", connected);
    elements.statusDot.classList.toggle("error", Boolean(status.last_error));
    elements.connectionLabel.textContent = connected ? "Connected securely" : paired ? "Paired, disconnected" : "Not paired";
    elements.connectionDetail.textContent = connected
        ? `WSS to ${status.host}`
        : status.pairing
            ? "Approve the prompt on the TV"
            : status.last_error || `TV at ${status.host}`;

    elements.pairButton.hidden = paired;
    elements.connectButton.hidden = !paired || connected;
    elements.disconnectButton.hidden = !connected;
    elements.unpairButton.hidden = !paired;

    document.querySelectorAll("[data-requires-connection]").forEach((control) => {
        control.disabled = !connected;
    });
    document.querySelectorAll("[data-requires-3d]").forEach((control) => {
        control.hidden = status.supports_3d !== true;
    });
    elements.threeDControls.hidden = status.supports_3d !== true;
    elements.closeAlertButton.disabled = !connected || status.alert_active !== true;

    elements.powerValue.textContent = status.power_state || (status.is_on ? "On" : connected ? "Standby" : "Unknown");
    elements.appValue.textContent = status.current_app_title || status.current_app_id || "Unknown";
    elements.softwareValue.textContent = status.software_version || "Unknown";
    elements.channelValue.textContent = status.current_channel_name
        ? `${status.current_channel_number ? `${status.current_channel_number} · ` : ""}${status.current_channel_name}`
        : "Unknown";
    elements.soundOutputValue.textContent = status.sound_output || "Unknown";

    const volume = Number.isInteger(status.volume) ? status.volume : 0;
    elements.volumeSlider.value = String(volume);
    elements.volumeOutput.value = String(volume);
    elements.volumeValue.textContent = Number.isInteger(status.volume)
        ? `${status.muted ? "Muted · " : ""}${status.volume}%`
        : "Unknown";
    elements.muteButton.textContent = status.muted ? "Unmute" : "Mute";

    setOptions(elements.appSelect, status.apps || [], "app_id", "title", "No applications loaded");
    setOptions(elements.inputSelect, status.inputs || [], "input_id", "label", "No inputs loaded");
    setOptions(
        elements.channelSelect,
        status.channels || [],
        "channel_id",
        (channel) => `${channel.number ? `${channel.number} · ` : ""}${channel.name}`,
        "No channels loaded",
    );
    if (status.current_channel_id && [...elements.channelSelect.options].some((option) => option.value === status.current_channel_id)) {
        elements.channelSelect.value = status.current_channel_id;
    }
    if (status.sound_output && [...elements.soundOutputSelect.options].some((option) => option.value === status.sound_output)) {
        elements.soundOutputSelect.value = status.sound_output;
    }
    renderServices(status.services || []);
}

async function refreshStatus() {
    try {
        renderStatus(await api("/api/status"));
    } catch (error) {
        showError(error);
    }
}

async function mutation(path, body, progressMessage) {
    clearMessages();
    if (progressMessage) {
        showNotice(progressMessage);
    }
    try {
        const result = await api(path, {method: "POST", body});
        showNotice(result.message);
        await refreshStatus();
        return true;
    } catch (error) {
        showError(error);
        await refreshStatus();
        return false;
    }
}

elements.pairButton.addEventListener("click", () => {
    mutation("/api/pair", null, "Approve the connection prompt on the TV now.");
});

elements.connectButton.addEventListener("click", () => {
    mutation("/api/connect", null, "Connecting to the TV…");
});

elements.disconnectButton.addEventListener("click", () => {
    mutation("/api/disconnect", null);
});

document.querySelector("#wake-button").addEventListener("click", () => {
    mutation("/api/wake", null, "Sending a Wake-on-LAN packet…");
});

elements.unpairButton.addEventListener("click", () => {
    if (window.confirm("Remove this controller's locally stored TV pairing key?")) {
        mutation("/api/unpair", null);
    }
});

document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => {
        const command = button.dataset.command;
        if (["power_off", "power_toggle"].includes(command) && !window.confirm("Send this power command to the TV?")) {
            return;
        }
        mutation("/api/command", {command});
    });
});

elements.muteButton.addEventListener("click", () => {
    mutation("/api/mute", {muted: currentStatus?.muted !== true});
});

elements.volumeSlider.addEventListener("input", () => {
    elements.volumeOutput.value = elements.volumeSlider.value;
});

elements.volumeSlider.addEventListener("change", () => {
    mutation("/api/volume", {level: Number(elements.volumeSlider.value)});
});

document.querySelector("#launch-button").addEventListener("click", () => {
    if (elements.appSelect.value) {
        mutation("/api/apps/launch", {app_id: elements.appSelect.value});
    }
});

document.querySelector("#close-app-button").addEventListener("click", () => {
    if (elements.appSelect.value && window.confirm("Close the selected TV application?")) {
        mutation("/api/apps/close", {app_id: elements.appSelect.value});
    }
});

document.querySelector("#input-button").addEventListener("click", () => {
    if (elements.inputSelect.value) {
        mutation("/api/inputs/select", {input_id: elements.inputSelect.value});
    }
});

document.querySelector("#channel-button").addEventListener("click", () => {
    if (elements.channelSelect.value) {
        mutation("/api/channels/select", {channel_id: elements.channelSelect.value});
    }
});

document.querySelector("#sound-output-button").addEventListener("click", () => {
    mutation("/api/sound-output", {output: elements.soundOutputSelect.value});
});

document.querySelectorAll("[data-three-d]").forEach((button) => {
    button.addEventListener("click", () => {
        mutation("/api/3d", {enabled: button.dataset.threeD === "true"});
    });
});

document.querySelector("#toast-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.querySelector("#toast-message");
    if (input.reportValidity()) {
        if (await mutation("/api/toast", {message: input.value})) {
            input.value = "";
        }
    }
});

document.querySelector("#text-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.querySelector("#text-value");
    if (input.reportValidity() && await mutation("/api/text", {
        text: input.value,
        replace: document.querySelector("#text-replace").checked,
    })) {
        input.value = "";
    }
});

document.querySelector("#text-delete-button").addEventListener("click", () => {
    mutation("/api/text/delete", {count: 1});
});

document.querySelector("#text-enter-button").addEventListener("click", () => {
    mutation("/api/text/enter", null);
});

document.querySelector("#alert-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.querySelector("#alert-message");
    const buttonLabel = document.querySelector("#alert-button-label");
    if (message.reportValidity() && buttonLabel.reportValidity() && await mutation("/api/alerts", {
        message: message.value,
        button_label: buttonLabel.value,
    })) {
        message.value = "";
    }
});

elements.closeAlertButton.addEventListener("click", () => {
    mutation("/api/alerts/close", null);
});

async function start() {
    await refreshStatus();
    if (currentStatus?.paired && !currentStatus.connected) {
        await mutation("/api/connect", null, "Connecting with the stored pairing key…");
    }
    statusTimer = window.setInterval(refreshStatus, 3_000);
}

window.addEventListener("pagehide", () => {
    if (statusTimer !== null) {
        window.clearInterval(statusTimer);
    }
});

start();
