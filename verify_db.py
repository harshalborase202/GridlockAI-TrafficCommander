import database
import json
import time

print("Waiting 10s for simulator to write data...")
time.sleep(10)

stats = database.query_live_stats()
print("=== LIVE STATS FROM DB ===")
print(json.dumps(stats, indent=2))

alerts = database.query_recent_alerts(5)
print(f"\n=== RECENT ALERTS ({len(alerts)}) ===")
for a in alerts:
    print(f"  [{a['type']}] {a['title']}: {a['text']}")

violations = database.query_all_violations(5)
print(f"\n=== VIOLATIONS IN DB ({len(violations)}) ===")
for v in violations:
    print(f"  {v['violation_id']} | {v['violation_type']} | {v['plate_number']} | {v['status']}")

tickets = database.query_all_tickets(3)
print(f"\n=== TICKETS IN DB ({len(tickets)}) ===")
for t in tickets:
    print(f"  {t['ticket_id']} | {t['fine_amount']} INR | {t['status']}")

breakdown = database.query_violation_type_breakdown()
print(f"\n=== VIOLATION TYPE BREAKDOWN ===")
for b in breakdown:
    print(f"  {b['violation_type']}: {b['count']}")
