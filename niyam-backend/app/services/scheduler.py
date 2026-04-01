"""
Deadline Reminder Scheduler — daily cron job at 8 AM IST.

Checks all compliance deadlines across all users and sends email reminders
at 7, 3, and 1 days before the due date. Uses reminder_logs to prevent
duplicate sends on the same day.

Requires APScheduler. Graceful no-op if email service is disabled.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Send reminders at these intervals before the deadline
REMINDER_DAYS = {7, 3, 1}

IST_TIMEZONE = "Asia/Kolkata"


class DeadlineScheduler:
    """Background scheduler for daily deadline reminder emails."""

    def __init__(self):
        self._scheduler = None

    def start(self):
        """Start the background scheduler with cron triggers."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            self._scheduler = BackgroundScheduler(timezone=IST_TIMEZONE)

            # Daily 8 AM IST — deadline reminder emails
            self._scheduler.add_job(
                func=self.send_deadline_reminders,
                trigger="cron",
                hour=8,
                minute=0,
                id="deadline_reminders",
                replace_existing=True,
            )

            # Weekly Sunday 2 AM IST — storage cleanup
            self._scheduler.add_job(
                func=self._run_storage_cleanup,
                trigger="cron",
                day_of_week="sun",
                hour=2,
                minute=0,
                id="storage_cleanup",
                replace_existing=True,
            )

            self._scheduler.start()
            logger.info("Scheduler started: deadline reminders (daily 8AM), storage cleanup (Sun 2AM).")
        except ImportError:
            logger.warning("APScheduler not installed — scheduled jobs disabled.")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")

    @staticmethod
    def _run_storage_cleanup():
        """Run the storage cleanup job (separate static method for APScheduler)."""
        try:
            from app.services.storage import storage_service
            storage_service.cleanup_old_documents()
        except Exception as e:
            logger.error(f"Storage cleanup job failed: {e}")

    def shutdown(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("Deadline reminder scheduler stopped.")

    # ------------------------------------------------------------------
    # Core job: scan deadlines and send reminders
    # ------------------------------------------------------------------
    def send_deadline_reminders(self):
        """
        Scan all deadlines, send emails for those due in 7/3/1 days.
        Called by APScheduler or manually for testing.
        """
        from app.services.email_service import email_service

        if not email_service.enabled:
            logger.debug("Email service disabled — skipping deadline reminders.")
            return

        today = date.today()
        today_str = today.isoformat()

        try:
            db, is_mock = _get_db()
        except Exception as e:
            logger.error(f"Scheduler: failed to get DB: {e}")
            return

        # Fetch all deadlines
        if is_mock:
            deadlines = db.get_all_deadlines()
        else:
            try:
                resp = db.table("deadlines").select("*").execute()
                deadlines = resp.data or []
            except Exception:
                try:
                    resp = db.table("compliance_deadlines").select("*").execute()
                    deadlines = resp.data or []
                except Exception as e:
                    logger.error(f"Scheduler: failed to fetch deadlines: {e}")
                    return

        # Build a user lookup (id → {email, full_name})
        user_lookup = _build_user_lookup(db, is_mock)

        sent_count = 0
        for dl in deadlines:
            if dl.get("status") == "completed":
                continue

            due_date = _parse_date(dl.get("due_date"))
            if not due_date:
                continue

            days_left = (due_date - today).days
            if days_left not in REMINDER_DAYS:
                continue

            dl_id = dl.get("id", "")
            business_id = dl.get("business_id", "")

            # Check if already sent today
            if _already_sent(db, is_mock, dl_id, today_str):
                continue

            # Find the user for this business
            user = _find_user_for_business(user_lookup, business_id)
            if not user or not user.get("email"):
                continue

            # Build deadline name
            dl_name = dl.get("subtype") or dl.get("description") or dl.get("type", "Deadline")

            # Send the reminder
            msg_id = email_service.send_deadline_reminder(user["email"], dl_name, days_left)
            if msg_id:
                _record_sent(db, is_mock, dl_id, today_str)
                sent_count += 1

        if sent_count:
            logger.info(f"Scheduler: sent {sent_count} deadline reminder(s).")


# ------------------------------------------------------------------
# Helpers (module-level to keep the class focused)
# ------------------------------------------------------------------

def _get_db():
    if settings.ENVIRONMENT != "production":
        from app.utils.mock_db import MockDB
        return MockDB(), True
    else:
        from app.database import get_db_client
        client = get_db_client()
        if not client:
            raise RuntimeError("Database unavailable")
        return client, False


def _build_user_lookup(db, is_mock: bool) -> dict:
    """Return {user_id: {email, full_name, business_id}} for all users."""
    if is_mock:
        users = db.get_all_users()
    else:
        try:
            resp = db.table("users").select("id,email,full_name,business_id").execute()
            users = resp.data or []
        except Exception:
            users = []
    return {u["id"]: u for u in users if u.get("id")}


def _find_user_for_business(user_lookup: dict, business_id: str) -> Optional[dict]:
    for u in user_lookup.values():
        if u.get("business_id") == business_id:
            return u
    return None


def _parse_date(val) -> Optional[date]:
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except (ValueError, TypeError):
            return None
    return None


def _already_sent(db, is_mock: bool, deadline_id: str, today_str: str) -> bool:
    if is_mock:
        return db.reminder_was_sent(deadline_id, today_str)
    else:
        try:
            resp = (
                db.table("reminder_logs")
                .select("id")
                .eq("deadline_id", deadline_id)
                .eq("sent_date", today_str)
                .execute()
            )
            return bool(resp.data)
        except Exception:
            return False


def _record_sent(db, is_mock: bool, deadline_id: str, today_str: str):
    if is_mock:
        db.log_reminder_sent(deadline_id, today_str)
    else:
        try:
            db.table("reminder_logs").insert({
                "deadline_id": deadline_id,
                "sent_date": today_str,
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to log reminder: {e}")


# Singleton
deadline_scheduler = DeadlineScheduler()
