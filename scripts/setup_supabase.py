#!/usr/bin/env python3
"""
Supabase setup script with migration tracking and verification.

Executes migrations via psycopg2 when SUPABASE_DB_URL is set, verifies
each migration's objects exist, and only records verified migrations.

Usage with database connection (recommended):
    export SUPABASE_DB_URL="postgresql://..."
    python scripts/setup_supabase.py

Usage without database connection (manual fallback):
    python scripts/setup_supabase.py
    # Script prints SQL to paste into Supabase SQL editor

Schema isolation (for testing):
    export MIGRATION_SCHEMA="migration_test"
    python scripts/setup_supabase.py

Audit mode (verify schema without executing):
    python scripts/setup_supabase.py --verify-all
    # Verifies all migration fingerprints exist in the database
"""
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Optional

# Try to import psycopg2
try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def parse_fingerprints(sql: str) -> List[Tuple[str, str, Optional[str]]]:
    """
    Extract verification fingerprints from a migration file.

    Returns list of (type, name, column) tuples:
        - ('table', 'deals', None) for CREATE TABLE deals
        - ('column', 'deals', 'deal_status') for ALTER TABLE deals ADD COLUMN deal_status
        - ('index', 'idx_deals_status', None) for CREATE INDEX

    Migrations that only drop/alter without creating (e.g., DROP CONSTRAINT)
    return an empty list - nothing to verify.
    """
    fingerprints = []

    # Match CREATE TABLE [IF NOT EXISTS] table_name
    for match in re.finditer(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)',
        sql,
        re.IGNORECASE
    ):
        table_name = match.group(1)
        fingerprints.append(('table', table_name, None))

    # Match ALTER TABLE table_name ADD COLUMN [IF NOT EXISTS] column_name
    for match in re.finditer(
        r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)',
        sql,
        re.IGNORECASE
    ):
        table_name = match.group(1)
        column_name = match.group(2)
        fingerprints.append(('column', table_name, column_name))

    # Match CREATE INDEX [IF NOT EXISTS] index_name
    for match in re.finditer(
        r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)',
        sql,
        re.IGNORECASE
    ):
        index_name = match.group(1)
        fingerprints.append(('index', index_name, None))

    return fingerprints


def verify_fingerprints(conn, schema: str, fingerprints: List[Tuple[str, str, Optional[str]]]) -> Tuple[bool, List[str]]:
    """
    Verify that all fingerprint objects exist in the specified schema.

    Returns (success, missing_list) where missing_list describes what's absent.
    """
    cur = conn.cursor()
    missing = []

    for fp_type, name, column in fingerprints:
        try:
            if fp_type == 'table':
                # Verify table exists
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s LIMIT 1",
                    (schema, name)
                )
                if not cur.fetchone():
                    missing.append(f"table {schema}.{name}")

            elif fp_type == 'column':
                # Verify column exists in table
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s AND column_name = %s LIMIT 1",
                    (schema, name, column)
                )
                if not cur.fetchone():
                    missing.append(f"column {schema}.{name}.{column}")

            elif fp_type == 'index':
                # Verify index exists
                cur.execute(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE schemaname = %s AND indexname = %s LIMIT 1",
                    (schema, name)
                )
                if not cur.fetchone():
                    missing.append(f"index {schema}.{name}")

        except Exception as e:
            missing.append(f"{fp_type} {name} (error: {e})")

    cur.close()
    return (len(missing) == 0, missing)


def ensure_migrations_table(conn, schema: str):
    """Create _migrations tracking table in the specified schema."""
    cur = conn.cursor()
    cur.execute(f"SET search_path TO {schema};")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id         SERIAL PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()


def get_applied(conn, schema: str) -> set:
    """Return set of already-applied migration names from the specified schema."""
    cur = conn.cursor()
    try:
        cur.execute(f"SET search_path TO {schema};")
        cur.execute("SELECT name FROM _migrations;")
        applied = {row[0] for row in cur.fetchall()}
        cur.close()
        return applied
    except Exception:
        # Table doesn't exist yet
        cur.close()
        return set()


def run_migration_psycopg2(conn, schema: str, path: Path) -> Tuple[bool, str]:
    """
    Execute a migration via psycopg2, verify it, and record it.

    Returns (success, message).
    """
    sql = path.read_text()
    fingerprints = parse_fingerprints(sql)

    cur = conn.cursor()

    try:
        # Set search_path for this migration
        cur.execute(f"SET search_path TO {schema};")

        # Execute the entire migration file
        # (psycopg2 handles multiple statements; splitting on ';' breaks on comment semicolons)
        cur.execute(sql)

        conn.commit()

        # Verify fingerprints (if any)
        if fingerprints:
            success, missing = verify_fingerprints(conn, schema, fingerprints)
            if not success:
                msg = f"Verification failed - missing: {', '.join(missing)}"
                cur.close()
                return (False, msg)

        # Record as applied
        cur.execute("INSERT INTO _migrations (name, applied_at) VALUES (%s, %s);",
                   (path.name, datetime.now(timezone.utc)))
        conn.commit()
        cur.close()

        return (True, "Done")

    except Exception as e:
        conn.rollback()
        cur.close()
        return (False, str(e))


def print_manual_instructions(pending_migrations: List[Path]):
    """Print instructions for manually applying migrations."""
    print("\n" + "=" * 60)
    print("MANUAL APPLICATION REQUIRED")
    print("=" * 60)
    print("\nSUPABASE_DB_URL is not set. Migrations must be applied")
    print("manually via the Supabase SQL editor.\n")

    print("Steps:")
    print("1. Go to your Supabase project → SQL Editor")
    print("2. Paste and run each migration below (in order)")
    print("3. Re-run this script to verify and record them\n")

    for i, path in enumerate(pending_migrations, 1):
        print(f"\n{'=' * 60}")
        print(f"Migration {i}/{len(pending_migrations)}: {path.name}")
        print("=" * 60)
        print(path.read_text())

    print("\n" + "=" * 60)
    print("After pasting all migrations into the SQL editor,")
    print("re-run this script with SUPABASE_DB_URL set to verify")
    print("and record them.")
    print("=" * 60)


def reload_postgrest_schema(conn):
    """Attempt to reload PostgREST schema cache."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_notify('pgrst', 'reload schema');")
        conn.commit()
        cur.close()
        print("\n✓ PostgREST schema reload requested")
        print("\nIf new tables/columns aren't visible in your app:")
        print("  1. Test with a PATCH to a nonexistent row (should 404)")
        print("  2. If stale, restart the Supabase project")
    except Exception:
        pass


def verify_all_migrations(conn, schema: str, migration_files: List[Path]) -> bool:
    """
    Audit mode: verify all migrations' fingerprints exist, regardless of
    _migrations table status. Read-only - executes nothing, writes nothing.

    Returns True if all migrations verified, False otherwise.
    """
    print("=" * 70)
    print("SCHEMA AUDIT MODE - Verifying all migrations")
    print("=" * 70)
    print(f"\nSchema: {schema}")
    print(f"Migrations to verify: {len(migration_files)}\n")

    all_passed = True
    results = []

    for path in migration_files:
        sql = path.read_text()
        fingerprints = parse_fingerprints(sql)

        if not fingerprints:
            # No objects to verify (e.g., 010 - drops only)
            results.append((path.name, True, "no objects to verify"))
            print(f"  {path.name}")
            print(f"    ✓ PASS (no objects to verify)")
            continue

        # Verify fingerprints
        success, missing = verify_fingerprints(conn, schema, fingerprints)
        results.append((path.name, success, missing if not success else None))

        if success:
            print(f"  {path.name}")
            print(f"    ✓ PASS ({len(fingerprints)} objects verified)")
        else:
            print(f"  {path.name}")
            print(f"    ✗ FAIL - Missing objects:")
            for obj in missing:
                print(f"      - {obj}")
            all_passed = False

    print("\n" + "=" * 70)
    print("AUDIT SUMMARY")
    print("=" * 70)

    passed_count = sum(1 for _, success, _ in results if success)
    failed_count = len(results) - passed_count

    print(f"\nTotal migrations: {len(results)}")
    print(f"  ✓ Passed: {passed_count}")
    if failed_count > 0:
        print(f"  ✗ Failed: {failed_count}")
        print("\nFailed migrations:")
        for name, success, missing in results:
            if not success:
                print(f"  - {name}: {', '.join(missing)}")

    print("\n" + "=" * 70)

    if all_passed:
        print("✅ All migrations verified - schema matches migration files")
        return True
    else:
        print("⛔ Schema audit failed - missing objects found")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Supabase migration runner with verification'
    )
    parser.add_argument(
        '--verify-all',
        action='store_true',
        help='Audit mode: verify all migrations exist (read-only, no execution)'
    )
    args = parser.parse_args()

    schema = os.getenv('MIGRATION_SCHEMA', 'public')
    db_url = os.getenv('SUPABASE_DB_URL')

    # Check if we can execute migrations
    if not db_url:
        print("⚠️  SUPABASE_DB_URL not set - manual application mode")
        print("Migrations will be printed for manual application.\n")
        use_psycopg2 = False
    elif not HAS_PSYCOPG2:
        print("⚠️  psycopg2 not installed")
        print("Install with: pip install psycopg2-binary\n")
        use_psycopg2 = False
    else:
        use_psycopg2 = True

    # Find migration files
    migrations_dir = Path('scripts/migrations')
    if not migrations_dir.exists():
        print(f'ERROR: {migrations_dir} not found.')
        print('Run from the repo root directory.')
        return 1

    migration_files = sorted(
        f for f in migrations_dir.glob('*.sql')
        if re.match(r'^\d+_', f.name)
    )

    if not migration_files:
        print('No migration files found in scripts/migrations/')
        return 1

    # VERIFY-ALL MODE: audit schema without execution
    if args.verify_all:
        if not use_psycopg2:
            print("⛔ ERROR: --verify-all requires SUPABASE_DB_URL to be set")
            return 1

        try:
            print(f"Connecting to database (schema: {schema})...")
            conn = psycopg2.connect(db_url)
            print("✓ Connected\n")

            all_passed = verify_all_migrations(conn, schema, migration_files)
            conn.close()

            return 0 if all_passed else 1
        except Exception as e:
            print(f"⛔ Connection failed: {e}")
            return 1

    # Connect and check applied migrations
    if use_psycopg2:
        try:
            print(f"Connecting to database (schema: {schema})...")
            conn = psycopg2.connect(db_url)
            print("✓ Connected\n")

            ensure_migrations_table(conn, schema)
            applied = get_applied(conn, schema)
        except Exception as e:
            print(f"⛔ Connection failed: {e}")
            print("\nFalling back to manual application mode.\n")
            use_psycopg2 = False
            conn = None
            applied = set()
    else:
        conn = None
        applied = set()

    pending = [f for f in migration_files if f.name not in applied]

    # Report status
    if not pending:
        print('All migrations already applied:')
        for f in migration_files:
            print(f'  ✓ {f.name}')
        print()
        if use_psycopg2:
            conn.close()
        return 0

    if applied:
        print('Already applied:')
        for name in sorted(applied):
            print(f'  ✓ {name}')
        print()

    # Apply pending migrations
    if use_psycopg2:
        print(f'Applying {len(pending)} pending migration(s)...\n')
        failed = False

        for path in pending:
            print(f'  → {path.name}')
            success, msg = run_migration_psycopg2(conn, schema, path)

            if success:
                print(f'    ✓ {msg}')
            else:
                print(f'    ✗ FAILED: {msg}')
                print(f'\nMigration SQL:\n{path.read_text()}\n')
                print('Paste the above SQL into Supabase SQL editor to apply manually.')
                failed = True
                break

        if not failed:
            print()
            reload_postgrest_schema(conn)
            print('\n✓ Setup complete.')

        conn.close()
        return 1 if failed else 0

    else:
        # Manual application mode
        print_manual_instructions(pending)
        return 1


if __name__ == '__main__':
    sys.exit(main())
