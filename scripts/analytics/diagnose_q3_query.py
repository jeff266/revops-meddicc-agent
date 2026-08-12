#!/usr/bin/env python3
"""
Diagnose Q3 query — check what Supabase actually has for Aug-Oct in both 2026 and 2027.
"""
import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

print("="*70)
print("Q3 2026 (Aug 1 - Oct 31, 2026) — CURRENT Q3")
print("="*70)

# Query 1: What does Supabase have for Aug-Oct 2026?
result_2026 = sb.table('deals')\
    .select('deal_id, company_name, close_date, deal_value, deal_status')\
    .gte('close_date', '2026-08-01')\
    .lte('close_date', '2026-10-31')\
    .in_('deal_status', ['active', 'prospective'])\
    .order('deal_value', desc=True)\
    .limit(20)\
    .execute()

deals_2026 = result_2026.data
print(f"\nTop 20 active deals with close_date Aug-Oct 2026:")
print(f"{'Company':<35s} {'Close Date':<12s} {'Value':>12s} {'Status':<12s}")
print("-"*70)
for d in deals_2026:
    company = (d.get('company_name') or 'Unknown')[:35]
    close = d.get('close_date') or 'N/A'
    value = float(d.get('deal_value') or 0)
    status = d.get('deal_status') or 'N/A'
    print(f"{company:<35s} {close:<12s} ${value:>11,.0f} {status:<12s}")

# Query 2: Count and sum for Aug-Oct 2026
result_2026_agg = sb.table('deals')\
    .select('deal_value, deal_status')\
    .gte('close_date', '2026-08-01')\
    .lte('close_date', '2026-10-31')\
    .in_('deal_status', ['active', 'prospective'])\
    .execute()

count_2026 = len(result_2026_agg.data)
sum_2026 = sum(float(d.get('deal_value') or 0) for d in result_2026_agg.data)

print(f"\nAGGREGATE for Aug-Oct 2026 (active/prospective):")
print(f"  Count: {count_2026}")
print(f"  Sum:   ${sum_2026:,.2f}")
print(f"  HubSpot shows for Q3 2027: $7,798,832.45")
print(f"  Difference: ${sum_2026 - 7798832.45:,.2f}")

print("\n" + "="*70)
print("Q3 2027 (Aug 1 - Oct 31, 2027) — FUTURE Q3")
print("="*70)

# Query 3: What does Supabase have for Aug-Oct 2027?
result_2027 = sb.table('deals')\
    .select('deal_id, company_name, close_date, deal_value, deal_status')\
    .gte('close_date', '2027-08-01')\
    .lte('close_date', '2027-10-31')\
    .in_('deal_status', ['active', 'prospective'])\
    .order('deal_value', desc=True)\
    .limit(20)\
    .execute()

deals_2027 = result_2027.data
print(f"\nTop 20 active deals with close_date Aug-Oct 2027:")
print(f"{'Company':<35s} {'Close Date':<12s} {'Value':>12s} {'Status':<12s}")
print("-"*70)
for d in deals_2027:
    company = (d.get('company_name') or 'Unknown')[:35]
    close = d.get('close_date') or 'N/A'
    value = float(d.get('deal_value') or 0)
    status = d.get('deal_status') or 'N/A'
    print(f"{company:<35s} {close:<12s} ${value:>11,.0f} {status:<12s}")

# Query 4: Count and sum for Aug-Oct 2027
result_2027_agg = sb.table('deals')\
    .select('deal_value, deal_status')\
    .gte('close_date', '2027-08-01')\
    .lte('close_date', '2027-10-31')\
    .in_('deal_status', ['active', 'prospective'])\
    .execute()

count_2027 = len(result_2027_agg.data)
sum_2027 = sum(float(d.get('deal_value') or 0) for d in result_2027_agg.data)

print(f"\nAGGREGATE for Aug-Oct 2027 (active/prospective):")
print(f"  Count: {count_2027}")
print(f"  Sum:   ${sum_2027:,.2f}")
print(f"  HubSpot shows for Q3 2027: $7,798,832.45")
print(f"  Difference: ${sum_2027 - 7798832.45:,.2f}")
