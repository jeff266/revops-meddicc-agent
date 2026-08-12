#!/usr/bin/env python3
"""
Explain the $740K gap between HubSpot screenshot ($7.8M) and Supabase ($8.5M).
"""
import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get all Q3 2026 active deals
result = sb.table('deals')\
    .select('deal_id, company_name, deal_value, close_date, stage, pipeline_id, deal_status')\
    .gte('close_date', '2026-08-01')\
    .lte('close_date', '2026-10-31')\
    .in_('deal_status', ['active', 'prospective'])\
    .execute()

deals = result.data

# Separate by pipeline
sales_deals = [d for d in deals if d.get('pipeline_id') == 'default']
renewal_deals = [d for d in deals if d.get('pipeline_id') != 'default']

sales_value = sum(float(d.get('deal_value') or 0) for d in sales_deals)
renewal_value = sum(float(d.get('deal_value') or 0) for d in renewal_deals)
total_value = sales_value + renewal_value

print("="*70)
print("Q3 2026 (Aug-Oct) Pipeline Breakdown")
print("="*70)
print(f"\nSales Pipeline:    {len(sales_deals):3d} deals  ${sales_value:>14,.2f}")
print(f"Renewal Pipeline:  {len(renewal_deals):3d} deals  ${renewal_value:>14,.2f}")
print(f"                   ---          ----------------")
print(f"Total Supabase:    {len(deals):3d} deals  ${total_value:>14,.2f}")
print(f"\nHubSpot Screenshot:              $7,798,832.45")
print(f"Difference:                      ${total_value - 7798832.45:>14,.2f}")

print(f"\n{'='*70}")
print("Hypothesis Testing:")
print("="*70)

# Hypothesis 1: Screenshot is Sales only
if abs(sales_value - 7798832.45) < abs(total_value - 7798832.45):
    print(f"\n✓ HubSpot might be showing Sales only:")
    print(f"  Sales value: ${sales_value:,.2f}")
    print(f"  HubSpot:     $7,798,832.45")
    print(f"  Diff:        ${sales_value - 7798832.45:,.2f}")
else:
    print(f"\n✗ Sales only doesn't match:")
    print(f"  Sales value: ${sales_value:,.2f}")
    print(f"  HubSpot:     $7,798,832.45")
    print(f"  Diff:        ${sales_value - 7798832.45:,.2f}")

# Check if excluding certain stages gets us closer
print(f"\n{'='*70}")
print("Top deals that might explain the $740K gap:")
print("="*70)

all_deals_sorted = sorted(deals, key=lambda x: float(x.get('deal_value') or 0), reverse=True)
cumulative = 0
gap_to_fill = total_value - 7798832.45

print(f"\nNeed to exclude ${gap_to_fill:,.2f} to match HubSpot\n")
print(f"{'Deal ID':<15s} {'Value':>12s} {'Cumulative':>12s} {'Pipeline':<10s} {'Company'}")
print("-"*80)

for d in all_deals_sorted[:30]:
    value = float(d.get('deal_value') or 0)
    cumulative += value
    pipeline = 'Renewal' if d.get('pipeline_id') != 'default' else 'Sales'
    company = (d.get('company_name') or 'Unknown')[:35]

    marker = " ← HIT" if abs(cumulative - gap_to_fill) < 50000 else ""
    print(f"{d['deal_id']:<15s} ${value:>11,.0f} ${cumulative:>11,.0f} {pipeline:<10s} {company}{marker}")

    if cumulative >= gap_to_fill:
        print(f"\n✓ First {all_deals_sorted.index(d) + 1} deals total ${cumulative:,.0f}")
        print(f"  This would bring Supabase down from ${total_value:,.0f} to ${total_value - cumulative:,.0f}")
        print(f"  Target is: $7,798,832.45")
        break
