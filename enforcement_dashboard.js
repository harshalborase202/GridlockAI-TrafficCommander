// enforcement_dashboard.js
// Handles queue sorting, explainability checklist cards, frame loop replay, and officer audits.
// All data from SQL endpoints. No Math.random(), no hardcoded counts.

const API_BASE = `${window.location.protocol}//${window.location.host}`;
const WS_BASE  = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;

let currentTickets = [];
let activeTicketId = null;
let activeTicketData = null;

// Replay player state
let replayIntervalId = null;
let currentFrameIdx = 0;
let isPlaying = false;

document.addEventListener("DOMContentLoaded", () => {
    // Start Clock HUD
    startClock();

    // Poll tickets register immediately and every 1s
    pollEnforcementQueues();
    setInterval(pollEnforcementQueues, 1000);

    // Connect WebSocket for live HUD updates
    connectStatsWS();
});

// Clock HUD
function startClock() {
    const clockEl = document.getElementById("clock-display");
    setInterval(() => {
        const now = new Date();
        clockEl.innerText = now.toTimeString().split(' ')[0];
    }, 1000);
}

let lastTicketHash = "";

// Poll and sort tickets dynamically
function pollEnforcementQueues() {
    fetch(`${API_BASE}/api/tickets`)
        .then(res => res.json())
        .then(tickets => {
            // Filter into queues
            const awaiting = tickets.filter(t => t.status === "AWAITING_REVIEW");
            const approved = tickets.filter(t => t.status === "AUTO_APPROVED" || t.status === "APPROVED");
            const discarded = tickets.filter(t => t.status === "DISCARDED");

            // Auto-select first ticket if none active, or if current active ticket was resolved
            const isActiveAwaiting = awaiting.some(t => t.violation_id === activeTicketId);
            const isActiveApproved = approved.some(t => t.violation_id === activeTicketId);
            const isActiveDiscarded = discarded.some(t => t.violation_id === activeTicketId);

            if (!activeTicketId || (!isActiveAwaiting && !isActiveApproved && !isActiveDiscarded)) {
                if (awaiting.length > 0) {
                    activeTicketId = awaiting[0].violation_id;
                    activeTicketData = null; // force reload
                } else {
                    activeTicketId = null;
                    activeTicketData = null;
                    document.getElementById("review-workspace-panel").style.display = "none";
                    document.getElementById("review-empty-placeholder").style.display = "flex";
                }
            }

            // Compare data hash to prevent table rebuilding flicker if no data changes
            const newHash = JSON.stringify([
                activeTicketId,
                tickets.map(t => [t.violation_id, t.status, t.plate_number, t.evidence_score])
            ]);
            if (newHash === lastTicketHash) return;
            lastTicketHash = newHash;

            currentTickets = tickets;

            // Update Counts HUD
            document.getElementById("review-queue-count").innerText = `${awaiting.length} PENDING`;
            document.getElementById("badge-awaiting-count").innerText = `${awaiting.length} CASES`;
            document.getElementById("badge-approved-count").innerText = `${approved.length} CHALLANS`;
            document.getElementById("badge-discarded-count").innerText = `${discarded.length} REJECTS`;

            // 1. Render Awaiting Review table
            const awaitingTbody = document.getElementById("awaiting-tbody");
            if (awaiting.length === 0) {
                awaitingTbody.innerHTML = '<tr><td colspan="6" class="table-empty">No tickets awaiting manual review.</td></tr>';
            } else {
                let html = "";
                awaiting.forEach(t => {
                    const isSelected = t.violation_id === activeTicketId ? "style='background: rgba(0, 242, 254, 0.05);'" : "";
                    html += `
                        <tr ${isSelected} onclick="selectTicketForReview('${t.violation_id}')" style="cursor: pointer;">
                            <td class="font-mono">${t.ticket_id || t.violation_id.replace('V_','TKT_')}</td>
                            <td class="font-mono text-yellow">${t.plate_number}</td>
                            <td>${t.location}</td>
                            <td class="text-red">${t.violation_type}</td>
                            <td class="font-mono text-green">${Math.round(t.evidence_score * 100)}%</td>
                            <td><button class="btn-review">AUDIT</button></td>
                        </tr>
                    `;
                });
                awaitingTbody.innerHTML = html;
            }

            // 2. Render Auto Approved index table
            const approvedTbody = document.getElementById("approved-tbody");
            if (approved.length === 0) {
                approvedTbody.innerHTML = '<tr><td colspan="6" class="table-empty">No challans auto-approved in this session.</td></tr>';
            } else {
                let html = "";
                [...approved].reverse().forEach(t => {
                    const statusLabel = t.status === "AUTO_APPROVED" ? "AUTO APPROVED" : "APPROVED BY OFFICER";
                    const isSelected = t.violation_id === activeTicketId ? "style='background: rgba(0, 242, 254, 0.05);'" : "";
                    html += `
                        <tr ${isSelected} onclick="selectTicketForReview('${t.violation_id}')" style="cursor: pointer;">
                            <td class="font-mono">${t.ticket_id || t.violation_id.replace('V_','TKT_')}</td>
                            <td class="font-mono text-yellow">${t.plate_number}</td>
                            <td>${t.violation_type}</td>
                            <td class="font-mono text-green">&#8377;${t.fine_amount || 0}</td>
                            <td><button class="btn-review" style="padding: 2px 6px; font-size: 8px;">VIEW</button></td>
                            <td><strong class="text-green" style="font-size: 9px; letter-spacing: 0.5px;">${statusLabel}</strong></td>
                        </tr>
                    `;
                });
                approvedTbody.innerHTML = html;
            }

            // 3. Render Discarded table
            const discardedTbody = document.getElementById("discarded-tbody");
            if (discarded.length === 0) {
                discardedTbody.innerHTML = '<tr><td colspan="5" class="table-empty">No cases discarded by system.</td></tr>';
            } else {
                let html = "";
                [...discarded].reverse().forEach(t => {
                    const isSelected = t.violation_id === activeTicketId ? "style='background: rgba(0, 242, 254, 0.05);'" : "";
                    html += `
                        <tr ${isSelected} onclick="selectTicketForReview('${t.violation_id}')" style="cursor: pointer;">
                            <td class="font-mono">${t.ticket_id || t.violation_id.replace('V_','TKT_')}</td>
                            <td class="font-mono text-yellow">${t.plate_number}</td>
                            <td>${t.violation_type}</td>
                            <td class="font-mono text-red">${Math.round(t.evidence_score * 100)}%</td>
                            <td class="text-secondary" style="font-style: italic;">${t.discard_reason || "Low OCR confidence"}</td>
                        </tr>
                    `;
                });
                discardedTbody.innerHTML = html;
            }

            // Keep dossier detail views loaded if currently active
            if (activeTicketId && !activeTicketData) {
                const found = tickets.find(t => t.violation_id === activeTicketId);
                if (found) {
                    loadTicketDossier(found.violation_id);
                }
            }
        })
        .catch(err => console.warn("API offline. Queues polling paused."));
}

function selectTicketForReview(violationId) {
    activeTicketId = violationId;
    activeTicketData = null; // force fresh reload of metadata & replay
    pollEnforcementQueues(); // Force instant re-render to update highlights Snappy!
    loadTicketDossier(violationId);
}

function loadTicketDossier(violationId) {
    stopReplay();

    fetch(`${API_BASE}/api/cases/${violationId}`)
        .then(res => res.json())
        .then(data => {
            activeTicketData = data;

            document.getElementById("review-empty-placeholder").style.display = "none";
            document.getElementById("review-workspace-panel").style.display = "flex";

            document.getElementById("review-ticket-id").innerText = data.ticket_id;
            document.getElementById("meta-plate-no").innerText = data.plate_number;
            document.getElementById("meta-violation-type").innerText = data.violation_type.toUpperCase();
            document.getElementById("meta-location").innerText = data.location;

            // Update SVG confidence gauge
            const scorePct = Math.round(data.evidence_score * 100);
            const gaugeFill = document.getElementById("gauge-fill");
            const gaugeText = document.getElementById("gauge-text");
            const arcLength = 62.8;
            const offset = arcLength * (1 - data.evidence_score);

            let gaugeColor = "var(--accent-red)";
            if (scorePct >= 95) {
                gaugeColor = "var(--accent-green)";
            } else if (scorePct >= 81) {
                gaugeColor = "var(--accent-amber)";
            }

            if (gaugeFill) {
                gaugeFill.style.strokeDashoffset = offset;
                gaugeFill.style.stroke = gaugeColor;
            }
            if (gaugeText) {
                gaugeText.textContent = `${scorePct}%`;
                gaugeText.style.fill = gaugeColor;
            }

            // Images using new API evidence endpoint
            document.getElementById("crop-vehicle-img").src = `${API_BASE}/api/evidence/${data.violation_id}/cropped_vehicle`;
            document.getElementById("crop-plate-img").src = `${API_BASE}/api/evidence/${data.violation_id}/plate_crop`;

            // Display ANPR text overlay
            const ocrOverlay = document.getElementById("ocr-overlay");
            if (ocrOverlay) {
                ocrOverlay.innerText = data.plate_number;
                ocrOverlay.style.display = "block";
            }

            // Render AI Explainability panel checkboxes
            const container = document.getElementById("explainability-container");
            let explainHtml = "";
            if (data.explainability_notes) {
                data.explainability_notes.forEach(note => {
                    let itemClass = "explain-item";
                    if (note.startsWith("✓")) itemClass += " item-pass";
                    else if (note.startsWith("⚠")) itemClass += " item-warn";
                    else if (note.startsWith("✗")) itemClass += " item-fail";

                    explainHtml += `<div class="${itemClass}">${note}</div>`;
                });
            }
            container.innerHTML = explainHtml;

            // Hide/Show action panel buttons based on status
            const controlsRow = document.getElementById("action-controls-row");
            if (data.status === "AWAITING_REVIEW") {
                controlsRow.style.display = "flex";
            } else {
                controlsRow.style.display = "none";
            }

            // Start replay video animation loop
            currentFrameIdx = 0;
            showFrame(0);
            startReplay();
        })
        .catch(err => console.error("Error loading review dossier:", err));
}

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
                        el.innerText = newVal;
                        el.classList.remove("pulse-glow");
                        void el.offsetWidth;
                        el.classList.add("pulse-glow");
                    }
                }
            };
            
            updateVal("review-queue-count", `${data.pending_cases} PENDING`);
            updateVal("badge-awaiting-count", `${data.pending_cases} CASES`);
            updateVal("badge-approved-count", `${data.approved_cases} CHALLANS`);
            updateVal("badge-discarded-count", `${data.discarded_cases} REJECTS`);
        } catch (e) {}
    };
    statsWS.onclose = () => {
        setTimeout(connectStatsWS, 3000);
    };
}

// ====================================================
// REPLAY ENGINE
// ====================================================
function showFrame(idx) {
    if (!activeTicketData) return;
    currentFrameIdx = idx;
    const imgEl = document.getElementById("replay-player-img");
    imgEl.src = `${API_BASE}/api/evidence/${activeTicketData.violation_id}/${idx}`;
    
    const labels = ["T-2 Approach", "T-1 Approach", "T INFRACTION", "T+1 Depart", "T+2 Depart"];
    document.getElementById("replay-frame-tag").innerText = `FRAME: ${labels[idx]}`;
}

function startReplay() {
    isPlaying = true;
    if (replayIntervalId) clearInterval(replayIntervalId);
    replayIntervalId = setInterval(() => {
        currentFrameIdx = (currentFrameIdx + 1) % 5;
        showFrame(currentFrameIdx);
    }, 600);
}

function stopReplay() {
    isPlaying = false;
    if (replayIntervalId) {
        clearInterval(replayIntervalId);
        replayIntervalId = null;
    }
}

// ====================================================
// OFFICER MANUAL DECISION TRIGGERS
// ====================================================
function triggerOfficerApproval() {
    if (!activeTicketId) return;

    if (confirm(`Approve challan for violation ${activeTicketId}?`)) {
        const ticketId = activeTicketData?.ticket_id || activeTicketId;
        fetch(`${API_BASE}/api/tickets/${encodeURIComponent(ticketId)}/approve`, { method: "POST" })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert("Challan APPROVED and finalized.");
                    activeTicketId = null; // Clear so the next pending ticket is auto-selected immediately
                    activeTicketData = null;
                    pollEnforcementQueues();
                }
            })
            .catch(() => alert("Error approving case."));
    }
}

function triggerOfficerDiscard() {
    if (!activeTicketId) return;

    const reason = prompt("Enter discard reason:", "Plate unreadable");
    if (reason === null) return;

    const ticketId = activeTicketData?.ticket_id || activeTicketId;
    fetch(`${API_BASE}/api/tickets/${encodeURIComponent(ticketId)}/discard?reason=${encodeURIComponent(reason)}`, { method: "POST" })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                alert("Case DISCARDED.");
                activeTicketId = null; // Clear so the next pending ticket is auto-selected immediately
                activeTicketData = null;
                pollEnforcementQueues();
            }
        })
        .catch(() => alert("Error discarding case."));
}
