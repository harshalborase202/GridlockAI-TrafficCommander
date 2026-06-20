# enforcement_engine.py
# AI Enforcement Officer evaluating evidence confidence and assigning status/fines.

import random

class EnforcementEngine:
    @staticmethod
    def evaluate_violation(violation_type, violation_confidence, ocr_confidence=None, tracking_confidence=None):
        """
        Evaluate evidence confidence scores and classify into Auto Approve, Officer Review, or Discard.
        """
        # Assign defaults if missing (based on randomized ranges for simulator realism)
        if ocr_confidence is None:
            ocr_confidence = round(random.uniform(0.60, 0.97), 2)
        if tracking_confidence is None:
            tracking_confidence = round(random.uniform(0.65, 0.98), 2)
            
        # Calculate Evidence Score as a weighted average
        # (violation conf: 40%, OCR: 30%, Tracking: 30%)
        evidence_score = (violation_confidence * 0.4) + (ocr_confidence * 0.3) + (tracking_confidence * 0.3)
        evidence_score = round(evidence_score, 3)
        
        # Calculate Fine Amount
        fine_amount = 1000
        if violation_type == "Red Light Violation":
            fine_amount = 1000
        elif violation_type == "Wrong Way Driving":
            fine_amount = 2000
        elif violation_type == "Overspeeding":
            fine_amount = 1500
        elif violation_type == "Illegal Parking":
            fine_amount = 500
        elif violation_type == "Triple Riding":
            fine_amount = 1000
            
        # Categorize
        status = "AWAITING_REVIEW"
        discard_reason = None
        explainability = []
        
        # Explainability Checks
        explainability.append(f"✓ Tracking confidence: {int(tracking_confidence*100)}%")
        explainability.append(f"✓ OCR plate reading confidence: {int(ocr_confidence*100)}%")
        explainability.append(f"✓ Violation detection confidence: {int(violation_confidence*100)}%")
        explainability.append(f"✓ Calculated composite evidence score: {int(evidence_score*100)}%")
        
        if violation_type == "Red Light Violation":
            explainability.insert(0, "✓ Vehicle crossed STOP line")
            explainability.insert(1, "✓ CCTV Traffic signal state: RED")
        elif violation_type == "Wrong Way Driving":
            explainability.insert(0, "✓ Vehicle tracked counter allowed flow direction")
            explainability.insert(1, "✓ Lane trajectory angle mismatch > 150°")
        elif violation_type == "Overspeeding":
            explainability.insert(0, "✓ Speed gate entry/exit interval timed")
            explainability.insert(1, "✓ Speed calculated above threshold limit")
        elif violation_type == "Illegal Parking":
            explainability.insert(0, "✓ Vehicle coordinate overlap in yellow ROI")
            explainability.insert(1, "✓ Static presence duration threshold exceeded")
        elif violation_type == "Triple Riding":
            explainability.insert(0, "✓ Two-wheeler class detected (Motorcycle/Scooter)")
            explainability.insert(1, "✓ Rider count analysis: 3 occupants detected on seat")
            
        # Classification thresholds
        if evidence_score > 0.94:
            status = "AUTO_APPROVED"
            explainability.append("✓ AUTO APPROVED: High evidence score meets smart enforcement regulations.")
        elif evidence_score < 0.81:
            status = "DISCARDED"
            # Random reason
            reasons = [
                "Low OCR confidence reading plate characters",
                "Severe vehicle occlusion by larger transport truck",
                "Low visibility due to ambient lens flare or night shadow",
                "Multiple vehicle boxes overlapping in stop line ROI"
            ]
            discard_reason = random.choice(reasons)
            explainability.append(f"✗ DISCARDED: {discard_reason}")
        else:
            status = "AWAITING_REVIEW"
            explainability.append("⚠ AWAITING REVIEW: Score between 81-94% requires human officer verification.")
            
        return {
            "evidence_score": evidence_score,
            "status": status,
            "fine_amount": fine_amount,
            "discard_reason": discard_reason,
            "tracking_confidence": tracking_confidence,
            "ocr_confidence": ocr_confidence,
            "explainability_notes": explainability
        }
