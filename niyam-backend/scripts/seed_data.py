#!/usr/bin/env python3
"""
Data Seeder — create initial data for a fresh Niyam AI deployment.

Usage:
    python scripts/seed_data.py                # Seed deadlines for current year
    python scripts/seed_data.py --demo-user    # Also create a demo user + business

Seeds statutory deadlines (GST, TDS, ROC) for the current year.
Optionally creates a demo user for testing.
"""

import os
import sys
import uuid
import logging
from datetime import date, datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def seed_deadlines_for_business(db, is_mock, business_id):
    """Seed all statutory deadlines for the current year."""
    from app.services.rules.deadline_rules import generate_deadlines_for_year

    current_year = date.today().year
    all_deadlines = generate_deadlines_for_year(current_year)
    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for dl in all_deadlines:
        dl["id"] = str(uuid.uuid4())
        dl["business_id"] = business_id
        dl["status"] = "upcoming"
        dl["filed_at"] = None
        dl["created_at"] = now

        if is_mock:
            db.upsert_deadline(dl)
        else:
            db.table("deadlines").insert(dl).execute()
        count += 1

    logger.info(f"Seeded {count} deadlines for business {business_id[:8]}... (year {current_year})")
    return count


def create_demo_user(db, is_mock):
    """Create a demo user and business for testing."""
    from app.utils.security import hash_password

    user_id = str(uuid.uuid4())
    business_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    email = "demo@niyam.ai"
    password = "demo12345"

    business = {
        "id": business_id,
        "user_id": user_id,
        "legal_name": "Demo MSME Pvt Ltd",
        "trade_name": "Demo MSME Pvt Ltd",
        "gstin": "29ABCDE1234F1Z5",
        "pan": "ABCDE1234F",
        "business_type": "Proprietorship",
        "address": "123 Demo Street, Bangalore, Karnataka - 560001",
        "state_code": "29",
        "created_at": now,
    }

    user = {
        "id": user_id,
        "email": email,
        "hashed_password": hash_password(password),
        "full_name": "Demo User",
        "phone": "+91 98765 43210",
        "business_id": business_id,
        "email_verified": True,
        "created_at": now,
        "last_login": None,
    }

    if is_mock:
        # Check if demo user exists
        existing = db.get_user_by_email(email)
        if existing:
            logger.info(f"Demo user already exists: {email}")
            return existing.get("business_id")

        db.create_business(business)
        db.create_user(user)
    else:
        # Check if exists
        resp = db.table("users").select("id, business_id").eq("email", email).execute()
        if resp.data:
            logger.info(f"Demo user already exists: {email}")
            return resp.data[0].get("business_id")

        db.table("businesses").insert(business).execute()
        db.table("users").insert(user).execute()

    logger.info(f"Created demo user: {email} / {password}")
    logger.info(f"  User ID: {user_id}")
    logger.info(f"  Business ID: {business_id}")
    return business_id


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Niyam AI Data Seeder")
    parser.add_argument("--demo-user", action="store_true", help="Create a demo user + business")
    parser.add_argument("--mock", action="store_true", help="Force MockDB (development)")
    args = parser.parse_args()

    from app.config import settings

    if args.mock or settings.ENVIRONMENT != "production":
        from app.utils.mock_db import MockDB
        db = MockDB()
        is_mock = True
        logger.info("Using MockDB (development mode)")
    else:
        from app.database import get_db_client
        db = get_db_client()
        if not db:
            logger.error("Supabase client not available. Check SUPABASE_URL/SUPABASE_KEY.")
            sys.exit(1)
        is_mock = False
        logger.info("Using Supabase (production mode)")

    if args.demo_user:
        business_id = create_demo_user(db, is_mock)
        if business_id:
            seed_deadlines_for_business(db, is_mock, business_id)
    else:
        # Seed for all existing businesses
        if is_mock:
            import json
            businesses_file = os.path.join("data", "businesses.json")
            if os.path.exists(businesses_file):
                with open(businesses_file) as f:
                    businesses = json.load(f)
                for biz in businesses:
                    seed_deadlines_for_business(db, is_mock, biz["id"])
                if not businesses:
                    logger.info("No businesses found. Use --demo-user to create one.")
            else:
                logger.info("No businesses found. Use --demo-user to create one.")
        else:
            resp = db.table("businesses").select("id").execute()
            businesses = resp.data or []
            for biz in businesses:
                seed_deadlines_for_business(db, is_mock, biz["id"])
            if not businesses:
                logger.info("No businesses found. Use --demo-user to create one.")

    logger.info("Seeding complete.")


if __name__ == "__main__":
    main()
