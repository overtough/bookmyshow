import json
import os
import sys
import time
from datetime import datetime
import requests

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"


def load_config():
    """Load configuration from environment variables or config.json."""
    config = {
        "target_url": os.getenv("TARGET_URL"),
        "show_label": os.getenv("SHOW_LABEL"),
        "closed_text_signal": os.getenv("CLOSED_TEXT_SIGNAL"),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
        "poll_interval_minutes": int(os.getenv("POLL_INTERVAL_MINUTES", "5")),
        "run_mode": os.getenv("RUN_MODE", "once"),
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                for key, val in file_config.items():
                    if not config.get(key):
                        config[key] = val
        except Exception as e:
            print(f"[!] Warning: Could not read {CONFIG_FILE}: {e}")

    # Set defaults if missing
    if not config.get("target_url"):
        config["target_url"] = "https://in.bookmyshow.com/"
    if not config.get("show_label"):
        config["show_label"] = "BookMyShow Event"
    if not config.get("closed_text_signal"):
        config["closed_text_signal"] = "No showtimes available"

    return config


def load_state():
    """Load previous monitoring state."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Warning: Could not read {STATE_FILE}: {e}")
    return {"is_open": False, "last_checked": None, "last_status": "Unknown"}


def save_state(state):
    """Save current state to file."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[!] Error saving state to {STATE_FILE}: {e}")


def fetch_page_text(url):
    """
    Renders target URL via Playwright (or falls back to requests).
    Returns rendered page text / HTML.
    """
    print(f"[*] Fetching page: {url}")

    # Try Playwright first for Javascript rendering & anti-bot bypass
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            
            # Navigate and wait for domcontentloaded
            response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
            status_code = response.status if response else None
            print(f"[*] Playwright HTTP status: {status_code}")

            # Give dynamic React elements time to render
            page.wait_for_timeout(2500)

            content = page.content()
            text_content = page.evaluate("() => document.body.innerText")
            browser.close()

            return {"html": content, "text": text_content, "status": status_code}

    except Exception as e:
        print(f"[!] Playwright fetch failed: {e}. Trying requests fallback...")

    # Fallback to requests with custom headers
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        res = requests.get(url, headers=headers, timeout=15)
        return {"html": res.text, "text": res.text, "status": res.status_code}
    except Exception as err:
        print(f"[!] Requests fetch failed: {err}")
        return {"html": "", "text": "", "status": 0}


def check_is_open(fetch_res, closed_signal):
    """
    Decides if the show is open for booking.
    - Returns (is_open: bool, reason: str)
    """
    text = fetch_res.get("text", "")
    html = fetch_res.get("html", "")
    status = fetch_res.get("status", 0)

    if status in (403, 404, 500) and not text:
        return False, f"HTTP Error {status}"

    if not text and not html:
        return False, "Empty response"

    # Search for closed signal phrase (case-insensitive)
    signal_lower = closed_signal.lower()
    text_lower = text.lower()
    html_lower = html.lower()

    # Indicators of open showtimes on BookMyShow
    open_indicators = [
        "book seats",
        "select seats",
        "showtimes",
        "venue-list",
        "showtime-pill",
        "cinema-name",
        "btn-book",
    ]
    has_open_indicator = any(ind in html_lower for ind in open_indicators)

    if signal_lower in text_lower or signal_lower in html_lower:
        return False, f"Closed signal found: '{closed_signal}'"

    # Check if there are no cinemas listed or explicit no-showtime elements
    if "no showtimes" in text_lower or "no shows available" in text_lower or "no venues available" in text_lower:
        return False, "No showtimes found on page"

    if has_open_indicator:
        return True, "Open showtimes/booking indicator detected on page"

    # If closed signal not found and page rendered successfully
    return True, "Closed signal absent & page loaded successfully"


def send_telegram_alert(bot_token, chat_id, message):
    """Sends notification to Telegram."""
    if not bot_token or bot_token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("[!] Telegram bot token not configured. Skipping alert.")
        return False

    if not chat_id or chat_id == "YOUR_TELEGRAM_CHAT_ID":
        print("[!] Telegram chat ID not configured. Skipping alert.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        data = res.json()
        if data.get("ok"):
            print("[+] Telegram alert sent successfully!")
            return True
        else:
            print(f"[!] Telegram API error: {data}")
            return False
    except Exception as e:
        print(f"[!] Failed to send Telegram alert: {e}")
        return False


def send_gmail_alert(sender_email, app_password, receiver_email, subject, body_html):
    """Sends email notification via Gmail SMTP."""
    if not sender_email or not app_password or not receiver_email:
        print("[!] Gmail credentials not configured. Skipping email alert.")
        return False
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = receiver_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html"))

        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10)
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.close()
        print("[+] Gmail alert sent successfully!")
        return True
    except Exception as e:
        print(f"[!] Failed to send Gmail alert: {e}")
        return False


def send_whatsapp_alert(phone_number, api_key, message):
    """Sends WhatsApp message via free CallMeBot API."""
    if not phone_number or not api_key:
        print("[!] WhatsApp CallMeBot credentials not configured. Skipping WhatsApp alert.")
        return False
    try:
        import urllib.parse
        encoded_msg = urllib.parse.quote(message)
        url = f"https://api.callmebot.com/whatsapp.php?phone={phone_number}&text={encoded_msg}&apikey={api_key}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            print("[+] WhatsApp alert sent successfully!")
            return True
        else:
            print(f"[!] WhatsApp API status code {res.status_code}: {res.text}")
            return False
    except Exception as e:
        print(f"[!] Failed to send WhatsApp alert: {e}")
        return False


def send_discord_alert(webhook_url, message):
    """Sends message to a Discord Channel via Webhook."""
    if not webhook_url:
        print("[!] Discord Webhook URL not configured. Skipping Discord alert.")
        return False
    try:
        res = requests.post(webhook_url, json={"content": message}, timeout=10)
        if res.status_code in (200, 204):
            print("[+] Discord alert sent successfully!")
            return True
        else:
            print(f"[!] Discord Webhook error: status {res.status_code}")
            return False
    except Exception as e:
        print(f"[!] Failed to send Discord alert: {e}")
        return False


def send_twilio_whatsapp(account_sid, auth_token, from_number, to_number, message):
    """Sends WhatsApp message via official Twilio API."""
    if not account_sid or not auth_token or not from_number or not to_number:
        return False
    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        if not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number}"
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

        data = {"From": from_number, "To": to_number, "Body": message}
        res = requests.post(url, data=data, auth=(account_sid, auth_token), timeout=10)
        if res.status_code in (200, 201):
            print("[+] Twilio WhatsApp alert sent successfully!")
            return True
        else:
            print(f"[!] Twilio WhatsApp error: status {res.status_code} - {res.text}")
            return False
    except Exception as e:
        print(f"[!] Failed to send Twilio WhatsApp alert: {e}")
        return False


def send_green_api_whatsapp(instance_id, api_token, to_phone, message):
    """Sends WhatsApp message via Green API."""
    if not instance_id or not api_token or not to_phone:
        return False
    try:
        clean_phone = "".join(c for c in to_phone if c.isdigit())
        chat_id = f"{clean_phone}@c.us" if not clean_phone.endswith("@c.us") else clean_phone
        url = f"https://api.green-api.com/waInstance{instance_id}/sendMessage/{api_token}"
        payload = {"chatId": chat_id, "message": message}
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("[+] Green API WhatsApp alert sent successfully!")
            return True
        else:
            print(f"[!] Green API WhatsApp error: status {res.status_code} - {res.text}")
            return False
    except Exception as e:
        print(f"[!] Failed to send Green API WhatsApp alert: {e}")
        return False
import re

def load_config():
    """Load configuration from environment variables or config.json."""
    config = {
        "target_url": os.getenv("TARGET_URL"),
        "show_label": os.getenv("SHOW_LABEL"),
        "closed_text_signal": os.getenv("CLOSED_TEXT_SIGNAL"),
        "target_cinema": os.getenv("TARGET_CINEMA"),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
        "poll_interval_minutes": int(os.getenv("POLL_INTERVAL_MINUTES", "5")),
        "run_mode": os.getenv("RUN_MODE", "once"),
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                for key, val in file_config.items():
                    if not config.get(key):
                        config[key] = val
        except Exception as e:
            print(f"[!] Warning: Could not read {CONFIG_FILE}: {e}")

    # Set defaults if missing
    if not config.get("target_url"):
        config["target_url"] = "https://in.bookmyshow.com/"
    if not config.get("show_label"):
        config["show_label"] = "BookMyShow Event"
    if not config.get("closed_text_signal"):
        config["closed_text_signal"] = "No showtimes available"
    if config.get("target_cinema") is None:
        config["target_cinema"] = ""

    return config


def parse_cinema_showtimes(page_text, target_cinema=""):
    """
    Parses showtimes from rendered page text.
    If target_cinema is specified, extracts showtimes for that specific cinema.
    If empty, extracts all showtimes across all cinemas on the page.
    """
    lines = page_text.split("\n")
    time_pattern = re.compile(r"^(0?[1-9]|1[0-2]):[0-5][0-9]\s*(AM|PM)$", re.IGNORECASE)

    if not target_cinema:
        return [l.strip() for l in lines if time_pattern.match(l.strip())]

    found_cinema = False
    showtimes = []
    for i, line in enumerate(lines):
        line_clean = line.strip()
        if target_cinema.lower() in line_clean.lower():
            found_cinema = True
            continue

        if found_cinema:
            # Stop if we hit another cinema header or footer
            if ((":" in line_clean and not time_pattern.match(line_clean) and any(w in line_clean for w in ["Cinemas", "Multiplex", "PVR", "INOX", "70MM"])) or "Unable to find" in line_clean):
                break

            if time_pattern.match(line_clean):
                showtimes.append(line_clean)

    return showtimes


def run_check():
    """Runs a single check iteration."""
    config = load_config()
    state = load_state()

    url = config["target_url"]
    label = config["show_label"]
    closed_signal = config["closed_text_signal"]
    target_cinema = config.get("target_cinema", "")

    # Credentials
    bot_token = config.get("telegram_bot_token")
    chat_id = config.get("telegram_chat_id")

    gmail_user = config.get("gmail_sender_email") or os.getenv("GMAIL_SENDER_EMAIL")
    gmail_pass = config.get("gmail_app_password") or os.getenv("GMAIL_APP_PASSWORD")
    gmail_recv = config.get("gmail_receiver_email") or os.getenv("GMAIL_RECEIVER_EMAIL")

    wa_phone = config.get("whatsapp_phone") or os.getenv("WHATSAPP_PHONE")
    wa_apikey = config.get("whatsapp_apikey") or os.getenv("WHATSAPP_APIKEY")

    discord_webhook = config.get("discord_webhook_url") or os.getenv("DISCORD_WEBHOOK_URL")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cinema_desc = f" [{target_cinema}]" if target_cinema else ""
    print(f"\n[{now_str}] Checking availability for: {label}{cinema_desc}")

    fetch_res = fetch_page_text(url)
    page_text = fetch_res.get("text", "")

    # Extract showtimes
    current_showtimes = parse_cinema_showtimes(page_text, target_cinema)
    current_count = len(current_showtimes)

    if target_cinema:
        if current_count > 0:
            is_open = True
            reason = f"Found {current_count} showtime(s) for '{target_cinema}': {', '.join(current_showtimes)}"
        else:
            is_open = False
            reason = f"No showtimes listed yet for '{target_cinema}'"
    else:
        is_open, reason = check_is_open(fetch_res, closed_signal)

    was_open = state.get("is_open", False)
    prev_count = state.get("showtime_count", 0)
    prev_showtimes = state.get("showtimes", [])

    status_str = "OPEN" if is_open else "CLOSED"
    print(f"[*] Result: {status_str} ({reason})")

    # Save state with showtimes details
    state["is_open"] = is_open
    state["showtime_count"] = current_count
    state["showtimes"] = current_showtimes
    state["last_checked"] = now_str
    state["last_status"] = f"{status_str}: {reason}"
    save_state(state)

    # Trigger alert if:
    # 1. First time opening (closed -> open)
    # 2. Or new showtimes were added! (e.g. from 1 show to 3 shows)
    new_showtimes_added = is_open and (current_count > prev_count) and prev_count > 0

    if (is_open and not was_open) or new_showtimes_added:
        header = "🎉 NEW SHOWTIMES ADDED! 🎉" if new_showtimes_added else "🎉 TICKETS OPEN FOR BOOKING! 🎉"
        cinema_info = f"<b>Cinema:</b> {target_cinema}\n" if target_cinema else ""
        shows_str = ", ".join(current_showtimes) if current_showtimes else "N/A"

        alert_text = (
            f"{header}\n\n"
            f"Show: {label}\n"
            f"{f'Cinema: {target_cinema}' if target_cinema else ''}\n"
            f"Showtimes Available ({current_count}): {shows_str}\n"
            f"Link: {url}"
        )
        telegram_html = (
            f"<b>{header}</b>\n\n"
            f"<b>Show:</b> {label}\n"
            f"{cinema_info}"
            f"<b>Showtimes Available ({current_count}):</b> {shows_str}\n"
            f"<b>Link:</b> {url}"
        )
        email_html = (
            f"<h2>{header}</h2>"
            f"<p><b>Show:</b> {label}</p>"
            f"{f'<p><b>Cinema:</b> {target_cinema}</p>' if target_cinema else ''}"
            f"<p><b>Showtimes Available ({current_count}):</b> {shows_str}</p>"
            f"<p><b>Book Now:</b> <a href='{url}'>{url}</a></p>"
        )

        print(f"[+] Transition / New showtimes detected! Sending alerts...")

        # 1. Telegram
        if bot_token and chat_id and bot_token != "YOUR_TELEGRAM_BOT_TOKEN":
            send_telegram_alert(bot_token, chat_id, telegram_html)

        # 2. Gmail
        if gmail_user and gmail_pass and gmail_recv:
            send_gmail_alert(gmail_user, gmail_pass, gmail_recv, f"🎟️ {header} - {label}", email_html)

        # 3. WhatsApp (CallMeBot)
        if wa_phone and wa_apikey:
            send_whatsapp_alert(wa_phone, wa_apikey, alert_text)

        # 3b. WhatsApp (Twilio Official)
        twilio_sid = config.get("twilio_account_sid") or os.getenv("TWILIO_ACCOUNT_SID")
        twilio_token = config.get("twilio_auth_token") or os.getenv("TWILIO_AUTH_TOKEN")
        twilio_from = config.get("twilio_whatsapp_from") or os.getenv("TWILIO_WHATSAPP_FROM")
        twilio_to = config.get("twilio_whatsapp_to") or os.getenv("TWILIO_WHATSAPP_TO")
        if twilio_sid and twilio_token and twilio_from and twilio_to:
            send_twilio_whatsapp(twilio_sid, twilio_token, twilio_from, twilio_to, alert_text)

        # 3c. WhatsApp (Green API)
        green_instance = config.get("green_api_instance_id") or os.getenv("GREEN_API_INSTANCE_ID")
        green_token = config.get("green_api_token") or os.getenv("GREEN_API_TOKEN")
        green_to = config.get("green_api_to_phone") or os.getenv("GREEN_API_TO_PHONE")
        if green_instance and green_token and green_to:
            send_green_api_whatsapp(green_instance, green_token, green_to, alert_text)

        # 4. Discord Webhook
        if discord_webhook:
            send_discord_alert(discord_webhook, alert_text)

    elif is_open and was_open:
        print(f"[*] Show is still OPEN ({current_count} showtimes active: {', '.join(current_showtimes)}). No new showtimes added.")
    else:
        print("[*] Show is still CLOSED.")

    return is_open


def main():
    config = load_config()
    run_mode = config.get("run_mode", "once").lower()

    if run_mode == "once":
        run_check()
    elif run_mode == "loop":
        interval = config.get("poll_interval_minutes", 5)
        print(f"[*] Starting polling loop every {interval} minute(s). Press Ctrl+C to stop.")
        try:
            while True:
                run_check()
                time.sleep(interval * 60)
        except KeyboardInterrupt:
            print("\n[*] Stopping monitor.")
    else:
        print(f"[!] Unknown run_mode '{run_mode}'. Defaulting to 'once'.")
        run_check()


if __name__ == "__main__":
    main()
