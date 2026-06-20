// junction_monitor.js
// Connects to real MJPEG stream and WebSocket telemetry from camera_stream.py.
// No fake vehicle simulation — all data comes from YOLOv8+ByteTrack inference.

const API_BASE = `${window.location.protocol}//${window.location.host}`;
const WS_BASE  = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;

// Camera metadata for UI labels and speed limits
const CAM_META = {
    "cam_12": {
        junction_id: "silk_board_junction",
        name: "Silk Board Junction",
        cam: "Traffic Camera 12",
        limit: 40,
        coords: "12.9176, 77.6241"
    },
    "cam_13": {
        junction_id: "koramangala_3rd_block",
        name: "Koramangala 3rd Block",
        cam: "Traffic Camera 13",
        limit: 50,
        coords: "12.9343, 77.6244"
    },
    "cam_14": {
        junction_id: "indiranagar_100ft_road",
        name: "Indiranagar 100ft Road",
        cam: "Traffic Camera 14",
        limit: 60,
        coords: "12.9719, 77.6412"
    }
};

let activeCamId = "cam_12";
let telemetryWS  = null;
let wsReconnectTimer = null;
let streamLoadedOnce  = false;

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    startClock();

    // Check URL params for deep-link (e.g. from City Command Center click)
    const params = new URLSearchParams(window.location.search);
    const jId = params.get("junction_id");
    const cId = params.get("cam_id");

    if (cId && CAM_META[cId]) {
        activeCamId = cId;
    } else if (jId) {
        // Find cam_id by junction_id
        for (const [id, m] of Object.entries(CAM_META)) {
            if (m.junction_id === jId) { activeCamId = id; break; }
        }
    }

    // Set dropdown to match
    const sel = document.getElementById("junction-select");
    if (sel) sel.value = activeCamId;

    loadCamera(activeCamId);
});

// ─────────────────────────────────────────────────────────────────────────────
// CLOCK
// ─────────────────────────────────────────────────────────────────────────────
function startClock() {
    const el = document.getElementById("clock-display");
    const tick = () => { if (el) el.innerText = new Date().toTimeString().split(" ")[0]; };
    tick();
    setInterval(tick, 1000);
}

// ─────────────────────────────────────────────────────────────────────────────
// CAMERA SWITCHING
// ─────────────────────────────────────────────────────────────────────────────
function changeCameraFeed() {
    const sel = document.getElementById("junction-select");
    activeCamId = sel.value;
    loadCamera(activeCamId);
}

function loadCamera(camId) {
    const meta = CAM_META[camId];
    if (!meta) return;

    streamLoadedOnce = false;
    setStreamStatus("connecting");

    // 1. Update labels
    document.getElementById("cctv-feed-label").innerText =
        `${meta.name}  —  ${meta.cam}  |  Coords: ${meta.coords}`;
    document.getElementById("telemetry-speed-limit").innerText =
        `SPEED LIMIT: ${meta.limit} km/h`;
    document.getElementById("cctv-meta").innerText =
        `CAM: ${meta.cam}  |  AI: YOLOv8n  |  TRACKER: ByteTrack  |  GPS: [${meta.coords}]`;

    // 2. Point <img> to MJPEG stream — appending timestamp busts cache
    const img = document.getElementById("cctv-mjpeg-img");
    if (img) {
        img.src = `${API_BASE}/stream/camera/${camId}?t=${Date.now()}`;
    }

    // 3. Notify backend of active junction switch
    fetch(`${API_BASE}/api/junctions/active?junction_id=${meta.junction_id}`, {
        method: "POST"
    }).catch(() => {});

    // 4. Connect WebSocket for telemetry
    connectTelemetryWS(camId);
}

// ─────────────────────────────────────────────────────────────────────────────
// MJPEG STREAM STATUS
// ─────────────────────────────────────────────────────────────────────────────
function handleStreamLoad() {
    if (!streamLoadedOnce) {
        streamLoadedOnce = true;
        setStreamStatus("live");
    }
}

function handleStreamError() {
    setStreamStatus("connecting");
    // Auto-retry after 3 s
    setTimeout(() => {
        const img = document.getElementById("cctv-mjpeg-img");
        if (img) img.src = `${API_BASE}/stream/camera/${activeCamId}?t=${Date.now()}`;
    }, 3000);
}

function setStreamStatus(state) {
    const badge   = document.getElementById("stream-badge");
    const hud     = document.getElementById("stream-status-hud");

    if (state === "live") {
        if (badge) { badge.className = "stream-status-badge live"; badge.textContent = "● LIVE"; }
        if (hud)   hud.textContent = "LIVE";
    } else {
        if (badge) { badge.className = "stream-status-badge connecting"; badge.textContent = "● CONNECTING"; }
        if (hud)   hud.textContent = "CONNECTING";
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WEBSOCKET TELEMETRY
// ─────────────────────────────────────────────────────────────────────────────
function connectTelemetryWS(camId) {
    // Close existing connection
    if (telemetryWS) {
        telemetryWS.onclose = null;  // prevent reconnect on intentional close
        telemetryWS.close();
        telemetryWS = null;
    }
    clearTimeout(wsReconnectTimer);

    const url = `${WS_BASE}/ws/camera/${camId}`;
    console.log(`[WS] Connecting: ${url}`);

    try {
        telemetryWS = new WebSocket(url);
    } catch (e) {
        console.warn("[WS] Cannot create WebSocket:", e);
        scheduleWSReconnect(camId);
        return;
    }

    telemetryWS.onopen = () => {
        console.log(`[WS] Connected: ${url}`);
        setStreamStatus("live");
    };

    telemetryWS.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.error) { console.warn("[WS]", data.error); return; }
            renderTelemetry(data);
        } catch (e) {
            console.warn("[WS] Parse error:", e);
        }
    };

    telemetryWS.onerror = (err) => {
        console.warn("[WS] Error:", err);
    };

    telemetryWS.onclose = () => {
        console.warn("[WS] Disconnected — reconnecting in 3s...");
        scheduleWSReconnect(camId);
    };
}

function scheduleWSReconnect(camId) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(() => connectTelemetryWS(camId), 3000);
}

// ─────────────────────────────────────────────────────────────────────────────
// TELEMETRY TABLE RENDERER
// ─────────────────────────────────────────────────────────────────────────────
function renderTelemetry(data) {
    const tbody = document.getElementById("telemetry-tbody");
    const countBadge = document.getElementById("telemetry-count-badge");
    const vehicleHud = document.getElementById("vehicle-count-hud");
    const meta = CAM_META[activeCamId] || {};
    const limit = meta.limit || 60;

    const vehicles = data.vehicles || [];

    // Update HUD counts
    if (countBadge) countBadge.textContent = `${vehicles.length} vehicle${vehicles.length !== 1 ? "s" : ""}`;
    if (vehicleHud) vehicleHud.textContent = vehicles.length;

    if (vehicles.length === 0) {
        if (tbody) tbody.innerHTML = `
            <tr>
                <td colspan="5" class="table-empty">No vehicles detected in current frame...</td>
            </tr>
        `;
        return;
    }

    // Sort: violators first, then by speed descending
    const sorted = [...vehicles].sort((a, b) => {
        if (a.is_violating !== b.is_violating) return a.is_violating ? -1 : 1;
        return b.speed_kmph - a.speed_kmph;
    });

    let html = "";
    for (const v of sorted) {
        const isOver = v.is_violating;
        const speedClass = isOver ? "text-red font-mono" : (v.speed_kmph > limit * 0.8 ? "text-orange font-mono" : "font-mono");
        const statusHtml = isOver
            ? `<strong class="text-red font-mono">${v.violation_text || "VIOLATION"}</strong>`
            : `<span class="text-green">TRACKING</span>`;

        const typeColour = {
            "Car": "text-cyan", "Motorcycle": "text-green",
            "Bus": "text-orange", "Truck": "text-orange"
        }[v.class_label] || "";

        html += `
            <tr class="${isOver ? "highlight-violation" : ""}">
                <td class="font-mono">#${v.track_id}</td>
                <td class="${typeColour}">${v.class_label}</td>
                <td class="${speedClass}">${v.speed_kmph} km/h</td>
                <td class="font-mono text-secondary">${v.direction}</td>
                <td>${statusHtml}</td>
            </tr>
        `;
    }

    if (tbody) tbody.innerHTML = html;
}
