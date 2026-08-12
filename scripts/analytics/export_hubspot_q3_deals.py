#!/usr/bin/env python3
"""
Export Q3 2026 deals directly from HubSpot API and compare with Supabase.
"""
import os
import sys
import json
sys.path.insert(0, 'scripts')

from adapters import get_crm_adapter
from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')

if not HUBSPOT_API_KEY:
    print("⚠️  HUBSPOT_API_KEY not set")
    exit(1)

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE credentials not set")
    exit(1)

# Get HubSpot deals via API
print("Fetching Q3 2026 deals from HubSpot API...")
print("="*70)

import requests

# Use HubSpot API directly
headers = {
    "Authorization": f"Bearer {HUBSPOT_API_KEY}",
    "Content-Type": "application/json"
}

search_url = "https://api.hubapi.com/crm/v3/objects/deals/search"

search_payload = {
    "filterGroups": [
        {
            "filters": [
                {
                    "propertyName": "closedate",
                    "operator": "GTE",
                    "value": "1722470400000"  # Aug 1, 2026 00:00:00 UTC in ms
                },
                {
                    "propertyName": "closedate",
                    "operator": "LTE",
                    "value": "1730419199000"  # Oct 31, 2026 23:59:59 UTC in ms
                }
                # NOT filtering by hs_is_closed - it's unreliable!
            ]
        }
    ],
    "properties": [
        "dealname", "amount", "closedate", "dealstage",
        "pipeline", "hs_is_closed", "is_open"
    ],
    "limit": 100
}

all_hubspot_deals = []
after = None

while True:
    if after:
        search_payload['after'] = after

    response = requests.post(search_url, headers=headers, json=search_payload)
    response.raise_for_status()
    data = response.json()

    all_hubspot_deals.extend(data.get('results', []))

    if not data.get('paging'):
        break
    after = data['paging']['next']['after']

print(f"Found {len(all_hubspot_deals)} open Q3 deals from HubSpot API\n")

# Convert to dict
hubspot_dict = {}
from datetime import datetime

for deal in all_hubspot_deals:
    props = deal.get('properties', {})
    deal_id = deal.get('id')

    # Parse close date (can be Unix timestamp ms or ISO string)
    close_ts = props.get('closedate')
    close_date = None
    if close_ts:
        try:
            # Try Unix timestamp milliseconds first
            close_date = datetime.fromtimestamp(int(close_ts)/1000).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            # Try ISO 8601 format
            try:
                close_date = datetime.fromisoformat(close_ts.replace('Z', '+00:00')).strftime('%Y-%m-%d')
            except:
                close_date = close_ts  # Keep as-is if can't parse

    amount = float(props.get('amount', 0) or 0)

    hubspot_dict[deal_id] = {
        'deal_id': deal_id,
        'company_name': props.get('dealname', ''),
        'amount': amount,
        'close_date': close_date,
        'stage': props.get('dealstage', ''),
        'pipeline': props.get('pipeline', ''),
        'is_closed': props.get('hs_is_closed', 'false'),
        'is_open': props.get('is_open', '0')
    }

# Check what is_open values we have
is_open_values = {}
for v in hubspot_dict.values():
    val = v['is_open'] if v['is_open'] else 'null/empty'
    is_open_values[val] = is_open_values.get(val, 0) + 1

print(f"  is_open property values: {is_open_values}")
print(f"  hs_is_closed values: {set(v['is_closed'] for v in hubspot_dict.values())}")

# Use all deals for now (no filtering)
open_deals = hubspot_dict

hubspot_total = sum(d['amount'] for d in open_deals.values())

# Get Supabase Q3 deals
sb = create_client(SUPABASE_URL, SUPABASE_KEY)
result = sb.table('deals')\
    .select('deal_id, company_name, deal_value, close_date, stage, pipeline_id, deal_status')\
    .gte('close_date', '2026-08-01')\
    .lte('close_date', '2026-10-31')\
    .in_('deal_status', ['active', 'prospective'])\
    .eq('pipeline_id', 'default')\
    .execute()

supabase_dict = {d['deal_id']: d for d in result.data}
supabase_total = sum(float(d.get('deal_value') or 0) for d in supabase_dict.values())

print("="*70)
print("DIRECT API COMPARISON")
print("="*70)
print(f"HubSpot API (open Q3):  {len(open_deals):3d} deals  ${hubspot_total:>14,.2f}")
print(f"Supabase (Sales Q3):    {len(supabase_dict):3d} deals  ${supabase_total:>14,.2f}")
print(f"Difference:                           ${hubspot_total - supabase_total:>14,.2f}")

# Find differences
in_hubspot_not_supabase = set(open_deals.keys()) - set(supabase_dict.keys())
in_supabase_not_hubspot = set(supabase_dict.keys()) - set(open_deals.keys())

if in_hubspot_not_supabase:
    missing_value = sum(open_deals[d]['amount'] for d in in_hubspot_not_supabase)
    print(f"\n❌ {len(in_hubspot_not_supabase)} deals in HubSpot API but NOT in Supabase (${missing_value:,.2f}):")
    print("-"*70)

    sorted_missing = sorted(in_hubspot_not_supabase,
                           key=lambda x: hubspot_dict[x]['amount'],
                           reverse=True)

    for deal_id in sorted_missing[:20]:
        d = open_deals[deal_id]
        print(f"  {deal_id:<15s} ${d['amount']:>11,.0f}  {d['close_date']}  {d['company_name'][:40]}")

if in_supabase_not_hubspot:
    extra_value = sum(float(supabase_dict[d].get('deal_value') or 0)
                     for d in in_supabase_not_hubspot)
    print(f"\n⚠️  {len(in_supabase_not_hubspot)} deals in Supabase but NOT in HubSpot API (${extra_value:,.2f}):")
    print("-"*70)

    sorted_extra = sorted(in_supabase_not_hubspot,
                         key=lambda x: float(supabase_dict[x].get('deal_value') or 0),
                         reverse=True)

    for deal_id in sorted_extra[:20]:
        d = supabase_dict[deal_id]
        print(f"  {deal_id:<15s} ${float(d.get('deal_value') or 0):>11,.0f}  {d.get('close_date')}  {(d.get('company_name') or '')[:40]}")

# Check value mismatches
print(f"\n{'='*70}")
print("VALUE MISMATCHES:")
print("="*70)

value_diffs = []
for deal_id in set(open_deals.keys()) & set(supabase_dict.keys()):
    hs_val = open_deals[deal_id]['amount']
    sb_val = float(supabase_dict[deal_id].get('deal_value') or 0)

    if abs(hs_val - sb_val) > 1:
        value_diffs.append({
            'deal_id': deal_id,
            'hs_value': hs_val,
            'sb_value': sb_val,
            'diff': sb_val - hs_val
        })

if value_diffs:
    print(f"Found {len(value_diffs)} value mismatches:")
    for item in sorted(value_diffs, key=lambda x: abs(x['diff']), reverse=True)[:10]:
        print(f"  {item['deal_id']:<15s} HubSpot: ${item['hs_value']:>11,.0f}  "
              f"Supabase: ${item['sb_value']:>11,.0f}  Diff: ${item['diff']:>11,.0f}")
else:
    print("✅ No value mismatches")
