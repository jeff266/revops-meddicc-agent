#!/usr/bin/env python3
"""
Check if the missing deals exist in Supabase with any status.
"""
import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

missing_deal_ids = [
    '59763534422',  # Ikano Bank
    '57982530888',  # Twilio
    '59387794836',  # Ryanair
    '60667714821',  # Crunchyroll
]

print("Checking if missing deals exist in Supabase with ANY status:")
print("="*70)

for deal_id in missing_deal_ids:
    result = sb.table('deals')\
        .select('deal_id, company_name, deal_status, stage, close_date, deal_value')\
        .eq('deal_id', deal_id)\
        .execute()

    if result.data:
        d = result.data[0]
        print(f"\n✓ {deal_id} EXISTS:")
        print(f"  Company: {d.get('company_name')}")
        print(f"  Status: {d.get('deal_status')}")
        print(f"  Stage: {d.get('stage')}")
        print(f"  Close: {d.get('close_date')}")
        print(f"  Value: ${float(d.get('deal_value') or 0):,.0f}")
    else:
        print(f"\n✗ {deal_id} NOT FOUND in Supabase")

print("\n" + "="*70)
print("Recommendation:")
print("="*70)
print("These deals are in active stages (Discovery, Technical Evaluation)")
print("and should have been synced by --mode active.")
print("\nIf they don't exist at all, run:")
print("  python scripts/etl_deals.py --mode analytics")
print("\nThis will force a full sync of ALL deals regardless of stage.")
