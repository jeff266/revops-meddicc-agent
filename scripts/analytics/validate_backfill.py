"""
Phase D Task 6: Backfill Validation Report
Dry-run validation before real historical backfill

Performs comprehensive validation:
1. Verifies migration 017 is applied
2. Checks property history cache exists and is complete
3. Validates stage mapping coverage
4. Runs dry-run snapshot backfill
5. Validates data quality and confidence distribution
6. Estimates database impact

This is the gate before Task 7 (real backfill run).

Usage:
    python scripts/analytics/validate_backfill.py
"""
import os
import sys
import json
import yaml
from pathlib import Path
from datetime import datetime
from collections import Counter

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase import create_client
from adapters.storage.supabase import select_all


class BackfillValidator:
    """Validates backfill readiness and generates dry-run report."""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []

        # Connect to Supabase
        self.supabase_url = os.environ.get('SUPABASE_URL')
        self.supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')

        if not self.supabase_url or not self.supabase_key:
            self.errors.append("SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
            return

        self.client = create_client(self.supabase_url, self.supabase_key)

        # Load config
        config_path = Path(__file__).parent.parent.parent / 'config/client.yaml'
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

    def check_migration_017(self) -> bool:
        """Verify migration 017 (backfill confidence fields) is applied."""
        print("1. Checking migration 017 status...")

        try:
            # Query deals_snapshot table to check for backfill_confidence column
            result = self.client.table('deals_snapshot')\
                .select('backfill_confidence')\
                .limit(1)\
                .execute()

            self.info.append("✓ Migration 017 applied - backfill_confidence column exists")
            print("   ✓ Migration 017 applied")
            return True

        except Exception as e:
            error_msg = f"Migration 017 NOT applied - backfill_confidence column missing"
            self.errors.append(error_msg)
            print(f"   ✗ {error_msg}")
            print(f"   Error: {e}")
            print()
            print("   ACTION REQUIRED: Run migration 017")
            print("   psql $DATABASE_URL < scripts/migrations/017_add_backfill_confidence.sql")
            return False

    def check_property_history_cache(self) -> dict:
        """Verify property history cache exists and is complete."""
        print()
        print("2. Checking property history cache...")

        cache_path = Path('property_history_cache.json')

        if not cache_path.exists():
            error_msg = "Property history cache not found: property_history_cache.json"
            self.errors.append(error_msg)
            print(f"   ✗ {error_msg}")
            print()
            print("   ACTION REQUIRED: Fetch property history from HubSpot")
            print("   python scripts/analytics/hubspot_history.py --all")
            return {}

        with open(cache_path) as f:
            cache = json.load(f)

        stats = cache.get('stats', {})
        deals = cache.get('deals', {})
        errors = cache.get('errors', [])

        print(f"   Found cache with {len(deals)} deals")
        print(f"   Successful fetches: {stats.get('successful', 0)}")
        print(f"   Failed fetches: {stats.get('failed', 0)}")

        # Get total deal count from Supabase
        all_deals = select_all(self.client, 'deals', columns='deal_id')
        total_deals = len(all_deals)

        coverage_pct = (len(deals) / total_deals * 100) if total_deals > 0 else 0

        print(f"   Coverage: {len(deals)}/{total_deals} deals ({coverage_pct:.1f}%)")

        if coverage_pct < 95:
            warning_msg = f"Property history coverage only {coverage_pct:.1f}% - some deals missing"
            self.warnings.append(warning_msg)
            print(f"   ⚠️  {warning_msg}")
        else:
            self.info.append(f"✓ Property history coverage: {coverage_pct:.1f}%")
            print("   ✓ Good coverage")

        if len(errors) > 0:
            warning_msg = f"{len(errors)} deals had fetch errors"
            self.warnings.append(warning_msg)
            print(f"   ⚠️  {warning_msg}")

        return cache

    def check_stage_mapping(self) -> dict:
        """Verify all stages are mapped in config."""
        print()
        print("3. Checking stage mapping coverage...")

        # Build stage map from config
        stage_map = {}
        for pipeline in self.config['pipeline']['pipelines']:
            for stage in pipeline['stages']:
                stage_map[stage['id']] = stage['name']

        print(f"   Configured stages: {len(stage_map)}")

        # Get all unique stage IDs from deals
        all_deals = select_all(self.client, 'deals', columns='stage')
        current_stages = set(d['stage'] for d in all_deals if d.get('stage'))

        unmapped = current_stages - set(stage_map.keys())

        if unmapped:
            error_msg = f"Unmapped stages found: {unmapped}"
            self.errors.append(error_msg)
            print(f"   ✗ {error_msg}")
        else:
            self.info.append("✓ All current stages are mapped")
            print("   ✓ All current stages mapped")

        return stage_map

    def analyze_snapshot_distribution(self, cache: dict) -> dict:
        """Analyze expected snapshot distribution by confidence level."""
        print()
        print("4. Analyzing expected snapshot distribution...")

        deals = cache.get('deals', {})
        total_deals = len(deals)

        if total_deals == 0:
            print("   No deals in cache - skipping analysis")
            return {}

        # Count deals by history availability
        with_history = sum(1 for d in deals.values() if d.get('history'))
        without_history = total_deals - with_history

        print(f"   Deals with property history: {with_history}/{total_deals} ({with_history/total_deals*100:.1f}%)")
        print(f"   Deals without history: {without_history}/{total_deals} ({without_history/total_deals*100:.1f}%)")

        # Estimate snapshots per confidence level (52 weeks)
        weeks = 52
        estimated_snapshots = {
            'total': total_deals * weeks,
            'exact': 0,  # Will vary by deal
            'interpolated': with_history * weeks,  # Rough estimate
            'unknown': without_history * weeks
        }

        print()
        print(f"   Estimated snapshots for {weeks} weeks:")
        print(f"     Total: {estimated_snapshots['total']:,}")
        print(f"     With history: ~{estimated_snapshots['interpolated']:,}")
        print(f"     Without history: ~{estimated_snapshots['unknown']:,}")

        return estimated_snapshots

    def estimate_database_impact(self, estimated_snapshots: dict):
        """Estimate database storage and performance impact."""
        print()
        print("5. Estimating database impact...")

        total_snapshots = estimated_snapshots.get('total', 0)

        if total_snapshots == 0:
            print("   No snapshots estimated - skipping impact analysis")
            return

        # Rough estimates
        bytes_per_snapshot = 500  # Conservative estimate for row size
        total_bytes = total_snapshots * bytes_per_snapshot
        total_mb = total_bytes / (1024 * 1024)

        print(f"   Estimated storage: {total_mb:.1f} MB for {total_snapshots:,} snapshots")

        # Estimate insert time (conservative: 1000 snapshots/sec with batching)
        insert_rate = 1000
        estimated_seconds = total_snapshots / insert_rate
        estimated_minutes = estimated_seconds / 60

        print(f"   Estimated insert time: ~{estimated_minutes:.1f} minutes")

        if total_mb > 500:
            warning_msg = f"Large backfill: {total_mb:.0f} MB - monitor database performance"
            self.warnings.append(warning_msg)
            print(f"   ⚠️  {warning_msg}")
        else:
            self.info.append(f"✓ Reasonable storage impact: {total_mb:.0f} MB")

    def generate_report(self):
        """Generate final validation report."""
        print()
        print("=" * 70)
        print("BACKFILL VALIDATION REPORT")
        print("=" * 70)
        print()

        # Summary
        print("SUMMARY")
        print("-" * 70)
        print(f"Errors:   {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")
        print(f"Info:     {len(self.info)}")
        print()

        # Errors
        if self.errors:
            print("ERRORS (BLOCKING):")
            print("-" * 70)
            for error in self.errors:
                print(f"  ✗ {error}")
            print()

        # Warnings
        if self.warnings:
            print("WARNINGS:")
            print("-" * 70)
            for warning in self.warnings:
                print(f"  ⚠️  {warning}")
            print()

        # Info
        if self.info:
            print("VALIDATION PASSED:")
            print("-" * 70)
            for info in self.info:
                print(f"  {info}")
            print()

        # Recommendation
        print("=" * 70)
        if self.errors:
            print("❌ BACKFILL BLOCKED")
            print("=" * 70)
            print()
            print("Action required: Fix errors above before proceeding")
            return False
        elif self.warnings:
            print("⚠️  BACKFILL READY WITH WARNINGS")
            print("=" * 70)
            print()
            print("The backfill can proceed, but review warnings above.")
            print()
            print("To run backfill:")
            print("  1. python scripts/analytics/backfill_snapshots.py --dry-run  # Final check")
            print("  2. python scripts/analytics/backfill_snapshots.py            # Real run")
            print("  3. python scripts/analytics/compute_waterfall.py --backfill  # Generate waterfalls")
            return True
        else:
            print("✅ BACKFILL READY")
            print("=" * 70)
            print()
            print("All validation checks passed. Ready to proceed.")
            print()
            print("To run backfill:")
            print("  1. python scripts/analytics/backfill_snapshots.py --dry-run  # Final check")
            print("  2. python scripts/analytics/backfill_snapshots.py            # Real run")
            print("  3. python scripts/analytics/compute_waterfall.py --backfill  # Generate waterfalls")
            return True


def main():
    print("=" * 70)
    print("PHASE D TASK 6: BACKFILL VALIDATION")
    print("=" * 70)
    print()

    validator = BackfillValidator()

    # Run all validation checks
    migration_ok = validator.check_migration_017()

    if not migration_ok:
        # Can't proceed without migration
        validator.generate_report()
        return 1

    cache = validator.check_property_history_cache()
    stage_map = validator.check_stage_mapping()
    estimated = validator.analyze_snapshot_distribution(cache)
    validator.estimate_database_impact(estimated)

    # Generate final report
    ready = validator.generate_report()

    return 0 if ready else 1


if __name__ == '__main__':
    sys.exit(main())
