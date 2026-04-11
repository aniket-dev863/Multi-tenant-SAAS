import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date, timedelta
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ── Alert thresholds (days remaining) ──
CRITICAL_DAYS = 7
WARNING_DAYS  = 15
WATCH_DAYS    = 30
LOOKBACK_DAYS = 30  # calculate burn rate over last 30 days


def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )


def calculate_burn_rates(pharmacy_id):
    """
    For every medicine in this pharmacy:
      1. Sum units sold in the last LOOKBACK_DAYS days
      2. Calculate burn_rate_per_day
      3. Calculate days_remaining from current total stock
      4. Assign alert_level
      5. Upsert into burn_rate_log
    Returns list of dicts for all medicines that have stock or sales.
    """
    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # All medicines for this pharmacy with their current total stock
    cur.execute("""
        SELECT
            m.medicine_id,
            m.name,
            COALESCE(SUM(b.quantity), 0) AS current_stock
        FROM medicines m
        LEFT JOIN batches b ON b.medicine_id = m.medicine_id
        WHERE m.pharmacy_id = %s
        GROUP BY m.medicine_id, m.name
        ORDER BY m.name
    """, (pharmacy_id,))
    medicines = cur.fetchall()

    results = []

    for med in medicines:
        med_id        = med['medicine_id']
        med_name      = med['name']
        current_stock = int(med['current_stock'])

        # Units sold in last LOOKBACK_DAYS days for this medicine
        cur.execute("""
            SELECT COALESCE(SUM(si.quantity), 0) AS units_sold
            FROM sale_items si
            JOIN batches b   ON si.batch_id   = b.batch_id
            JOIN medicines m ON b.medicine_id  = m.medicine_id
            JOIN sales s     ON si.sale_id     = s.sale_id
            WHERE m.medicine_id = %s
              AND s.pharmacy_id = %s
              AND s.sale_date  >= CURRENT_DATE - INTERVAL '%s days'
        """, (med_id, pharmacy_id, LOOKBACK_DAYS))
        units_sold = float(cur.fetchone()['units_sold'])

        # Burn rate = units sold per day
        burn_rate = round(units_sold / LOOKBACK_DAYS, 4) if units_sold > 0 else 0.0

        # Days remaining
        if burn_rate > 0:
            days_remaining = round(current_stock / burn_rate, 1)
        else:
            days_remaining = None  # no sales data — can't predict

        # Predicted stockout date
        if days_remaining is not None:
            predicted_date = date.today() + timedelta(days=days_remaining)
        else:
            predicted_date = None

        # Alert level
        if days_remaining is None or burn_rate == 0:
            alert_level = 'ok'
        elif days_remaining <= CRITICAL_DAYS:
            alert_level = 'critical'
        elif days_remaining <= WARNING_DAYS:
            alert_level = 'warning'
        elif days_remaining <= WATCH_DAYS:
            alert_level = 'watch'
        else:
            alert_level = 'ok'

        # Upsert into burn_rate_log
        # Delete today's existing log for this medicine, then insert fresh
        cur.execute("""
            DELETE FROM burn_rate_log
            WHERE medicine_id = %s
              AND pharmacy_id = %s
              AND DATE(calculated_at) = CURRENT_DATE
        """, (med_id, pharmacy_id))

        cur.execute("""
            INSERT INTO burn_rate_log
                (medicine_id, pharmacy_id, burn_rate_per_day, current_stock,
                 days_remaining, predicted_stockout_date, alert_level)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            med_id, pharmacy_id, burn_rate, current_stock,
            days_remaining, predicted_date, alert_level
        ))

        results.append({
            'medicine_id':            med_id,
            'name':                   med_name,
            'current_stock':          current_stock,
            'burn_rate_per_day':      burn_rate,
            'units_sold_30d':         int(units_sold),
            'days_remaining':         days_remaining,
            'predicted_stockout_date': predicted_date,
            'alert_level':            alert_level,
        })

    conn.commit()
    cur.close()
    conn.close()

    return results


def get_admin_email(pharmacy_id):
    """Fetch the email of the admin user for this pharmacy."""
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
    SELECT email FROM users
    WHERE pharmacy_id = %s AND role = 'admin'
    AND email IS NOT NULL AND email != ''
    LIMIT 1
""", (pharmacy_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def get_pharmacy_name(pharmacy_id):
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("SELECT name FROM pharmacies WHERE id = %s", (pharmacy_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else 'Your Pharmacy'


def build_email_html(pharmacy_name, alerts):
    """Build a clean HTML email body."""
    critical = [a for a in alerts if a['alert_level'] == 'critical']
    warning  = [a for a in alerts if a['alert_level'] == 'warning']
    watch    = [a for a in alerts if a['alert_level'] == 'watch']

    def row_color(level):
        return {'critical': '#fde8e8', 'warning': '#fef3c7', 'watch': '#e1f5ee'}.get(level, '#fff')

    def badge_style(level):
        styles = {
            'critical': 'background:#991b1b;color:#fff;',
            'warning':  'background:#92400e;color:#fff;',
            'watch':    'background:#065f46;color:#fff;',
        }
        return styles.get(level, '')

    rows_html = ''
    for a in alerts:
        if a['alert_level'] == 'ok':
            continue
        days = f"{a['days_remaining']} days" if a['days_remaining'] is not None else 'N/A'
        date_str = str(a['predicted_stockout_date']) if a['predicted_stockout_date'] else 'Unknown'
        rows_html += f"""
        <tr style="background:{row_color(a['alert_level'])};">
            <td style="padding:10px 14px;font-weight:700;color:#1a3a2e;">{a['name']}</td>
            <td style="padding:10px 14px;text-align:center;">{a['current_stock']}</td>
            <td style="padding:10px 14px;text-align:center;">{a['burn_rate_per_day']}/day</td>
            <td style="padding:10px 14px;text-align:center;font-weight:700;">{days}</td>
            <td style="padding:10px 14px;text-align:center;">{date_str}</td>
            <td style="padding:10px 14px;text-align:center;">
                <span style="padding:3px 8px;border-radius:20px;font-size:11px;font-weight:700;{badge_style(a['alert_level'])}">
                    {a['alert_level'].upper()}
                </span>
            </td>
        </tr>"""

    if not rows_html:
        return None  # nothing to alert about

    html = f"""
    <html><body style="font-family:'Nunito',Arial,sans-serif;background:#f0faf6;padding:24px;">
    <div style="max-width:680px;margin:0 auto;background:#fff;border-radius:14px;
                border:1px solid #e8f5f0;overflow:hidden;">

        <!-- Header -->
        <div style="background:#1a7a5e;padding:20px 28px;">
            <h1 style="color:#fff;font-size:18px;margin:0;">
                Stock Alert — {pharmacy_name}
            </h1>
            <p style="color:#9fe1cb;font-size:12px;margin:6px 0 0;">
                Burn rate analysis · {date.today().strftime('%d %b %Y')}
            </p>
        </div>

        <!-- Summary pills -->
        <div style="display:flex;gap:12px;padding:16px 28px;border-bottom:1px solid #f0faf6;flex-wrap:wrap;">
            <span style="background:#fde8e8;color:#991b1b;padding:5px 12px;
                         border-radius:20px;font-size:12px;font-weight:700;">
                🔴 Critical: {len(critical)}
            </span>
            <span style="background:#fef3c7;color:#92400e;padding:5px 12px;
                         border-radius:20px;font-size:12px;font-weight:700;">
                🟡 Warning: {len(warning)}
            </span>
            <span style="background:#d4f1e6;color:#065f46;padding:5px 12px;
                         border-radius:20px;font-size:12px;font-weight:700;">
                🟢 Watch: {len(watch)}
            </span>
        </div>

        <!-- Table -->
        <div style="padding:0 0 20px;">
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead>
                    <tr style="background:#f8fffe;">
                        <th style="padding:10px 14px;text-align:left;color:#94a3b8;
                                   font-size:10px;text-transform:uppercase;letter-spacing:.6px;">Medicine</th>
                        <th style="padding:10px 14px;text-align:center;color:#94a3b8;
                                   font-size:10px;text-transform:uppercase;">Stock</th>
                        <th style="padding:10px 14px;text-align:center;color:#94a3b8;
                                   font-size:10px;text-transform:uppercase;">Burn Rate</th>
                        <th style="padding:10px 14px;text-align:center;color:#94a3b8;
                                   font-size:10px;text-transform:uppercase;">Days Left</th>
                        <th style="padding:10px 14px;text-align:center;color:#94a3b8;
                                   font-size:10px;text-transform:uppercase;">Stockout Date</th>
                        <th style="padding:10px 14px;text-align:center;color:#94a3b8;
                                   font-size:10px;text-transform:uppercase;">Status</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>

        <!-- Footer -->
        <div style="background:#f8fffe;padding:14px 28px;border-top:1px solid #e8f5f0;">
            <p style="font-size:11px;color:#94a3b8;margin:0;">
                This alert was generated automatically by Pharmacy MS.
                Log in to restock medicines before the predicted stockout date.
            </p>
        </div>
    </div>
    </body></html>
    """
    return html


def send_alert_email(to_email, pharmacy_name, alerts):
    """Send the alert email via Gmail SMTP."""
    sender   = os.getenv("ALERT_EMAIL_SENDER")
    password = os.getenv("ALERT_EMAIL_PASSWORD")

    if not sender or not password:
        print("Email credentials not set in .env — skipping email.")
        return False, "Email credentials not configured."

    html_body = build_email_html(pharmacy_name, alerts)
    if not html_body:
        return False, "No alerts to send — all stock levels are healthy."

    critical_count = sum(1 for a in alerts if a['alert_level'] == 'critical')
    subject = f"🔴 {critical_count} Critical Stock Alert(s) — {pharmacy_name}" \
              if critical_count > 0 else f"⚠️ Stock Alert — {pharmacy_name}"

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = sender
    msg['To']      = to_email
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, password)
            server.sendmail(sender, to_email, msg.as_string())
        print(f"Alert email sent to {to_email}")
        return True, f"Email sent to {to_email}"
    except Exception as e:
        print(f"Email send failed: {e}")
        return False, str(e)


def run_analysis_and_alert(pharmacy_id):
    """
    Full pipeline:
      1. Calculate burn rates
      2. Get admin email
      3. Send alert if any critical/warning/watch items exist
    Returns (results, email_status_message)
    """
    results       = calculate_burn_rates(pharmacy_id)
    pharmacy_name = get_pharmacy_name(pharmacy_id)
    admin_email   = get_admin_email(pharmacy_id)

    alertable = [r for r in results if r['alert_level'] in ('critical', 'warning', 'watch')]

    if not alertable:
        return results, "All stock levels are healthy. No email sent."

    if not admin_email:
        return results, "No admin user found for this pharmacy. No email sent."

    ok, msg = send_alert_email(admin_email, pharmacy_name, alertable)
    return results, msg