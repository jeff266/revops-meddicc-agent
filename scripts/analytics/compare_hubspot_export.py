#!/usr/bin/env python3
"""
Compare HubSpot Q3 export CSV with Supabase deals table.
Find missing deals, value differences, and field mismatches.
"""
import os
import csv
from datetime import datetime
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Read HubSpot export CSV
from pathlib import Path
script_dir = Path(__file__).parent
csv_path = script_dir / 'hubspot_q3_export.csv'
hubspot_deals = {}

with open(csv_path, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        deal_id = row['Record ID']
        close_date = row['Close Date']

        # Parse close_date and filter to Q3 FY2027 = Aug 1 - Oct 31, 2026
        if close_date:
            dt = datetime.strptime(close_date, '%Y-%m-%d %H:%M')
            if '2026-08-01' <= dt.strftime('%Y-%m-%d') <= '2026-10-31':
                amount_str = row['Amount in company currency']
                amount = float(amount_str) if amount_str else 0.0

                hubspot_deals[deal_id] = {
                    'deal_id': deal_id,
                    'company_name': row['Deal Name'],
                    'deal_value': amount,
                    'close_date': dt.strftime('%Y-%m-%d'),
                    'stage': row['Deal Stage'],
                    'pipeline': row['Pipeline']
                }

print(f"HubSpot Q3 2026 (Aug-Oct) deals from CSV: {len(hubspot_deals)}")
hubspot_total = sum(d['deal_value'] for d in hubspot_deals.values())
print(f"HubSpot Q3 total: ${hubspot_total:,.2f}\n")

# Get Supabase Q3 deals
result = sb.table('deals')\
    .select('deal_id, company_name, deal_value, close_date, stage, pipeline_id, deal_status')\
    .gte('close_date', '2026-08-01')\
    .lte('close_date', '2026-10-31')\
    .in_('deal_status', ['active', 'prospective'])\
    .execute()

supabase_deals = {d['deal_id']: d for d in result.data}
print(f"Supabase Q3 2026 (Aug-Oct) active deals: {len(supabase_deals)}")
supabase_total = sum(float(d.get('deal_value') or 0) for d in supabase_deals.values())
print(f"Supabase Q3 total: ${supabase_total:,.2f}\n")

# Find differences
print("="*80)
print("DEAL-BY-DEAL COMPARISON")
print("="*80 + "\n")

# 1. Deals in HubSpot but not in Supabase
missing_in_supabase = set(hubspot_deals.keys()) - set(supabase_deals.keys())
if missing_in_supabase:
    print(f"❌ {len(missing_in_supabase)} deals in HubSpot CSV but MISSING from Supabase:\n")
    missing_value = sum(hubspot_deals[did]['deal_value'] for did in missing_in_supabase)
    for deal_id in sorted(missing_in_supabase, key=lambda x: hubspot_deals[x]['deal_value'], reverse=True)[:10]:
        d = hubspot_deals[deal_id]
        print(f"  {deal_id:12s} ${d['deal_value']:>10,.0f}  {d['company_name'][:50]}")
    print(f"\n  Missing total: ${missing_value:,.2f}\n")
else:
    print("✅ All HubSpot deals found in Supabase\n")

# 2. Deals in Supabase but not in HubSpot CSV
extra_in_supabase = set(supabase_deals.keys()) - set(hubspot_deals.keys())
if extra_in_supabase:
    print(f"⚠️  {len(extra_in_supabase)} deals in Supabase but NOT in HubSpot CSV (may have moved out of Q3):\n")
    extra_value = sum(float(supabase_deals[did].get('deal_value') or 0) for did in extra_in_supabase)
    for deal_id in sorted(extra_in_supabase, key=lambda x: float(supabase_deals[x].get('deal_value') or 0), reverse=True)[:10]:
        d = supabase_deals[deal_id]
        print(f"  {deal_id:12s} ${float(d.get('deal_value') or 0):>10,.0f}  {(d.get('company_name') or '')[:50]}")
    print(f"\n  Extra total: ${extra_value:,.2f}\n")
else:
    print("✅ No extra deals in Supabase\n")

# 3. Deals in both but with value differences
print("VALUE MISMATCHES (deals in both but different amounts):\n")
value_diffs = []
for deal_id in set(hubspot_deals.keys()) & set(supabase_deals.keys()):
    hs_val = hubspot_deals[deal_id]['deal_value']
    sb_val = float(supabase_deals[deal_id].get('deal_value') or 0)

    if abs(hs_val - sb_val) > 1:  # Allow $1 rounding difference
        diff = sb_val - hs_val
        value_diffs.append({
            'deal_id': deal_id,
            'company': hubspot_deals[deal_id]['company_name'],
            'hs_value': hs_val,
            'sb_value': sb_val,
            'diff': diff
        })

if value_diffs:
    value_diffs.sort(key=lambda x: abs(x['diff']), reverse=True)
    print(f"Found {len(value_diffs)} value mismatches:\n")
    print(f"{'Deal ID':<15s} {'HubSpot':>12s} {'Supabase':>12s} {'Diff':>12s} {'Company'}")
    print("-"*80)
    for item in value_diffs[:20]:
        print(f"{item['deal_id']:<15s} ${item['hs_value']:>11,.0f} ${item['sb_value']:>11,.0f} "
              f"${item['diff']:>11,.0f} {item['company'][:35]}")

    total_diff = sum(abs(x['diff']) for x in value_diffs)
    print(f"\nTotal absolute difference: ${total_diff:,.2f}")
else:
    print("✅ All deal values match between HubSpot and Supabase\n")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"HubSpot CSV Q3 deals:   {len(hubspot_deals):3d}  ${hubspot_total:>14,.2f}")
print(f"Supabase Q3 deals:      {len(supabase_deals):3d}  ${supabase_total:>14,.2f}")
print(f"Missing from Supabase:  {len(missing_in_supabase):3d}  ${sum(hubspot_deals[d]['deal_value'] for d in missing_in_supabase) if missing_in_supabase else 0:>14,.2f}")
print(f"Extra in Supabase:      {len(extra_in_supabase):3d}  ${sum(float(supabase_deals[d].get('deal_value') or 0) for d in extra_in_supabase) if extra_in_supabase else 0:>14,.2f}")
print(f"Value mismatches:       {len(value_diffs):3d}")
