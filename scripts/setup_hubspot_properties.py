#!/usr/bin/env python3
"""
One-time setup: creates the per-component properties in HubSpot
(scores, statuses, and rationale text fields) for the configured
qualification methodology (MEDDICC, MEDDPIC, SPICED, or BANT).

Idempotent — skips properties that already exist.

Usage: HUBSPOT_API_KEY=... python scripts/setup_hubspot_properties.py
"""

import os, json, requests
from utils import get_components, component_key, get_methodology

BASE = "https://api.hubapi.com"

def _get_components() -> list[tuple[str, str]]:
    """Returns (key, label) pairs from the client's configured
    methodology. Works for MEDDICC, MEDDPIC, SPICED, BANT."""
    return [(component_key(c), c) for c in get_components()]

def _group_name() -> str:
    return f"{get_methodology().lower()}_scoring"

def get_headers():
    return {
        "Authorization": f"Bearer {os.environ['HUBSPOT_API_KEY']}",
        "Content-Type": "application/json"
    }

def ensure_group():
    """Create the property group if needed."""
    group = _group_name()
    resp = requests.get(
        f"{BASE}/crm/v3/properties/deals/groups/{group}",
        headers=get_headers()
    )
    if resp.status_code == 200:
        print(f"Group '{group}' already exists")
        return
    resp = requests.post(
        f"{BASE}/crm/v3/properties/deals/groups",
        headers=get_headers(),
        json={
            "name": group,
            "label": f"{get_methodology()} Scoring",
            "displayOrder": 10
        }
    )
    resp.raise_for_status()
    print(f"Created group '{group}'")

def get_existing_props() -> set:
    resp = requests.get(
        f"{BASE}/crm/v3/properties/deals",
        params={"limit": 1000},
        headers=get_headers()
    )
    resp.raise_for_status()
    return {p["name"] for p in resp.json().get("results", [])}

def create_property(name, label, field_type, prop_type,
                    description="", options=None):
    body = {
        "name": name,
        "label": label,
        "type": prop_type,
        "fieldType": field_type,
        "groupName": _group_name(),
        "description": description,
        "hasUniqueValue": False,
    }
    if options:
        body["options"] = options
    resp = requests.post(
        f"{BASE}/crm/v3/properties/deals",
        headers=get_headers(),
        json=body
    )
    resp.raise_for_status()
    return resp.json()

def main():
    ensure_group()
    existing = get_existing_props()
    created, skipped = [], []
    methodology = get_methodology()
    prefix = methodology.lower()

    for key, label in _get_components():
        # Score property (number, 1-10)
        score_name = f"{prefix}_{key}_score"
        if score_name not in existing:
            create_property(
                name=score_name,
                label=f"{label} Score",
                field_type="number",
                prop_type="number",
                description=f"{methodology} {label} score (1-10). "
                            f"Derived from cumulative call history."
            )
            created.append(score_name)
            print(f"  Created: {score_name}")
        else:
            skipped.append(score_name)
            print(f"  Exists:  {score_name}")

        # Status property (enum: identified/partial/unknown)
        status_name = f"{prefix}_{key}_status"
        if status_name not in existing:
            create_property(
                name=status_name,
                label=f"{label} Status",
                field_type="select",
                prop_type="enumeration",
                description=f"{methodology} {label} qualification status.",
                options=[
                    {"label": "Identified", "value": "identified",
                     "displayOrder": 0, "hidden": False},
                    {"label": "Partial",    "value": "partial",
                     "displayOrder": 1, "hidden": False},
                    {"label": "Unknown",    "value": "unknown",
                     "displayOrder": 2, "hidden": False},
                ]
            )
            created.append(status_name)
            print(f"  Created: {status_name}")
        else:
            skipped.append(status_name)

        # Rationale property (text, max 1000 chars)
        rationale_name = f"{prefix}_{key}_rationale"
        if rationale_name not in existing:
            create_property(
                name=rationale_name,
                label=f"{label} Evidence",
                field_type="textarea",
                prop_type="string",
                description=f"Evidence from call history supporting "
                            f"the {label} score. Auto-updated nightly."
            )
            created.append(rationale_name)
            print(f"  Created: {rationale_name}")
        else:
            skipped.append(rationale_name)
            print(f"  Exists:  {rationale_name}")

    print(f"\nDone. Created {len(created)}, skipped {len(skipped)}.")
    print("Created:", created)

if __name__ == "__main__":
    main()
