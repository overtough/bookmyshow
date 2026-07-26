# BookMyShow Ticket Availability Watcher

Automated tool to monitor BookMyShow movie showtimes and notify via **Telegram**, **Gmail**, **WhatsApp**, or **Discord** the instant tickets open for booking or new showtimes are added.

---

## WhatsApp Notification Alternatives

In addition to CallMeBot, `main.py` supports official and dedicated WhatsApp API services:

### 1. 🟢 Green API (Recommended - Free Tier Available)
Links to your own WhatsApp account via QR code and sends up to 1,000 free messages per month.

**Setup Steps:**
1. Register at [green-api.com](https://green-api.com/).
2. Create an instance and scan the QR code using your phone's WhatsApp (`Linked Devices`).
3. Copy your `idInstance` and `apiTokenInstance`.
4. In `config.json` set:
   ```json
   "green_api_instance_id": "1101234567",
   "green_api_token": "abc123xyz...",
   "green_api_to_phone": "919876543210"
   ```

---

### 2. 🔴 Twilio API for WhatsApp (Official & High Reliability)
Uses Twilio's official WhatsApp Sandbox. Includes a free trial credit ($15 credit).

**Setup Steps:**
1. Create a free account at [twilio.com](https://www.twilio.com/).
2. Navigate to **Messaging > Try it out > Send a WhatsApp message** to activate the WhatsApp Sandbox.
3. Follow the instructions to send `join <sandbox-code>` from your phone to Twilio's WhatsApp number (`+1 415 523 8886`).
4. Copy your `Account SID` and `Auth Token` from the Twilio Console.
5. In `config.json` set:
   ```json
   "twilio_account_sid": "ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
   "twilio_auth_token": "your_auth_token",
   "twilio_whatsapp_from": "whatsapp:+14155238886",
   "twilio_whatsapp_to": "whatsapp:+919876543210"
   ```

---

### 3. 📞 CallMeBot (100% Free - Personal Bot)
Send `I allow callmebot to send me messages` on WhatsApp to `+34 644 51 95 03` to get your API key.
In `config.json` set:
```json
"whatsapp_phone": "+919876543210",
"whatsapp_apikey": "123456"
```

---

## Other Supported Channels
- **Gmail (SMTP)**: Set `gmail_sender_email`, `gmail_app_password`, `gmail_receiver_email`.
- **Discord Webhooks**: Set `discord_webhook_url`.
- **Telegram Bot**: Set `telegram_bot_token`, `telegram_chat_id`.
