#!/usr/bin/env python3
"""
Migration Runner — apply SQL migrations to Supabase PostgreSQL.

Usage:
    python scripts/run_migrations.py              # Apply all pending migrations
    python scripts/run_migrations.py --schema     # Apply full schema (fresh DB)
    python scripts/run_migrations.py --status     # Show migration status

Requires SUPABASE_URL and SUPABASE_KEY environment variables.
Uses the Supabase REST API to execute SQL via the rpc endpoint,
or falls back to direct psycopg2 if available.
"""

import os
import sys
import logging

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SQL_DIR = os.path.join(os.path.dirname(__file__), "..", "sql")
MIGRATIONS_DIR = os.path.join(SQL_DIR, "migrations")


def get_migration_files():
    """Get ordered list of migration SQL files."""
    if not os.path.isdir(MIGRATIONS_DIR):
        return []
    files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))
    return files


def read_sql(filepath):
    """Read a SQL file."""
    with open(filepath, "r") as f:
        return f.read()


def execute_via_supabase(sql: str):
    """Execute SQL using Supabase Python client."""
    from app.database import get_db_client
    client = get_db_client()
    if not client:
        raise RuntimeError("Supabase client not available. Check SUPABASE_URL/SUPABASE_KEY.")

    # Use the rpc endpoint to execute raw SQL
    # Supabase service role key allows this
    try:
        result = client.rpc("exec_sql", {"query": sql}).execute()
        return True
    except Exception as e:
        # If rpc doesn't exist, try the postgrest approach
        logger.warning(f"RPC exec_sql not available ({e}). SQL must be run manually.")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Niyam AI Migration Runner")
    parser.add_argument("--schema", action="store_true", help="Apply full schema (fresh DB)")
    parser.add_argument("--status", action="store_true", help="Show migration files")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")
    args = parser.parse_args()

    if args.status:
        files = get_migration_files()
        print(f"\nFound {len(files)} migration(s):")
        for f in files:
            print(f"  - {f}")
        schema_path = os.path.join(SQL_DIR, "schema.sql")
        print(f"\nBase schema: {'EXISTS' if os.path.exists(schema_path) else 'MISSING'}")
        return

    if args.schema:
        schema_path = os.path.join(SQL_DIR, "schema.sql")
        if not os.path.exists(schema_path):
            logger.error(f"Schema file not found: {schema_path}")
            sys.exit(1)

        sql = read_sql(schema_path)
        print(f"\n--- Applying base schema ({len(sql)} chars) ---")
        if args.dry_run:
            print(sql[:500] + "..." if len(sql) > 500 else sql)
        else:
            if execute_via_supabase(sql):
                print("Schema applied successfully.")
            else:
                print("\nCould not apply via API. Run this SQL manually in Supabase SQL Editor:")
                print(f"  File: {schema_path}")

    # Apply migrations
    files = get_migration_files()
    if not files:
        print("No migrations found.")
        return

    print(f"\n--- Applying {len(files)} migration(s) ---")
    for filename in files:
        filepath = os.path.join(MIGRATIONS_DIR, filename)
        sql = read_sql(filepath)
        print(f"\n  [{filename}] ({len(sql)} chars)")

        if args.dry_run:
            print(f"    {sql[:200]}...")
            continue

        if execute_via_supabase(sql):
            print(f"    Applied successfully.")
        else:
            print(f"    Could not apply via API. Run manually in Supabase SQL Editor:")
            print(f"    File: {filepath}")

    print("\nDone.")


if __name__ == "__main__":
    main()
