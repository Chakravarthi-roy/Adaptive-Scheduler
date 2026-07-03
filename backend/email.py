import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_USER     = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
APP_NAME       = "Scheduler"


def send_reset_email(to_email: str, reset_token: str, frontend_url: str):
    """Send a password reset link via Gmail SMTP."""
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("[email] GMAIL_USER or GMAIL_APP_PASSWORD not set — skipping email")
        return False

    reset_link = f"{frontend_url}/reset-password.html?token={reset_token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Reset your {APP_NAME} password"
    msg["From"]    = f"{APP_NAME} <{GMAIL_USER}>"
    msg["To"]      = to_email

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

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, to_email, msg.as_string())
        print(f"[email] reset email sent to {to_email}")
        return True
    except Exception as e:
        print(f"[email] failed to send: {e}")
        return False