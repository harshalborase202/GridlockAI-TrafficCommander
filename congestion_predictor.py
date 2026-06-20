# congestion_predictor.py
# Uses rolling historical congestion data to predict future traffic density levels.

class CongestionPredictor:
    def __init__(self, history_limit=12):
        """
        Initialize the CongestionPredictor.
        Args:
            history_limit: Number of entries (each representing 5 mins) to keep in queue (default 1 hour).
        """
        self.history_limit = history_limit
        self.congestion_history = {}  # {junction_id: [congestion_pct, ...]}

    def add_history_point(self, junction_id, congestion_pct):
        """Adds a live congestion reading to the junction's historical queue."""
        if junction_id not in self.congestion_history:
            self.congestion_history[junction_id] = []
            
        self.congestion_history[junction_id].append(float(congestion_pct))
        
        # Limit historical queue size
        if len(self.congestion_history[junction_id]) > self.history_limit:
            self.congestion_history[junction_id].pop(0)

    def predict(self, junction_id, current_congestion):
        """
        Predict congestion levels 15 minutes and 30 minutes in the future.
        Uses a moving average trend interpolation.
        Returns:
            dict: Projections containing current status, and 15-min / 30-min predictions.
        """
        history = self.congestion_history.get(junction_id, [])
        
        # Ensure current value is seeded in history
        if not history or history[-1] != current_congestion:
            self.add_history_point(junction_id, current_congestion)
            history = self.congestion_history[junction_id]

        # 1. Fallback if history is insufficient
        # Extrapolate using a mild default baseline coefficient (adds 3% and 5% for demo variance)
        if len(history) < 3:
            pred_15 = max(0.0, min(100.0, current_congestion + 3.0))
            pred_30 = max(0.0, min(100.0, current_congestion + 5.0))
        else:
            # 2. Moving Average calculation
            # Calculate short-term average (last 3 intervals) vs long-term average (up to 12 intervals)
            short_term_avg = sum(history[-3:]) / len(history[-3:])
            long_term_avg = sum(history) / len(history)
            
            # Find the trend gradient
            # Positive trend means congestion is rising. Negative means it is clearing.
            trend_slope = (short_term_avg - long_term_avg) / max(1.0, len(history) - 3)
            
            # Extrapolate:
            # 15 minutes = 3 intervals of 5 minutes.
            # 30 minutes = 6 intervals of 5 minutes.
            pred_15 = current_congestion + (trend_slope * 3.0)
            pred_30 = current_congestion + (trend_slope * 6.0)

            # Add mild noise variance for organic visual feel in demo loops
            import random
            pred_15 += random.uniform(-1.5, 1.5)
            pred_30 += random.uniform(-2.5, 2.5)

            # Clamp between 0% and 100%
            pred_15 = max(0.0, min(100.0, pred_15))
            pred_30 = max(0.0, min(100.0, pred_30))

        return {
            "current_congestion": round(current_congestion, 1),
            "current_status": self._get_status_label(current_congestion),
            "prediction_15_min": round(pred_15, 1),
            "prediction_15_status": self._get_status_label(pred_15),
            "prediction_30_min": round(pred_30, 1),
            "prediction_30_status": self._get_status_label(pred_30)
        }

    def _get_status_label(self, val):
        """Maps percentage values to status descriptions."""
        if val <= 25.0:
            return "LOW"
        elif val <= 55.0:
            return "MEDIUM"
        elif val <= 85.0:
            return "HIGH"
        return "GRIDLOCK"
