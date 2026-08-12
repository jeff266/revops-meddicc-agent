#!/usr/bin/env python3
"""
Merge duplicate call cache files for the same company.
Run after ETL if you see ambiguous slug warnings.

Usage:
  python scripts/dedupe_cache.py

Shows duplicates and merges on confirmation.
"""
import json
import yaml
from pathlib import Path
from collections import defaultdict

CALLS_DIR = Path(__file__).parent.parent / 'memory' / 'calls'


def _get_vendor_slug() -> str:
    """
    Read the organization name from config/client.yaml (same pattern as
    utils.slugify). Lowercased and hyphenated. Falls back to 'yourcompany'
    if missing or still a placeholder.
    """
    vendor = 'yourcompany'  # Default
    try:
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        if config_path.exists():
            config = yaml.safe_load(open(config_path)) or {}
            org_name = config.get('organization', {}).get('name', '')
            if org_name and 'YOUR_' not in org_name:
                vendor = org_name.lower()
    except Exception:
        pass  # Use default if config fails
    return vendor.replace(' ', '-')


def get_base_slug(stem: str) -> str:
    """Extract the company name from a cache filename."""
    # Remove the configured vendor suffix/prefix
    vendor_slug = _get_vendor_slug()
    stem = stem.replace(f'{vendor_slug}-', '') \
               .replace(f'-{vendor_slug}', '')
    # Take first meaningful segment
    return stem.split('-')[0] if '-' in stem else stem


def main():
    files = list(CALLS_DIR.glob('*.json'))
    files = [f for f in files if f.name != '.gitkeep']

    # Group by base slug
    groups = defaultdict(list)
    for f in files:
        base = get_base_slug(f.stem)
        groups[base].append(f)

    duplicates = {k: v for k, v in groups.items()
                  if len(v) > 1}

    if not duplicates:
        print('No duplicate cache files found.')
        return

    print(f'Found {len(duplicates)} potential duplicates:\n')
    for base, files in sorted(duplicates.items()):
        print(f'  {base}:')
        for f in files:
            d = json.load(open(f))
            print(f'    {f.name} ({len(d.get("calls",[]))} calls)')

    print()
    confirm = input('Merge duplicates? (y/N): ')
    if confirm.lower() != 'y':
        print('Aborted.')
        return

    for base, dupe_files in sorted(duplicates.items()):
        # Collect all calls, deduplicate by ID
        all_calls = {}
        company_name = ''
        for f in dupe_files:
            d = json.load(open(f))
            company_name = company_name or d.get('company', '')
            for call in d.get('calls', []):
                all_calls[call['id']] = call

        merged = sorted(all_calls.values(),
                        key=lambda c: c.get('date', ''))

        # Write to canonical name (shortest = cleanest)
        canonical = min(dupe_files, key=lambda f: len(f.stem))
        with open(canonical, 'w') as out:
            json.dump({
                'company': company_name,
                'calls': merged
            }, out, indent=2)

        # Delete the others
        for f in dupe_files:
            if f != canonical:
                f.unlink()
                print(f'  Deleted: {f.name}')
        print(f'  Merged → {canonical.name} ({len(merged)} calls)')


if __name__ == '__main__':
    main()
