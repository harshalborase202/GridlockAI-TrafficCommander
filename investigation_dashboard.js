// investigation_dashboard.js
// Handles list polling, frame-loop replay, timeline frames, and vehicle offense lookups.
// All data from SQL endpoints. No Math.random(), no hardcoded counts.

const API_BASE = `${window.location.protocol}//${window.location.host}`;
const WS_BASE  = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;

let currentTickets = [];
let activeTicketId = null;
let activeTicketData = null;

// Replay Player State
let replayIntervalId = null;
let currentFrameIdx = 0; // 0=T-2, 1=T-1, 2=T, 3=T+1, 4=T+2
let isPlaying = false;

const FRAME_LABELS = [
    "FRAME: T-2 (2.0s Before)",
    "FRAME: T-1 (1.0s Before)",
    "FRAME: T (VIOLATION DETECTED)",
    "FRAME: T+1 (1.0s After)",
    "FRAME: T+2 (2.0s After)"
];

// Initialize Dashboard 3
document.addEventListener("DOMContentLoaded", () => {
    // Start Clock HUD
    startClock();

    // Start polling tickets register (every 1.0 second)
    pollTickets();
    setInterval(pollTickets, 1000);

    // Connect WebSocket for live stats HUD
    connectStatsWS();

    // Check if violation_id was passed in URL for automatic focus on redirect
    const urlParams = new URLSearchParams(window.location.search);
    const vId = urlParams.get("violation_id");
    if (vId) {
        activeTicketId = vId;
    }
});

// HUD Clock Timer
function startClock() {
    const clockEl = document.getElementById("clock-display");
    setInterval(() => {
        const now = new Date();
        clockEl.innerText = now.toTimeString().split(' ')[0];
    }, 1000);
}

let lastTicketsHash = "";

// Poll Active Tickets from Backend
function pollTickets() {
    fetch(`${API_BASE}/api/tickets`)
        .then(res => res.json())
        .then(data => {
            // Auto-select the newest ticket on load if none selected
            if (!activeTicketId && data.length > 0) {
                activeTicketId = data[data.length - 1].violation_id;
                activeTicketData = null; // force load
            }

            // Compare data hash to avoid flickering/unnecessary DOM redraws
            const newHash = JSON.stringify([
                activeTicketId,
                data.map(t => [t.violation_id, t.status, t.plate_number])
            ]);
            if (newHash === lastTicketsHash) return;
            lastTicketsHash = newHash;

            currentTickets = data;

            const listEl = document.getElementById("tickets-list-container");
            
            if (data.length === 0) {
                listEl.innerHTML = '<div style="text-align: center; color: var(--text-secondary); margin-top: 50px;">No violation tickets logged in this session yet.</div>';
                return;
            }

            let html = "";
            // Reverse to display most recent tickets at top
            [...data].reverse().forEach(t => {
                const isActive = t.violation_id === activeTicketId ? "active-ticket" : "";
                const formattedTime = new Date(t.timestamp).toLocaleTimeString();
                
                let borderStyle = "";
                const vTypeLower = (t.violation_type || "").toLowerCase();
                if (vTypeLower.includes("red") || vTypeLower.includes("light")) {
                    borderStyle = "border-left: 3px solid var(--accent-red);";
                } else if (vTypeLower.includes("wrong")) {
                    borderStyle = "border-left: 3px solid var(--accent-amber);";
                } else if (vTypeLower.includes("speed")) {
                    borderStyle = "border-left: 3px solid #ff6b35;";
                } else if (vTypeLower.includes("park")) {
                    borderStyle = "border-left: 3px solid #9b59b6;";
                } else if (vTypeLower.includes("triple") || vTypeLower.includes("riding")) {
                    borderStyle = "border-left: 3px solid #e84393;";
                }

                html += `
                    <div class="ticket-item-card ${isActive}" style="${borderStyle}" onclick="selectTicket('${t.violation_id}')">
                        <div class="title-row">
                            <span class="logo-accent">${t.ticket_id || t.violation_id}</span>
                            <span class="font-mono text-secondary">${formattedTime}</span>
                        </div>
                        <div class="body-row">${t.violation_type}</div>
                        <div class="footer-row">
                            <span>Plate: <strong class="text-yellow font-mono">${t.plate_number}</strong></span>
                            <span>Loc: <strong>${t.location}</strong></span>
                        </div>
                    </div>
                `;
            });
            listEl.innerHTML = html;

            // If activeTicketId was set but details are not loaded yet, load them
            if (activeTicketId && !activeTicketData) {
                const found = data.find(t => t.violation_id === activeTicketId);
                if (found) {
                    loadTicketDossier(found.violation_id);
                }
            }
        })
        .catch(err => console.warn("API offline. Ticket logs polling paused."));
}

let statsWS = null;
function connectStatsWS() {
    if (statsWS) statsWS.close();
    statsWS = new WebSocket(`${WS_BASE}/ws/stats`);
    statsWS.onmessage = (msg) => {
        try {
            const data = JSON.parse(msg.data);
            const el = document.getElementById("tickets-count");
            if (el) {
                const newVal = `${data.total_cases} CASES`;
                if (el.innerText !== newVal) {
                    el.innerText = newVal;
                    el.classList.remove("pulse-glow");
                    void el.offsetWidth;
                    el.classList.add("pulse-glow");
                }
            }
        } catch (e) {}
    };
    statsWS.onclose = () => {
        setTimeout(connectStatsWS, 3000);
    };
}

// Called when user clicks a ticket card from the list
function selectTicket(violationId) {
    activeTicketId = violationId;
    activeTicketData = null; // force reload
    pollTickets(); // Force instant re-render to update highlights Snappy!
    loadTicketDossier(violationId);
}

// Query full evidence dossier from API
function loadTicketDossier(violationId) {
    stopReplay(); // Stop any running loops before switching

    fetch(`${API_BASE}/api/cases/${violationId}`)
        .then(res => res.json())
        .then(data => {
            activeTicketData = data;
            
            // Toggle panel displays
            document.getElementById("dossier-empty-placeholder").style.display = "none";
            document.getElementById("dossier-workspace-panel").style.display = "flex";

            // Update Metadata Texts
            document.getElementById("dossier-ticket-id").innerText = data.ticket_id;
            document.getElementById("meta-plate-no").innerText = data.plate_number;
            document.getElementById("meta-violation-type").innerText = data.violation_type.toUpperCase();
            document.getElementById("meta-location").innerText = data.location;
            document.getElementById("meta-confidence").innerText = `${Math.round(data.confidence * 100)}%`;
            document.getElementById("meta-timestamp").innerText = new Date(data.timestamp).toLocaleString();

            // Render Static Crops via new endpoint
            document.getElementById("crop-vehicle-img").src = `${API_BASE}/api/evidence/${data.violation_id}/cropped_vehicle`;
            document.getElementById("crop-plate-img").src = `${API_BASE}/api/evidence/${data.violation_id}/plate_crop`;

            // Display ANPR text overlay
            const ocrOverlay = document.getElementById("ocr-overlay");
            if (ocrOverlay) {
                ocrOverlay.innerText = data.plate_number;
                ocrOverlay.style.display = "block";
            }

            // Preload thumbnails timeline strip via new endpoint
            document.getElementById("thumb-img-0").src = `${API_BASE}/api/evidence/${data.violation_id}/0`;
            document.getElementById("thumb-img-1").src = `${API_BASE}/api/evidence/${data.violation_id}/1`;
            document.getElementById("thumb-img-2").src = `${API_BASE}/api/evidence/${data.violation_id}/2`;
            document.getElementById("thumb-img-3").src = `${API_BASE}/api/evidence/${data.violation_id}/3`;
            document.getElementById("thumb-img-4").src = `${API_BASE}/api/evidence/${data.violation_id}/4`;

            // Reset replay index to T frame (index 2)
            currentFrameIdx = 2;
            showFrame(2);

            // Start auto replay on dossier load
            startReplay();

            // Fetch violation history for this vehicle plate
            fetchViolationHistory(data.plate_number);
        })
        .catch(err => {
            console.error("Error loading ticket case details:", err);
            alert(`Failed to load dossier for violation: ${violationId}`);
        });
}

// Fetch historical cases matching license plate
function fetchViolationHistory(plateNo) {
    fetch(`${API_BASE}/api/violations/history/${encodeURIComponent(plateNo)}`)
        .then(res => res.json())
        .then(historyData => {
            const tbody = document.getElementById("history-tbody");
            
            if (historyData.length <= 1) {
                // There is only this current violation
                tbody.innerHTML = `
                    <tr>
                        <td colspan="4" class="table-empty" style="padding: 15px !important;">No other historic violations logged for this vehicle.</td>
                    </tr>
                `;
                return;
            }

            let rowsHtml = "";
            // Display all other cases (excluding the active one if desired, or displaying all)
            historyData.forEach(h => {
                const formattedDate = new Date(h.timestamp).toLocaleString();
                const isCurrent = h.violation_id === activeTicketId ? "style='background: rgba(0, 242, 254, 0.05);'" : "";
                
                rowsHtml += `
                    <tr ${isCurrent}>
                        <td class="font-mono">${h.ticket_id || h.violation_id}</td>
                        <td class="font-mono">${formattedDate}</td>
                        <td>${h.location}</td>
                        <td class="text-red font-mono">${h.violation_type}</td>
                    </tr>
                `;
            });
            tbody.innerHTML = rowsHtml;
        })
        .catch(err => console.error("Error querying vehicle history logs:", err));
}

// ====================================================
// VIOLATION REPLAY PLAYER CONTROLLERS
// ====================================================
function showFrame(idx) {
    if (!activeTicketData) return;
    
    currentFrameIdx = idx;
    
    // Set image source via new endpoint
    const imgEl = document.getElementById("replay-player-img");
    imgEl.src = `${API_BASE}/api/evidence/${activeTicketData.violation_id}/${idx}`;

    // Update label tag text
    document.getElementById("replay-frame-tag").innerText = FRAME_LABELS[idx];

    // Highlight timeline thumbnail border
    document.querySelectorAll(".timeline-thumbnail-box").forEach(box => box.classList.remove("active-thumb"));
    document.getElementById(`thumb-${idx}`).classList.add("active-thumb");
}

function startReplay() {
    isPlaying = true;
    document.getElementById("btn-play-pause").innerText = "PAUSE";
    
    if (replayIntervalId) clearInterval(replayIntervalId);
    
    replayIntervalId = setInterval(() => {
        currentFrameIdx = (currentFrameIdx + 1) % 5;
        showFrame(currentFrameIdx);
    }, 600); // Cycles frame every 600ms (1.6 frames per second)
}

function stopReplay() {
    isPlaying = false;
    document.getElementById("btn-play-pause").innerText = "PLAY";
    
    if (replayIntervalId) {
        clearInterval(replayIntervalId);
        replayIntervalId = null;
    }
}

function toggleReplay() {
    if (isPlaying) {
        stopReplay();
    } else {
        startReplay();
    }
}

function resetReplay() {
    stopReplay();
    currentFrameIdx = 0;
    showFrame(0);
}

function stepFrame(dir) {
    stopReplay();
    currentFrameIdx = (currentFrameIdx + dir + 5) % 5;
    showFrame(currentFrameIdx);
}

function jumpToFrame(idx) {
    stopReplay();
    showFrame(idx);
}
