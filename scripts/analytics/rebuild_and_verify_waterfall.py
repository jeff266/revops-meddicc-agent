#!/usr/bin/env python3
"""
Rebuild waterfall for 2026-08-10 and verify close_date and company_name are present.
"""
import os
import json
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Step 1: Delete old waterfall data
print("Deleting old waterfall data for 2026-08-10...")
sb.table('waterfall_weekly').delete().eq('week_ending', '2026-08-10').execute()
print("✓ Deleted\n")

# Step 2: Recompute waterfall
print("Recomputing waterfall...")
import subprocess
result = subprocess.run(
    ['python', 'scripts/analytics/compute_waterfall.py'],
    capture_output=True,
    text=True
)
print(result.stdout)
if result.stderr:
    print(result.stderr)
if result.returncode != 0:
    print(f"⚠️  Waterfall computation failed with exit code {result.returncode}")
    exit(1)

# Step 3: Verify close_date and company_name are present
print("\n" + "="*70)
print("VERIFICATION: Top 10 deals with company_name and close_date")
print("="*70 + "\n")

result = sb.table('waterfall_weekly').select('details').eq('week_ending', '2026-08-10').execute()
all_details = []
for row in result.data:
    details = json.loads(row['details']) if isinstance(row['details'], str) else row['details']
    all_details.extend(details)

# Sort by value descending
all_details.sort(key=lambda x: float(x.get('value', 0) or 0), reverse=True)

for detail in all_details[:10]:
    company = detail.get('company_name', 'N/A')[:30]
    change = detail.get('change_type', 'N/A')
    close_date = detail.get('close_date', 'N/A')
    value = float(detail.get('value', 0) or 0)
    print(f"{company:30s} {change:15s} {close_date:12s} ${value:>12,.0f}")

# Step 4: Test Q3 slice query
print("\n" + "="*70)
print("Q3 SLICE (May 1 - Jul 31, 2026)")
print("="*70 + "\n")

q3_deals = [d for d in all_details
            if d.get('close_date') and '2026-05-01' <= d.get('close_date') <= '2026-07-31']
q3_count = len(q3_deals)
q3_value = sum(float(d.get('value', 0) or 0) for d in q3_deals)

print(f"Deals in Q3: {q3_count}")
print(f"Q3 Value: ${q3_value:,.0f}")

print("\n✓ Verification complete")
