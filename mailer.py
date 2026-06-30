import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

MAIL_HOST = os.environ.get("MAIL_HOST", "")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "2525"))
MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "orders@example.com")


def mail_is_configured():
    return bool(MAIL_HOST and MAIL_USERNAME and MAIL_PASSWORD)


def send_order_confirmation_email(to_email, order, items, status_url):
    """
    Sends an HTML order confirmation email. Returns (success: bool, error: str|None)
    so the calling route can show a sensible message instead of crashing if
    mail isn't configured or the send fails.
    """
    if not mail_is_configured():
        return False, "Email is not configured (MAIL_HOST/MAIL_USERNAME/MAIL_PASSWORD missing)."

    lines = "".join(
        f"<tr><td style='padding:6px 0;'>{it['quantity']} x {it['name']}</td>"
        f"<td style='padding:6px 0; text-align:right;'>${it['price_cents']*it['quantity']/100:,.2f}</td></tr>"
        for it in items
    )
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
      <h2 style="color:#251710;">Thanks for your order, order #{order['id']}</h2>
      <p>We've received your order and it's being prepared.</p>
      <table style="width:100%; border-collapse:collapse; margin: 16px 0;">
        {lines}
        <tr><td style="padding-top:10px; font-weight:bold; border-top:1px solid #ddd;">Total</td>
            <td style="padding-top:10px; font-weight:bold; text-align:right; border-top:1px solid #ddd;">
              ${order['total_cents']/100:,.2f}
            </td></tr>
      </table>
      <p>
        <a href="{status_url}" style="background:#c08a3e; color:#251710; padding:10px 18px;
           text-decoration:none; border-radius:4px; font-weight:bold;">Track your order</a>
      </p>
      <p style="color:#777; font-size:13px;">If the button doesn't work, copy this link: {status_url}</p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Order confirmation #{order['id']}"
    msg["From"] = MAIL_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(MAIL_HOST, MAIL_PORT, timeout=10) as server:
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_FROM, [to_email], msg.as_string())
        return True, None
    except Exception as exc:  # noqa: BLE001 - surface any SMTP error to the caller
        return False, str(exc)
