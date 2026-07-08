"""Publishing: static dashboard (GitHub Pages / docs/) + daily email digest."""
import datetime as dt
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Environment, FileSystemLoader

_env = Environment(
    loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
    autoescape=True)


def _pretty(date_str):
    try:
        return dt.date.fromisoformat(date_str).strftime("%A, %B %-d, %Y")
    except ValueError:
        return date_str


def render_site(days, base_ctx, out_dir="docs"):
    """Render one page per day (docs/d/<date>.html) + index.html = latest day.

    `days`: [(date_str, daily_dict)] any order. `base_ctx`: shared context.
    """
    os.makedirs(os.path.join(out_dir, "d"), exist_ok=True)
    open(os.path.join(out_dir, ".nojekyll"), "w").close()
    ordered = sorted(dict(days).items())  # oldest -> newest, deduped
    all_dates = [d for d, _ in ordered]
    tpl = _env.get_template("dashboard.html.j2")
    for i, (day, daily) in enumerate(ordered):
        ctx = dict(base_ctx)
        ctx.update(
            date=day, pretty_date=_pretty(day),
            signals=daily.get("signals", []), watchlist=daily.get("watchlist", []),
            provider=daily.get("provider", base_ctx.get("provider", "?")),
            source_status=daily.get("source_status"),
            note=daily.get("note"),
            all_dates=all_dates,
            prev_date=all_dates[i - 1] if i > 0 else None,
            next_date=all_dates[i + 1] if i < len(all_dates) - 1 else None,
            is_latest=(i == len(all_dates) - 1),
        )
        with open(os.path.join(out_dir, "d", f"{day}.html"), "w", encoding="utf-8") as f:
            f.write(tpl.render(day_prefix="", **ctx))
        if ctx["is_latest"]:
            with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
                f.write(tpl.render(day_prefix="d/", **ctx))
    return os.path.join(out_dir, "index.html")


def render_email(context):
    return _env.get_template("email.html.j2").render(**context)


def send_email(html, subject, out_dir="data/out"):
    """Send via Gmail SMTP (free) if configured; always saves a copy to disk."""
    os.makedirs(out_dir, exist_ok=True)
    copy = os.path.join(out_dir, f"email-{dt.date.today().isoformat()}.html")
    with open(copy, "w", encoding="utf-8") as f:
        f.write(html)

    addr = os.environ.get("GMAIL_ADDRESS")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("DIGEST_TO") or addr
    if not (addr and pw):
        return False, "email not configured (GMAIL_ADDRESS / GMAIL_APP_PASSWORD unset); saved to " + copy

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"The Curiosity Engine <{addr}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                              context=ssl.create_default_context()) as s:
            s.login(addr, pw)
            s.sendmail(addr, [t.strip() for t in to.split(",")], msg.as_string())
        return True, f"sent to {to}"
    except Exception as exc:  # noqa: BLE001 - never crash the run over email
        return False, f"send failed: {exc}; saved to {copy}"
