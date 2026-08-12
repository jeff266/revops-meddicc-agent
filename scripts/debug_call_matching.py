#!/usr/bin/env python3
# Diagnostic: Verifies call matching logic between CSV and deal cache
"""
Debug script to check which HubSpot deals have matching Fireflies/Apollo calls.
"""
import sys
from adapters import get_call_adapter, get_crm_adapter

# Initialize clients
print("Connecting to APIs...")
fireflies = get_call_adapter('fireflies')
apollo = get_call_adapter('apollo')
hubspot = get_crm_adapter()

# Get active deals
print("\nFetching active deals from HubSpot...")
deals = hubspot.get_active_deals()[:10]  # Limit to first 10 for speed
print(f"Found {len(deals)} active deals (showing first 10)\n")

print("=" * 80)
print("DEAL CALL MATCHING REPORT")
print("=" * 80)

for i, deal in enumerate(deals, 1):
    deal_id = deal.get('id')
    deal_name = deal.get('properties', {}).get('dealname', 'Unknown')

    # Get deal context
    deal_context = hubspot.get_deal_context(deal_id)
    company = deal_context.get('company')

    if not company:
        print(f"\n[{i}] {deal_name}")
        print("    ⚠️  No company associated")
        continue

    company_name = company.get('properties', {}).get('name', '')
    contacts = deal_context.get('contacts', [])
    contact_emails = [c.get('properties', {}).get('email') for c in contacts if c.get('properties', {}).get('email')]

    print(f"\n[{i}] {deal_name}")
    print(f"    Company: {company_name}")
    print(f"    Contacts: {len(contact_emails)} ({', '.join(contact_emails[:3])})")

    # Search for calls
    print(f"    Searching Fireflies...")
    fireflies_by_email = []
    if contact_emails:
        fireflies_by_email = fireflies.search_by_contact_emails(contact_emails, max_results=10)
    fireflies_by_name = fireflies.search_by_company(company_name, max_results=10)

    print(f"    Searching Apollo...")
    apollo_calls = apollo.search_conversations_by_company(company_name)

    # Deduplicate Fireflies
    seen_ids = set()
    fireflies_total = []
    for call in fireflies_by_email:
        if call.get('id') not in seen_ids:
            fireflies_total.append(call)
            seen_ids.add(call.get('id'))
    for call in fireflies_by_name:
        if call.get('id') not in seen_ids:
            fireflies_total.append(call)
            seen_ids.add(call.get('id'))

    total_calls = len(fireflies_total) + len(apollo_calls)

    if total_calls > 0:
        print(f"    ✅ FOUND {total_calls} calls ({len(fireflies_total)} Fireflies, {len(apollo_calls)} Apollo)")
        if fireflies_by_email:
            print(f"       - {len(fireflies_by_email)} via email match")
        if fireflies_by_name:
            print(f"       - {len(fireflies_by_name)} via company name match")
    else:
        print(f"    ❌ NO CALLS FOUND")

print("\n" + "=" * 80)
print("Recommendation: Test with deals that show ✅ FOUND calls")
print("=" * 80)
