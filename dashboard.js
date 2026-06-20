// dashboard.js
// Handles REST API polling, Leaflet map renders, heatmap overlays, and real-time
// event timeline via WebSocket /ws/events. All numbers from SQL endpoints.

const API_BASE = `${window.location.protocol}//${window.location.host}`;
const WS_BASE  = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;

const CAM_MAP = {
    "silk_board_junction": { cam: "Traffic Camera 12", location: "Outer Ring Rd, Bangalore" },
    "koramangala_3rd_block": { cam: "Traffic Camera 13", location: "Koramangala 80ft Rd, Bangalore" },
    "indiranagar_100ft_road": { cam: "Traffic Camera 14", location: "Indiranagar 100ft Rd, Bangalore" }
};

let map;
let markers = {};
let junctionCircles = {};
let activeHeatmapType = "density";
let activeJunctionId = "";
let heatLayer = null;
let camerasData = [];

// Pulse violating circles
let pulseState = 0;
setInterval(() => {
    pulseState = (pulseState + 1) % 2;
    for (let jId in junctionCircles) {
        const circle = junctionCircles[jId];
        if (circle && circle._isViolating) {
            circle.setStyle({
                fillOpacity: pulseState === 0 ? 0.9 : 0.4,
                radius: pulseState === 0 ? 15 : 10
            });
        } else if (circle) {
            circle.setStyle({
                radius: 10,
                fillOpacity: 0.9
            });
        }
    }
}, 500);

// Initialize Dashboard 1
document.addEventListener("DOMContentLoaded", () => {
    startClock();
    initMap();
    fetchJunctions();

    // Connect WebSocket for live statistics
    connectStatsWS();

    // Connect WebSocket for real-time event timeline
    connectEventsWS();
});

// HUD Clock Timer
function startClock() {
    const clockEl = document.getElementById("clock-display");
    const tick = () => { if (clockEl) clockEl.innerText = new Date().toTimeString().split(" ")[0]; };
    tick();
    setInterval(tick, 1000);
}

// ─── Stats Summary (header KPIs from SQL via WebSocket) ──────────────────────
let statsWS = null;
function connectStatsWS() {
    if (statsWS) statsWS.close();
    statsWS = new WebSocket(`${WS_BASE}/ws/stats`);
    statsWS.onmessage = (msg) => {
        try {
            const data = JSON.parse(msg.data);
            const updateVal = (id, newVal) => {
                const el = document.getElementById(id);
                if (el) {
                    const currentVal = el.innerText;
                    if (currentVal !== String(newVal)) {
                        el.innerText = newVal ?? "-";
                        el.classList.remove("pulse-glow");
                        void el.offsetWidth; // Trigger reflow
                        el.classList.add("pulse-glow");
                    }
                }
            };
            updateVal("stat-vehicles-today", data.vehicles_today);
            updateVal("stat-violations-today", data.violations_today);
            updateVal("active-cams", `${data.active_cameras} / 3`);
        } catch (e) { /* ignore */ }
    };
    statsWS.onclose = () => {
        setTimeout(connectStatsWS, 3000);
    };
}

// Map Initialization
function initMap() {
    map = L.map('map-container').setView([12.9343, 77.6244], 14);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);
}

function fetchJunctions() {
    updateMapData().then(() => {
        fetch(`${API_BASE}/api/junctions`)
            .then(res => res.json())
            .then(data => {
                activeJunctionId = data.active_junction_id;
                pollJunctionCongestion(data.junctions);
                setInterval(() => pollJunctionCongestion(data.junctions), 5000);
            })
            .catch(err => console.error("Error fetching junctions:", err));
    });
    setInterval(updateMapData, 10000);
}

function updateMapData() {
    return fetch(`${API_BASE}/api/stats/cameras`)
        .then(res => res.json())
        .then(data => {
            camerasData = data;
            renderMap();
        })
        .catch(err => console.error("Error fetching camera stats:", err));
}

function renderMap() {
    for (let id in markers) {
        if (markers[id]) map.removeLayer(markers[id]);
    }
    markers = {};
    junctionCircles = {};

    if (heatLayer) {
        map.removeLayer(heatLayer);
        heatLayer = null;
    }

    if (!camerasData || !camerasData.length) return;

    camerasData.forEach(cam => {
        let fillColor = '#00cc66';
        if (activeHeatmapType === 'density') {
            fillColor = cam.congestion_pct > 70 ? '#ff4444' : cam.congestion_pct > 40 ? '#ffaa00' : '#00cc66';
        } else if (activeHeatmapType === 'violations') {
            fillColor = cam.violations > 3 ? '#ff4444' : cam.violations > 0 ? '#ffaa00' : '#00cc66';
        } else { // risk
            fillColor = cam.risk > 70 ? '#ff4444' : cam.risk > 40 ? '#ffaa00' : '#00cc66';
        }

        const marker = L.circleMarker([cam.lat, cam.lng], {
            radius: 10,
            fillColor: fillColor,
            color: '#fff',
            weight: 2,
            fillOpacity: 0.9
        }).addTo(map);

        marker.bindPopup(`
            <div style="font-family: 'Outfit', sans-serif; min-width: 180px; color: #fff;">
                <h3 style="margin: 0 0 5px; color: #00f2fe; font-size: 14px;">${cam.name}</h3>
                <p id="popup-congestion-${cam.id}" style="margin: 2px 0; font-size: 11px;">Congestion: ${Math.round(cam.congestion_pct)}%</p>
                <p id="popup-speed-${cam.id}" style="margin: 2px 0; font-size: 11px;">Avg Speed: ${cam.avg_speed} km/h</p>
                <p id="popup-violations-${cam.id}" style="margin: 2px 0; font-size: 11px;">Active Violations: ${cam.violations}</p>
                <p style="margin: 2px 0; font-size: 11px;">Vehicles: ${cam.vehicle_count}</p>
                <p style="margin: 2px 0; font-size: 11px;">Risk Score: ${cam.risk} pts</p>
                <button onclick="location.href='/junction_monitor.html?junction_id=${cam.id}'" style="margin-top: 8px; width: 100%; padding: 5px; background: linear-gradient(135deg, #00f2fe, #4facfe); border: none; border-radius: 4px; color: #000; font-weight: bold; cursor: pointer;">MONITOR CAM</button>
            </div>
        `);

        marker._isViolating = cam.violations > 0;
        markers[cam.id] = marker;
        junctionCircles[cam.id] = marker;
    });

    let heatData = [];
    if (activeHeatmapType === 'density') {
        heatData = camerasData.map(c => [c.lat, c.lng, c.congestion_pct / 100]);
    } else if (activeHeatmapType === 'violations') {
        heatData = camerasData.map(c => [c.lat, c.lng, Math.min(1.0, c.violations / 5)]);
    } else { // risk
        heatData = camerasData.map(c => [c.lat, c.lng, c.risk / 100]);
    }

    heatLayer = L.heatLayer(heatData, { radius: 40, blur: 25, maxZoom: 17 }).addTo(map);
}

// Poll congestion for each junction from canonical DB endpoint
function pollJunctionCongestion(junctions) {
    // Map junction_id → cam_id
    const junctionToCam = {
        "silk_board_junction":    "cam_12",
        "koramangala_3rd_block":  "cam_13",
        "indiranagar_100ft_road": "cam_14",
    };

    junctions.forEach(j => {
        const camId = junctionToCam[j.id] || j.id;
        fetch(`${API_BASE}/api/congestion/${camId}?n=1`)
            .then(r => r.json())
            .then(data => {
                const pts = data.points || [];
                if (!pts.length) return;
                const latest = pts[pts.length - 1];

                const cong = latest.congestion_pct ?? latest.congestion_level ?? 0;
                const spd  = latest.avg_speed ?? latest.average_speed ?? 0;

                const popCong = document.getElementById(`popup-congestion-${j.id}`);
                const popSpd  = document.getElementById(`popup-speed-${j.id}`);
                if (popCong) popCong.innerText = `Congestion: ${Math.round(cong)}%`;
                if (popSpd)  popSpd.innerText  = `Avg Speed: ${Math.round(spd)} km/h`;
            })
            .catch(() => {});
    });

    // Also refresh junction registry cards
    pollLiveStats();
}

// Poll live-stats for junction cards (unchanged — backed by SQL)
function pollLiveStats() {
    fetch(`${API_BASE}/api/live-stats`)
        .then(res => res.json())
        .then(data => {
            if (data.junctions) {
                let listHtml = "";
                data.junctions.forEach(j => {
                    const camInfo = CAM_MAP[j.id] || { cam: "Traffic Camera", location: "Bangalore" };
                    const riskColor = j.risk_score > 70 ? "text-red" : j.risk_score > 40 ? "text-yellow" : "text-green";

                    listHtml += `
                        <div class="ticket-item-card" onclick="location.href='/junction_monitor.html?junction_id=${j.id}'">
                            <div class="title-row">
                                <span class="logo-accent" style="font-size: 13px; font-weight: 600;">${j.name}</span>
                                <span class="font-mono text-secondary" style="font-size: 10px;">${camInfo.cam}</span>
                            </div>
                            <div class="body-row" style="font-size: 11px; margin: 4px 0; color: var(--text-secondary); line-height: 1.4;">
                                Coordinates: <span class="font-mono text-primary">${j.lat.toFixed(4)}, ${j.lng.toFixed(4)}</span><br>
                                Location: <span class="text-primary">${camInfo.location}</span>
                            </div>
                            <div class="footer-row" style="margin-top: 5px; font-size: 11px;">
                                <span>Active Violations: <strong class="text-red">${j.active_violations}</strong></span>
                                <span>Risk Level: <strong class="${riskColor}">${j.risk_score}</strong></span>
                            </div>
                            <div class="footer-row" style="margin-top: 3px; font-size: 11px;">
                                <span>Vehicles Screen: <strong class="text-green">${j.vehicle_count}</strong></span>
                                <span>Avg Speed: <strong class="text-yellow">${j.average_speed} km/h</strong></span>
                            </div>
                        </div>
                    `;

                    const circle = junctionCircles[j.id];
                    if (j.active_violations > 0) {
                        if (circle) { circle._isViolating = true; circle.setStyle({ color: "#ff1744", fillColor: "#ff1744" }); }
                        if (markers[j.id]) markers[j.id].openPopup();
                    } else {
                        if (circle) { circle._isViolating = false; circle.setStyle({ color: "rgba(0,242,254,0.4)", fillColor: "rgba(0,242,254,0.15)", fillOpacity: 0.15 }); }
                    }
                });
                const regEl = document.getElementById("junction-registry-list");
                if (regEl) regEl.innerHTML = listHtml;
            }
        })
        .catch(() => {});
}

// ─── WebSocket: /ws/events — real-time violation event timeline ───────────────
let eventsWS = null;
let eventsReconnectTimer = null;
const eventTimeline = [];   // accumulate locally for display
const MAX_TIMELINE  = 50;

function connectEventsWS() {
    if (eventsWS) eventsWS.close();
    clearTimeout(eventsReconnectTimer);

    eventsWS = new WebSocket(`${WS_BASE}/ws/events`);

    eventsWS.onopen = () => console.log("[WS] /ws/events connected");

    eventsWS.onmessage = (msg) => {
        try {
            const ev = JSON.parse(msg.data);
            eventTimeline.unshift(ev);     // newest first
            if (eventTimeline.length > MAX_TIMELINE) eventTimeline.pop();
            renderEventTimeline();
        } catch (e) { /* ignore parse errors */ }
    };

    eventsWS.onclose = () => {
        eventsReconnectTimer = setTimeout(connectEventsWS, 3000);
    };

    eventsWS.onerror = () => {};
}

function renderEventTimeline() {
    const timelineEl = document.getElementById("alerts-timeline");
    const countEl    = document.getElementById("alerts-count");
    if (!timelineEl) return;

    if (countEl) countEl.innerText = `${eventTimeline.length} ACTIVE`;

    if (eventTimeline.length === 0) {
        timelineEl.innerHTML = '<div class="empty-alerts">Monitoring traffic feeds for anomalies...</div>';
        return;
    }

    let html = "";
    eventTimeline.forEach(a => {
        const clickAttr = a.violation_id
            ? `onclick="location.href='/investigation_dashboard.html?violation_id=${a.violation_id}'"` : "";
        html += `
            <div class="alert-card type-${a.type}" ${clickAttr}>
                <div class="alert-meta">
                    <span class="title">${(a.title || "Event").toUpperCase()}</span>
                    <span class="time font-mono">${a.time || ""}</span>
                </div>
                <div class="alert-desc">${a.text || ""}</div>
            </div>
        `;
    });
    timelineEl.innerHTML = html;
}

function switchHeatmap(type) {
    activeHeatmapType = type;

    document.querySelectorAll(".heatmap-controls button").forEach(btn => btn.classList.remove("active"));
    const btn = document.getElementById(`btn-${type}`);
    if (btn) btn.classList.add("active");

    renderMap();
}
