"""
Email Service — sends transactional emails via Resend.

Provides verification emails, welcome emails, and deadline reminders.
Graceful degradation: if RESEND_API_KEY is not set, all methods are
no-ops and return False. This keeps dev mode working without an email
provider.
"""

import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Thin wrapper around the Resend SDK for transactional emails."""

    def __init__(self):
        self._client = None
        if settings.RESEND_API_KEY:
            try:
                import resend
                resend.api_key = settings.RESEND_API_KEY
                self._client = resend
                logger.info("Resend email service initialized.")
            except ImportError:
                logger.warning("resend package not installed — emails disabled.")
        else:
            logger.info("RESEND_API_KEY not set — emails disabled (dev mode).")

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _send(self, to: str, subject: str, html: str) -> Optional[str]:
        """Send an email. Returns the Resend message ID or None on failure."""
        if not self.enabled:
            return None
        try:
            result = self._client.Emails.send({
                "from": settings.SENDER_EMAIL,
                "to": [to],
                "subject": subject,
                "html": html,
            })
            msg_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
            logger.info(f"Email sent to {to[:4]}****: subject={subject!r} id={msg_id}")
            return msg_id
        except Exception as e:
            logger.error(f"Failed to send email to {to[:4]}****: {e}")
            return None

    # ------------------------------------------------------------------
    # Verification email
    # ------------------------------------------------------------------
    def send_verification_email(self, user_email: str, code: str) -> Optional[str]:
        """Send the 6-digit verification code to the user."""
        dashboard_url = f"{settings.FRONTEND_URL}/dashboard.html"
        return self._send(
            to=user_email,
            subject="Verify your Niyam AI account",
            html=f"""
            <div style="font-family:sans-serif; max-width:480px; margin:0 auto;">
                <h2 style="color:#1e293b;">Welcome to Niyam AI!</h2>
                <p>Your verification code is:</p>
                <div style="font-size:32px; font-weight:700; letter-spacing:8px;
                            text-align:center; padding:20px; background:#f1f5f9;
                            border-radius:8px; margin:16px 0;">
                    {code}
                </div>
                <p style="color:#64748b; font-size:14px;">
                    Enter this code on the verification page. It expires in 10 minutes.
                </p>
                <p style="color:#64748b; font-size:14px;">
                    If you didn't create an account, you can safely ignore this email.
                </p>
                <hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">
                <p style="color:#94a3b8; font-size:12px;">
                    Niyam AI &mdash; GST/TDS/ROC compliance for Indian MSMEs
                </p>
            </div>
            """,
        )

    # ------------------------------------------------------------------
    # Welcome email (after verification)
    # ------------------------------------------------------------------
    def send_welcome_email(self, user_email: str, user_name: str) -> Optional[str]:
        """Send a getting-started email after the user verifies their account."""
        dashboard_url = f"{settings.FRONTEND_URL}/dashboard.html"
        return self._send(
            to=user_email,
            subject="You're in! Getting started with Niyam AI",
            html=f"""
            <div style="font-family:sans-serif; max-width:480px; margin:0 auto;">
                <h2 style="color:#1e293b;">Hi {user_name},</h2>
                <p>Your Niyam AI account is verified and ready to go!</p>
                <p><strong>Here's how to get started:</strong></p>
                <ol style="line-height:1.8;">
                    <li>Upload your first invoice (PDF or image)</li>
                    <li>Review extracted GST and ITC details</li>
                    <li>Check your compliance health score</li>
                    <li>Export your filing-ready report</li>
                </ol>
                <a href="{dashboard_url}"
                   style="display:inline-block; padding:12px 28px; background:#2563eb;
                          color:white; text-decoration:none; border-radius:8px;
                          font-weight:600; margin:16px 0;">
                    Go to Dashboard &rarr;
                </a>
                <hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">
                <p style="color:#94a3b8; font-size:12px;">
                    Niyam AI &mdash; GST/TDS/ROC compliance for Indian MSMEs
                </p>
            </div>
            """,
        )

    # ------------------------------------------------------------------
    # Deadline reminder
    # ------------------------------------------------------------------
    def send_deadline_reminder(
        self, user_email: str, deadline_name: str, days_left: int
    ) -> Optional[str]:
        """Send a compliance deadline reminder."""
        urgency = "URGENT: " if days_left <= 1 else ""
        dashboard_url = f"{settings.FRONTEND_URL}/dashboard.html"
        return self._send(
            to=user_email,
            subject=f"{urgency}{deadline_name} due in {days_left} day{'s' if days_left != 1 else ''}",
            html=f"""
            <div style="font-family:sans-serif; max-width:480px; margin:0 auto;">
                <h2 style="color:#1e293b;">Compliance Deadline Approaching</h2>
                <p><strong>{deadline_name}</strong> is due in
                   <strong>{days_left} day{'s' if days_left != 1 else ''}</strong>.</p>
                <a href="{dashboard_url}"
                   style="display:inline-block; padding:12px 28px; background:#2563eb;
                          color:white; text-decoration:none; border-radius:8px;
                          font-weight:600; margin:16px 0;">
                    Review Compliance Status
                </a>
                <hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">
                <p style="color:#94a3b8; font-size:12px;">
                    Niyam AI &mdash; GST/TDS/ROC compliance for Indian MSMEs
                </p>
            </div>
            """,
        )


    # ------------------------------------------------------------------
    # Subscription emails
    # ------------------------------------------------------------------
    def send_plan_upgrade_email(self, user_email: str, plan: str) -> Optional[str]:
        """Confirm successful plan upgrade."""
        dashboard_url = f"{settings.FRONTEND_URL}/dashboard.html"
        return self._send(
            to=user_email,
            subject=f"You're now on Niyam AI {plan.capitalize()}!",
            html=f"""
            <div style="font-family:sans-serif; max-width:480px; margin:0 auto;">
                <h2 style="color:#1e293b;">Plan Upgraded to {plan.capitalize()}</h2>
                <p>Your Niyam AI subscription is now active. You have full access
                   to all {plan.capitalize()} features.</p>
                <a href="{dashboard_url}"
                   style="display:inline-block; padding:12px 28px; background:#2563eb;
                          color:white; text-decoration:none; border-radius:8px;
                          font-weight:600; margin:16px 0;">
                    Go to Dashboard &rarr;
                </a>
                <hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">
                <p style="color:#94a3b8; font-size:12px;">
                    Niyam AI &mdash; GST/TDS/ROC compliance for Indian MSMEs
                </p>
            </div>
            """,
        )

    def send_password_reset_email(self, user_email: str, code: str) -> Optional[str]:
        """Send the 6-digit password reset code to the user."""
        reset_url = f"{settings.FRONTEND_URL}/forgot-password.html?email={user_email}"
        return self._send(
            to=user_email,
            subject="Reset your Niyam AI password",
            html=f"""
            <div style="font-family:sans-serif; max-width:480px; margin:0 auto;">
                <h2 style="color:#1e293b;">Reset Your Password</h2>
                <p>Use this code to reset your Niyam AI password:</p>
                <div style="font-size:32px; font-weight:700; letter-spacing:8px;
                            text-align:center; padding:20px; background:#f1f5f9;
                            border-radius:8px; margin:16px 0;">
                    {code}
                </div>
                <p style="color:#64748b; font-size:14px;">
                    This code expires in 10 minutes.
                    <a href="{reset_url}" style="color:#4a40e0;">Click here to open the reset page.</a>
                </p>
                <p style="color:#64748b; font-size:14px;">
                    If you didn't request a password reset, you can safely ignore this email.
                </p>
                <hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">
                <p style="color:#94a3b8; font-size:12px;">
                    Niyam AI &mdash; GST/TDS/ROC compliance for Indian MSMEs
                </p>
            </div>
            """,
        )

    def send_plan_downgrade_email(self, user_email: str) -> Optional[str]:
        """Notify user their subscription expired / was cancelled."""
        dashboard_url = f"{settings.FRONTEND_URL}/dashboard.html"
        return self._send(
            to=user_email,
            subject="Your Niyam AI Pro subscription has ended",
            html=f"""
            <div style="font-family:sans-serif; max-width:480px; margin:0 auto;">
                <h2 style="color:#1e293b;">Subscription Ended</h2>
                <p>Your Niyam AI Pro subscription has expired or been cancelled.
                   You've been moved back to the Free plan.</p>
                <p>To continue using Pro features, please renew your subscription.</p>
                <a href="{dashboard_url}"
                   style="display:inline-block; padding:12px 28px; background:#2563eb;
                          color:white; text-decoration:none; border-radius:8px;
                          font-weight:600; margin:16px 0;">
                    Renew Subscription
                </a>
                <hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">
                <p style="color:#94a3b8; font-size:12px;">
                    Niyam AI &mdash; GST/TDS/ROC compliance for Indian MSMEs
                </p>
            </div>
            """,
        )


# Singleton — initialized once at import time
email_service = EmailService()
