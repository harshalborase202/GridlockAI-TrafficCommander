// analytics_dashboard.js
// All charts fed from SQL endpoints. No Math.random(), no hardcoded baselines.

const API_BASE = `${window.location.protocol}//${window.location.host}`;

let predictionsJunctionId = "silk_board_junction";
let congestionHistory = [];   // filled from /api/congestion/{cam_id}

document.addEventListener("DOMContentLoaded", () => {
    // Start Clock HUD
    startClock();

    // Poll live predictions and stats
    pollPredictions();
    pollRiskStats();
    
    // Draw initial charts
    initCharts();

    // Polling schedules
    setInterval(pollPredictions, 3000);
    setInterval(pollRiskStats, 3000);
});

// HUD Clock Timer
function startClock() {
    const clockEl = document.getElementById("clock-display");
    setInterval(() => {
        const now = new Date();
        clockEl.innerText = now.toTimeString().split(' ')[0];
    }, 1000);
}

// Handle Junction predictions switch dropdown
function changePredictionsJunction() {
    predictionsJunctionId = document.getElementById("predictions-junction-select").value;
    const labelEl = document.getElementById("congestion-graph-label");
    const nameMap = {
        "silk_board_junction": "SILK BOARD JUNCTION",
        "koramangala_3rd_block": "KORAMANGALA 3RD BLOCK",
        "indiranagar_100ft_road": "INDIRANAGAR 100FT ROAD"
    };
    labelEl.innerText = nameMap[predictionsJunctionId] || "MONITORED CAMERA";
    congestionHistory = [];  // reset; will be filled from DB
    pollPredictions();
    drawCongestionSwings();
}

// Poll congestion data from canonical DB endpoint
const junctionToCam = {
    "silk_board_junction":    "cam_12",
    "koramangala_3rd_block":  "cam_13",
    "indiranagar_100ft_road": "cam_14",
};

function pollPredictions() {
    const camId = junctionToCam[predictionsJunctionId] || predictionsJunctionId;

    // 1. Fetch last 60 congestion_log rows from DB
    fetch(`${API_BASE}/api/congestion/${camId}?n=60`)
        .then(r => r.json())
        .then(data => {
            const pts = data.points || [];
            if (pts.length > 0) {
                // Replace history with real DB data
                congestionHistory = pts.map(p => Math.round(p.congestion_pct ?? 0));
            }

            // Current congestion = latest point
            const latest = pts[pts.length - 1];
            const curCong = latest ? (latest.congestion_pct ?? 0) : 0;

            // Determine status string from congestion %
            const toStatus = pct => {
                if (pct >= 80) return "GRIDLOCK";
                if (pct >= 60) return "HIGH";
                if (pct >= 35) return "MEDIUM";
                return "LOW";
            };

            updatePredictorBlock("current", curCong, toStatus(curCong));
            // Simple linear projection for 15/30 min
            const slope = pts.length >= 2
                ? ((pts[pts.length-1].congestion_pct ?? 0) - (pts[0].congestion_pct ?? 0)) / pts.length
                : 0;
            const pred15 = Math.max(0, Math.min(100, curCong + slope * 5));
            const pred30 = Math.max(0, Math.min(100, curCong + slope * 10));
            updatePredictorBlock("15", pred15, toStatus(pred15));
            updatePredictorBlock("30", pred30, toStatus(pred30));

            drawCongestionSwings();
        })
        .catch(() => {
            // Fallback: try congestion predictor endpoint
            fetch(`${API_BASE}/api/congestion`)
                .then(r => r.json())
                .then(data => {
                    updatePredictorBlock("current", data.current_congestion, data.current_status);
                    updatePredictorBlock("15", data.prediction_15_min, data.prediction_15_status);
                    updatePredictorBlock("30", data.prediction_30_min, data.prediction_30_status);
                })
                .catch(() => {});
        });
}

function updatePredictorBlock(prefix, val, status) {
    const valEl = document.getElementById(`pred-${prefix}-level`);
    const statusEl = document.getElementById(`pred-${prefix}-status`);

    valEl.innerText = `${Math.round(val)}%`;
    statusEl.innerText = status;

    statusEl.className = "status-badge";
    if (status === "LOW") statusEl.classList.add("status-low");
    else if (status === "MEDIUM") statusEl.classList.add("status-medium");
    else if (status === "HIGH") statusEl.classList.add("status-high");
    else if (status === "GRIDLOCK") statusEl.classList.add("status-gridlock");
}

// Poll Junction statistics to populate the Risk Index meters
let violationChart = null;
let congestionChart = null;

function pollRiskStats() {
    fetch(`${API_BASE}/api/stats/cameras`)
        .then(res => res.json())
        .then(cameras => {
            const tbody = document.getElementById("risk-tbody");
            let html = "";
            
            cameras.forEach(cam => {
                let levelStr = "LOW RISK";
                let levelColor = "var(--accent-green)";
                if (cam.risk > 75) {
                    levelStr = "CRITICAL RISK";
                    levelColor = "var(--accent-red)";
                } else if (cam.risk > 45) {
                    levelStr = "MODERATE RISK";
                    levelColor = "var(--accent-amber)";
                }

                html += `
                    <tr>
                        <td style="width: 40%; font-weight: 600;">
                            ${cam.name} <br>
                            <span style="font-size: 10px; font-weight: 400; color: var(--text-secondary);">
                                Active Violations: <strong class="text-red">${cam.violations}</strong>
                            </span>
                        </td>
                        <td style="width: 20%; font-weight: 800; font-family: monospace; font-size: 14px; text-align: right; color: ${levelColor};">
                            ${cam.risk} pts
                        </td>
                        <td style="width: 40%; padding-left: 20px;">
                            <span style="font-size: 9px; font-weight: 800; color: ${levelColor}; letter-spacing: 0.5px;">${levelStr}</span>
                            <div class="risk-score-bar-bg">
                                <div class="risk-score-bar-fill" style="width: ${cam.risk}%; background: ${levelColor};"></div>
                            </div>
                        </td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;

            // Also reload violation trends counts based on actual tickets
            pollViolationCounts();
        })
        .catch(err => {});
}

// ====================================================
// GRAPHIC CHART CANVAS PLOTTERS (USING CHART.JS)
// ====================================================
function initCharts() {
    pollViolationCounts();
    drawCongestionSwings();
}

function pollViolationCounts() {
    // Fetch count per violation type from the new analytics endpoint
    fetch(`${API_BASE}/api/analytics/violations-by-type`)
        .then(r => r.json())
        .then(data => {
            const counts = {
                "Red Light Violation": 0,
                "Wrong Way Driving":   0,
                "Illegal Parking":     0,
                "Overspeeding":        0,
            };
            data.forEach(item => {
                const t = item.violation_type || "";
                if (t in counts) counts[t] = item.count;
                else if (t.includes("Red"))     counts["Red Light Violation"] += item.count;
                else if (t.includes("Wrong"))   counts["Wrong Way Driving"] += item.count;
                else if (t.includes("Park"))    counts["Illegal Parking"] += item.count;
                else if (t.includes("Speed") || t.includes("Over")) counts["Overspeeding"] += item.count;
            });
            drawViolationTrends(counts);
        })
        .catch(() => {
            drawViolationTrends({
                "Red Light Violation": 0,
                "Wrong Way Driving":   0,
                "Illegal Parking":     0,
                "Overspeeding":        0,
            });
        });
}

function drawViolationTrends(counts) {
    const canvas = document.getElementById("violation-trends-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const dataVals = [
        counts["Red Light Violation"] || 0,
        counts["Wrong Way Driving"] || 0,
        counts["Illegal Parking"] || 0,
        counts["Overspeeding"] || 0
    ];

    if (violationChart) {
        violationChart.data.datasets[0].data = dataVals;
        violationChart.update();
    } else {
        violationChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ['RED LIGHT', 'WRONG WAY', 'ILG PARKING', 'SPEEDING'],
                datasets: [{
                    label: 'Violations Today',
                    data: dataVals,
                    backgroundColor: [
                        'var(--accent-red)',
                        'var(--accent-amber)',
                        '#9b59b6',
                        '#ff6b35'
                    ],
                    borderWidth: 0,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#8892a4', font: { family: 'Inter', size: 10 } }
                    },
                    y: {
                        grid: { color: 'rgba(255,255,255,0.03)' },
                        ticks: { color: '#8892a4', font: { family: 'Inter', size: 10 } }
                    }
                }
            }
        });
    }
}

function drawCongestionSwings() {
    const canvas = document.getElementById("congestion-trends-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const camId = junctionToCam[predictionsJunctionId] || predictionsJunctionId;
    fetch(`${API_BASE}/api/analytics/congestion_history/${camId}?n=20`)
        .then(r => r.json())
        .then(data => {
            const pts = data.points || [];
            const labels = pts.map(p => {
                const tStr = p.recorded_at || "";
                return tStr.includes(" ") ? tStr.split(" ")[1] : tStr.includes("T") ? tStr.split("T")[1].substring(0, 8) : tStr;
            });
            const values = pts.map(p => Math.round(p.congestion_pct ?? p.congestion_level ?? 0));

            if (congestionChart) {
                congestionChart.data.labels = labels;
                congestionChart.data.datasets[0].data = values;
                congestionChart.update();
            } else {
                congestionChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Congestion %',
                            data: values,
                            borderColor: 'var(--accent-cyan)',
                            backgroundColor: 'rgba(0, 212, 255, 0.05)',
                            fill: true,
                            tension: 0.4,
                            borderWidth: 2,
                            pointRadius: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false }
                        },
                        scales: {
                            x: {
                                grid: { display: false },
                                ticks: { color: '#8892a4', font: { family: 'Inter', size: 9 }, maxRotation: 45 }
                            },
                            y: {
                                min: 0,
                                max: 100,
                                grid: { color: 'rgba(255,255,255,0.03)' },
                                ticks: { color: '#8892a4', font: { family: 'Inter', size: 10 } }
                            }
                        }
                    }
                });
            }
        })
        .catch(() => {});
}
