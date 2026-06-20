# analytics_engine.py
# Calculates city-wide safety and congestion risk scores based on traffic parameters.

class AnalyticsEngine:
    def __init__(self):
        # Default reference parameters for normal safe operations
        self.nominal_speed_kmph = 45.0  # Speed limit reference

    def calculate_risk_score(self, congestion_level, active_violations, average_speed, parking_violations=0):
        """
        Calculate a traffic risk score scaled from 0 to 100.
        Formula:
            Risk = 0.3*Density + 0.3*Violations + 0.2*SpeedDeviation + 0.2*ParkingViolations
        Args:
            congestion_level: Current congestion percentage (0 to 100).
            active_violations: Count of currently active violations.
            average_speed: Average speed of vehicles in km/h.
            parking_violations: Count of illegal parking incidents.
        Returns:
            dict: Contains risk_score (int), category (str), and color (str).
        """
        # 1. Density Component (0 to 100)
        density_comp = float(congestion_level)

        # 2. Violation Frequency Component (Scale: each violation adds 15 points, max 100)
        violation_comp = min(100.0, float(active_violations) * 15.0)

        # 3. Speed Deviation Component
        # Risk increases both for congestion crawls (speed < 15) and speeding (speed > limit)
        speed_dev = abs(float(average_speed) - self.nominal_speed_kmph)
        speed_comp = min(100.0, speed_dev * 4.0)

        # 4. Parking Component (Each parked vehicle blocks a lane, high hazard: 25 points each)
        parking_comp = min(100.0, float(parking_violations) * 25.0)

        # 5. Compile Weighted Score
        raw_score = (0.3 * density_comp) + (0.3 * violation_comp) + (0.2 * speed_comp) + (0.2 * parking_comp)
        risk_score = int(round(max(0.0, min(100.0, raw_score))))

        # 6. Map to Risk Category and Alert Colors
        if risk_score <= 30:
            category = "LOW RISK"
            color = "Green"
        elif risk_score <= 60:
            category = "MODERATE RISK"
            color = "Yellow"
        elif risk_score <= 85:
            category = "HIGH RISK"
            color = "Orange"
        else:
            category = "CRITICAL RISK"
            color = "Red"

        return {
            "risk_score": risk_score,
            "category": category,
            "color": color
        }
