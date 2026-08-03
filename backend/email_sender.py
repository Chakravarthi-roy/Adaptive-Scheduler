import os
import requests

# ─── Resend (https://resend.com) — HTTP API, not SMTP ───────────────────────
# Replaces the old Gmail SMTP sender. No app password, no 2FA dance, no
# Google flagging Render's server IP as suspicious. Free tier: 3,000
# emails/month, 100/day, permanent (not a trial), no credit card required.
#
# IMPORTANT: until a custom domain is verified in the Resend dashboard
# (resend.com/domains — still free, just needs a domain you own + a couple
# DNS records), the default RESEND_FROM_EMAIL below can only deliver to the
# email address the Resend ACCOUNT ITSELF was signed up with — not to your
# app's actual users. That's a sandbox restriction Resend enforces to stop
# spam abuse, not a paywall. Fine for testing the flow end-to-end right now;
# verify a domain before relying on this for real password resets.
RESEND_API_KEY    = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
RESEND_API_URL    = "https://api.resend.com/emails"
APP_NAME          = "Scheduler"


def send_reset_email(to_email: str, reset_token: str, frontend_url: str):
    """Send a password reset link via Resend's HTTP API."""
    if not RESEND_API_KEY:
        print("[email] RESEND_API_KEY not set — skipping email")
        return False

    reset_link = f"{frontend_url}/reset-password.html?token={reset_token}"

    text = f"""Hi,

Someone requested a password reset for your {APP_NAME} account.

Reset your password here:
{reset_link}

This link expires in 30 minutes. If you didn't request this, ignore this email.

— {APP_NAME}"""

    html = f"""<div style="font-family:'DM Sans',sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;color:#4a3520">
  <h2 style="font-family:'Playfair Display',serif;color:#dda15e;margin-bottom:8px">{APP_NAME}</h2>
  <p style="margin-bottom:24px;color:#8a7260;font-size:14px">Password reset request</p>
  <p style="margin-bottom:24px;font-size:15px;line-height:1.6">
    Someone requested a password reset for your account. If this was you, click the button below.
  </p>
  <a href="{reset_link}"
     style="display:inline-block;padding:12px 28px;background:#dda15e;color:#fefae0;border-radius:12px;text-decoration:none;font-weight:600;font-size:14px;margin-bottom:24px">
    Reset password
  </a>
  <p style="font-size:12px;color:#8a7260;line-height:1.5">
    This link expires in 30 minutes.<br>
    If you didn't request this, you can safely ignore this email.
  </p>
</div>"""

    return _send(to_email, f"Reset your {APP_NAME} password", html, text)


def send_otp_email(to_email: str, code: str):
    """Send the signup verification code."""
    if not RESEND_API_KEY:
        print("[email] RESEND_API_KEY not set — skipping email")
        return False

    text = f"""Hi,

Your {APP_NAME} verification code is:

{code}

This code expires in 10 minutes. If you didn't try to sign up, ignore this email.

— {APP_NAME}"""

    html = f"""<div style="font-family:'DM Sans',sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;color:#4a3520">
  <h2 style="font-family:'Playfair Display',serif;color:#dda15e;margin-bottom:8px">{APP_NAME}</h2>
  <p style="margin-bottom:24px;color:#8a7260;font-size:14px">Verify your email</p>
  <p style="margin-bottom:20px;font-size:15px;line-height:1.6">
    Enter this code to finish creating your account:
  </p>
  <div style="font-family:'DM Mono',monospace;font-size:32px;font-weight:600;letter-spacing:0.15em;color:#dda15e;background:rgba(221,161,94,0.08);border-radius:12px;padding:16px 20px;text-align:center;margin-bottom:24px">
    {code}
  </div>
  <p style="font-size:12px;color:#8a7260;line-height:1.5">
    This code expires in 10 minutes.<br>
    If you didn't try to sign up, you can safely ignore this email.
  </p>
</div>"""

    return _send(to_email, f"Your {APP_NAME} verification code", html, text)


def _send(to_email: str, subject: str, html: str, text: str) -> bool:
    """Shared Resend API call — used by send_reset_email above and by
    send_otp_email (added when OTP verification, BACKLOG.md #7, is built)."""
    try:
        res = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from": f"{APP_NAME} <{RESEND_FROM_EMAIL}>",
                "to": [to_email],
                "subject": subject,
                "html": html,
                "text": text
            },
            timeout=10
        )
        if res.status_code >= 400:
            print(f"[email] Resend API error {res.status_code}: {res.text}")
            return False
        print(f"[email] sent to {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"[email] failed to send: {e}")
        return False