#!/usr/bin/env python3
"""
Match HubSpot's exact filters:
- Sales pipeline only (pipeline != Renewal)
- Exclude Meeting Set stage
- Open deals (active/prospective)
"""
import os
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get Q3 2026 deals with HubSpot's exact filters
result = sb.table('deals')\
    .select('deal_id, company_name, deal_value, close_date, stage, pipeline_id, deal_status')\
    .gte('close_date', '2026-08-01')\
    .lte('close_date', '2026-10-31')\
    .in_('deal_status', ['active', 'prospective'])\
    .eq('pipeline_id', 'default')\
    .execute()

# Filter out "Meeting Set" stage
# Common meeting set stage IDs in HubSpot: appointmentscheduled, meetingscheduled, etc.
meeting_set_keywords = ['appointment', 'meeting', 'meetingset', 'meeting_set', 'meetingscheduled']
deals_filtered = [
    d for d in result.data
    if not any(keyword in (d.get('stage') or '').lower() for keyword in meeting_set_keywords)
]

filtered_value = sum(float(d.get('deal_value') or 0) for d in deals_filtered)

print("="*70)
print("Q3 2026 with HubSpot's Exact Filters Applied")
print("="*70)
print(f"\nFilters:")
print(f"  1. Sales pipeline only (pipeline_id = 'default')")
print(f"  2. Exclude Meeting Set stage")
print(f"  3. Open deals (active/prospective)")
print(f"  4. Close date: Aug 1 - Oct 31, 2026")
print(f"\nResults:")
print(f"  Deals matching filters:  {len(deals_filtered):3d}")
print(f"  Total value:             ${filtered_value:>14,.2f}")
print(f"\nHubSpot screenshot:        $7,798,832.45")
print(f"Difference:                ${filtered_value - 7798832.45:>14,.2f}")
print(f"Match %:                   {(filtered_value / 7798832.45 * 100):>14.2f}%")

# Show top deals
print(f"\n{'='*70}")
print("Top 20 deals (Sales pipeline, excluding Meeting Set):")
print("="*70)
print(f"{'Company':<40s} {'Value':>12s} {'Close Date':<12s} {'Stage'}")
print("-"*70)

deals_filtered.sort(key=lambda x: float(x.get('deal_value') or 0), reverse=True)
for d in deals_filtered[:20]:
    company = (d.get('company_name') or 'Unknown')[:40]
    value = float(d.get('deal_value') or 0)
    close = d.get('close_date') or 'N/A'
    stage = (d.get('stage') or 'N/A')[:30]
    print(f"{company:<40s} ${value:>11,.0f} {close:<12s} {stage}")

# Check what deals were excluded by Meeting Set filter
all_sales_q3 = result.data
meeting_set_deals = [
    d for d in all_sales_q3
    if any(keyword in (d.get('stage') or '').lower() for keyword in meeting_set_keywords)
]

if meeting_set_deals:
    meeting_set_value = sum(float(d.get('deal_value') or 0) for d in meeting_set_deals)
    print(f"\n{'='*70}")
    print(f"Excluded by Meeting Set filter: {len(meeting_set_deals)} deals, ${meeting_set_value:,.2f}")
    print("="*70)
    for d in sorted(meeting_set_deals, key=lambda x: float(x.get('deal_value') or 0), reverse=True)[:10]:
        company = (d.get('company_name') or 'Unknown')[:40]
        value = float(d.get('deal_value') or 0)
        stage = d.get('stage') or 'N/A'
        print(f"  {company:<40s} ${value:>11,.0f}  {stage}")
