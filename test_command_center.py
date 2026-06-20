# test_command_center.py
# Unit and integration test suite for the FastAPI Dashboard backend and Analytics engines.

import os
import json
from fastapi.testclient import TestClient

# Import backend modules
from dashboard_api import app, j_manager, predictor, demo_sim
from analytics_engine import AnalyticsEngine

client = TestClient(app)

def test_backend_components():
    print("="*60)
    print("     PHASE 4: COMMAND CENTER & DIGITAL TWIN TEST SUITE")
    print("="*60)

    # 1. Test Analytics Risk Score calculations
    print("[1/6] Testing Analytics Engine risk score equations...")
    analytics = AnalyticsEngine()
    
    # Test case A: Low congestion, no violations, normal speeds
    risk_low = analytics.calculate_risk_score(
        congestion_level=10, active_violations=0, average_speed=45.0, parking_violations=0
    )
    assert risk_low["risk_score"] <= 30, f"Expected low risk, got {risk_low}"
    assert risk_low["category"] == "LOW RISK"
    assert risk_low["color"] == "Green"
    print("  [OK] Low-risk equations validated.")

    # Test case B: Extreme congestion, active violations, crawling speed, parked truck
    risk_critical = analytics.calculate_risk_score(
        congestion_level=90, active_violations=4, average_speed=12.0, parking_violations=1
    )
    assert risk_critical["risk_score"] >= 70, f"Expected high risk, got {risk_critical}"
    assert risk_critical["color"] in ["Orange", "Red"]
    print("  [OK] Critical-risk equations validated.")

    # 2. Test Congestion Predictor trends
    print("[2/6] Testing Congestion Predictor moving averages...")
    j_id = "silk_board_junction"
    
    # Seed historical congestion coordinates (increasing congestion slope)
    predictor.congestion_history[j_id] = [40.0, 45.0, 50.0, 55.0, 60.0]
    proj = predictor.predict(j_id, 60.0)
    
    # Assert that predictions are successfully returned and trend upward (> 60%)
    assert "prediction_15_min" in proj
    assert proj["prediction_15_min"] >= 60.0, f"Expected upward trend, got {proj}"
    print("  [OK] Congestion predictor MA trend analysis verified.")

    # 3. Test REST API: /api/junctions
    print("[3/6] Testing REST Endpoint: GET /api/junctions...")
    response = client.get("/api/junctions")
    assert response.status_code == 200
    data = response.json()
    assert "junctions" in data
    assert "active_junction_id" in data
    assert len(data["junctions"]) == 3
    print("  [OK] /api/junctions returned 3 valid intersections.")

    # 4. Test REST API: POST /api/junctions/active
    print("[4/6] Testing REST Endpoint: POST /api/junctions/active...")
    response = client.post("/api/junctions/active?junction_id=silk_board_junction")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["active_junction_id"] == "silk_board_junction"
    print("  [OK] Junction-switching controller verified.")

    # 5. Test REST API: GET /api/live-stats & Heatmaps
    print("[5/6] Testing REST Endpoints: GET /api/live-stats & GET /api/heatmap...")
    # Stats
    response = client.get("/api/live-stats")
    assert response.status_code == 200
    data = response.json()
    assert data["system_status"] == "ONLINE"
    assert "global_analytics" in data
    assert "alerts_timeline" in data
    print("  [OK] /api/live-stats returned active HUD values.")

    # Heatmap Density
    response = client.get("/api/heatmap?type=density")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "density"
    assert len(data["points"]) > 0
    print("  [OK] /api/heatmap?type=density returned thermal coordinate array.")

    # 6. Test REST API: Case Ticket details retrieval
    print("[6/6] Testing REST Endpoint: GET /api/cases/{ticket_id}...")
    # Seed a simulated violation so uvicorn has a case to fetch
    demo_sim._generate_simulated_violation(j_manager.get_junction("silk_board_junction"), 999, 500)
    
    # Fetch uvicorn violations list to find valid ticket ID
    violations_resp = client.get("/api/violations")
    assert violations_resp.status_code == 200
    violations_list = violations_resp.json()
    assert len(violations_list) > 0
    ticket_id = violations_list[0]["ticket_id"]
    
    # Query ticket case details
    case_resp = client.get(f"/api/cases/{ticket_id}")
    assert case_resp.status_code == 200
    case_data = case_resp.json()
    assert case_data["ticket_id"] == ticket_id
    assert case_data["plate_number"] == violations_list[0]["plate_number"]
    print(f"  [OK] Case review lookup validated for ticket: {ticket_id}")

    print("="*60)
    print("          ALL DIGITAL TWIN INTEGRATION TESTS PASSED")
    print("="*60)

if __name__ == "__main__":
    test_backend_components()
