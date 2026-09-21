"""Branded operator-invite mail. Stdlib SMTP only; no Gmail OAuth client."""

from __future__ import annotations

import html
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from env_utils import env_bool, env_int, env_str

BRAND_BLUE = "#1868db"
TEXT = "#292a2e"
SUBTLE = "#505258"
SURFACE = "#f7f9fb"


def public_origin() -> str:
    return env_str("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")


def public_app_prefix() -> str:
    explicit = env_str("HABIBI_BASE").rstrip("/")
    if explicit:
        return explicit
    return "/app" if env_bool("HABIBI_DEPLOYED") else ""


def login_url() -> str:
    return f"{public_origin()}{public_app_prefix()}/login"


def landing_url() -> str:
    """Marketing site at the public origin. Console lives under HABIBI_BASE."""
    return f"{public_origin()}/"


def _asset(path: str) -> str:
    return f"{public_origin()}{public_app_prefix()}/{path.lstrip('/')}"


def render_invite(*, to_email: str, role_name: str, inviter_name: str | None) -> tuple[str, str, str]:
    """Return (subject, text, html) for one invite."""
    role = role_name.strip() or "Viewer"
    who = (inviter_name or "").strip() or "A PayInt admin"
    url = login_url()
    landing = landing_url()
    bee = _asset("videos/login-bee.jpg")
    mark = _asset("brand/bigtapp.png")
    subject = "You're invited to PayInt"
    text = (
        f"{who} invited you to PayInt as {role}.\n\n"
        f"Sign in with Microsoft using your @bigtapp.ai account:\n{url}\n\n"
        f"Product page:\n{landing}\n\n"
        "A Bigtapp product. Beeonix · PayInt.\n"
    )
    safe_role = html.escape(role)
    safe_who = html.escape(who)
    safe_url = html.escape(url, quote=True)
    safe_landing = html.escape(landing, quote=True)
    safe_bee = html.escape(bee, quote=True)
    safe_mark = html.escape(mark, quote=True)
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:{SURFACE};font-family:Inter,Segoe UI,Helvetica,Arial,sans-serif;color:{TEXT};">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{SURFACE};padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #dcdfe4;border-radius:8px;overflow:hidden;">
          <tr>
            <td style="padding:0;">
              <img src="{safe_bee}" alt="" width="560" style="display:block;width:100%;max-height:180px;object-fit:cover;">
            </td>
          </tr>
          <tr>
            <td style="padding:28px 32px 8px 32px;">
              <span style="display:inline-block;font-size:13px;color:{BRAND_BLUE};border:1px solid {BRAND_BLUE};border-radius:4px;padding:2px 8px;margin-right:8px;">Beeonix</span>
              <span style="font-size:20px;font-weight:600;color:{TEXT};vertical-align:middle;">PayInt</span>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 32px 0 32px;font-size:12px;letter-spacing:0.04em;text-transform:uppercase;color:{SUBTLE};">
              Autonomous Payment Intelligence
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 0 32px;font-size:22px;line-height:1.3;font-weight:600;">
              The floor is already working the book.
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 0 32px;font-size:15px;line-height:1.55;color:{SUBTLE};">
              {safe_who} invited you to sign in as <strong style="color:{TEXT};">{safe_role}</strong>.
              Use your @bigtapp.ai Microsoft account. This page does not collect a password.
            </td>
          </tr>
          <tr>
            <td style="padding:28px 32px;">
              <a href="{safe_url}" style="display:inline-block;background:{BRAND_BLUE};color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;padding:12px 20px;border-radius:6px;">Open PayInt</a>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 12px 32px;font-size:13px;color:{SUBTLE};">
              Or paste this sign-in link into a browser:<br>
              <a href="{safe_url}" style="color:{BRAND_BLUE};">{html.escape(url)}</a>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 28px 32px;font-size:13px;color:{SUBTLE};">
              Product page:<br>
              <a href="{safe_landing}" style="color:{BRAND_BLUE};">{html.escape(landing)}</a>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 24px 32px;border-top:1px solid #dcdfe4;font-size:12px;color:{SUBTLE};">
              <img src="{safe_mark}" alt="Bigtapp" height="18" style="height:18px;vertical-align:middle;margin-right:8px;">
              A Bigtapp product · Beeonix
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return subject, text, html_body


def smtp_configured() -> bool:
    return env_bool("SMTP_ENABLED") and bool(env_str("SMTP_HOST") and env_str("SMTP_USERNAME"))


def settings_url() -> str:
    return f"{public_origin()}{public_app_prefix()}/settings"


def render_access_request(
    *,
    requester_name: str,
    requester_email: str | None,
    page_path: str,
    permission_label: str | None,
    reason: str,
) -> tuple[str, str, str]:
    who = (requester_name or "").strip() or "An operator"
    email = (requester_email or "").strip()
    page = page_path.strip() or "/"
    perm = (permission_label or "").strip()
    why = reason.strip()
    url = settings_url()
    subject = f"PayInt access request from {who}"
    perm_line = f"Permission: {perm}\n" if perm else ""
    text = (
        f"{who} ({email or 'no email'}) asked for access to {page}.\n"
        f"{perm_line}"
        f"Reason:\n{why}\n\n"
        f"Review and grant a role:\n{url}\n"
    )
    safe_who = html.escape(who)
    safe_email = html.escape(email or "no email")
    safe_page = html.escape(page)
    safe_perm = html.escape(perm) if perm else ""
    safe_why = html.escape(why).replace("\n", "<br>")
    safe_url = html.escape(url, quote=True)
    perm_html = (
        f'<tr><td style="padding:8px 32px 0 32px;font-size:14px;color:{SUBTLE};">Permission: {safe_perm}</td></tr>'
        if safe_perm
        else ""
    )
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:{SURFACE};font-family:Inter,Segoe UI,Helvetica,Arial,sans-serif;color:{TEXT};">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{SURFACE};padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #dcdfe4;border-radius:8px;overflow:hidden;">
          <tr>
            <td style="padding:28px 32px 8px 32px;font-size:20px;font-weight:600;">Access request</td>
          </tr>
          <tr>
            <td style="padding:8px 32px 0 32px;font-size:15px;line-height:1.55;color:{SUBTLE};">
              <strong style="color:{TEXT};">{safe_who}</strong> ({safe_email}) asked for access to
              <strong style="color:{TEXT};">{safe_page}</strong>.
            </td>
          </tr>
          {perm_html}
          <tr>
            <td style="padding:16px 32px 0 32px;font-size:14px;line-height:1.55;color:{SUBTLE};">{safe_why}</td>
          </tr>
          <tr>
            <td style="padding:28px 32px;">
              <a href="{safe_url}" style="display:inline-block;background:{BRAND_BLUE};color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;padding:12px 20px;border-radius:6px;">Review in Settings</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return subject, text, html_body


def _deliver(*, to_email: str, subject: str, text: str, html_body: str) -> str | None:
    """Send one message. Returns None on success, or a short error token."""
    if not smtp_configured():
        return "smtp_disabled"
    from_email = env_str("SMTP_FROM_EMAIL") or env_str("SMTP_USERNAME")
    from_name = env_str("SMTP_FROM_NAME", "PayInt")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    host = env_str("SMTP_HOST")
    port = env_int("SMTP_PORT", 587)
    username = env_str("SMTP_USERNAME")
    password = env_str("SMTP_PASSWORD")
    try:
        if env_bool("SMTP_USE_SSL"):
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.sendmail(from_email, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.ehlo()
                if env_bool("SMTP_USE_TLS", True):
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                if username:
                    smtp.login(username, password)
                smtp.sendmail(from_email, [to_email], msg.as_string())
    except Exception:
        return "smtp_failed"
    return None


def send_invite_email(*, to_email: str, role_name: str, inviter_name: str | None) -> str | None:
    """Send the invite. Returns None on success, or a short error token."""
    subject, text, html_body = render_invite(
        to_email=to_email, role_name=role_name, inviter_name=inviter_name
    )
    return _deliver(to_email=to_email, subject=subject, text=text, html_body=html_body)


def send_access_request_email(
    *,
    to_email: str,
    requester_name: str,
    requester_email: str | None,
    page_path: str,
    permission_label: str | None,
    reason: str,
) -> str | None:
    subject, text, html_body = render_access_request(
        requester_name=requester_name,
        requester_email=requester_email,
        page_path=page_path,
        permission_label=permission_label,
        reason=reason,
    )
    return _deliver(to_email=to_email, subject=subject, text=text, html_body=html_body)


def send_dashboard_report_email(*, to_email: str, download_url: str, range_key: str) -> str | None:
    """Link to a ready dashboard CSV. Returns None on success, or a short error token."""
    window = (range_key or "30d").strip() or "30d"
    subject = f"PayInt dashboard export ({window})"
    text = (
        f"Your dashboard CSV for {window} is ready.\n\n"
        f"Download: {download_url}\n"
    )
    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;color:{TEXT}">
  <p>Your dashboard CSV for <strong>{html.escape(window)}</strong> is ready.</p>
  <p><a href="{html.escape(download_url)}" style="color:{BRAND_BLUE}">Download the CSV</a></p>
</body></html>
"""
    return _deliver(to_email=to_email, subject=subject, text=text, html_body=html_body)
