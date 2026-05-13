import json
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from groq import Groq

load_dotenv()

APP_ID = os.environ["LARK_APP_ID"]
APP_SECRET = os.environ["LARK_APP_SECRET"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
LEADER_GROUP_CHAT_ID = os.environ["LEADER_GROUP_CHAT_ID"]
LARK_BASE_TOKEN = os.environ["LARK_BASE_TOKEN"]
LARK_PKR_TABLE_ID = os.environ["LARK_PKR_TABLE_ID"]

ai_client = Groq(api_key=GROQ_API_KEY)

# Deduplication — ignore messages already processed
_seen_message_ids = set()

SYSTEM_PROMPT = """You are Revvy, the AI Commercial Co-Pilot for AJobThing's recruitment agency.
You help leaders and Account Managers track performance, close deals, and stay on top of their pipeline.
Be sharp, direct, and helpful. When you have real PKR data, use it — never make up numbers."""

SUMMARISE_PROMPT = """You are Revvy, an AI assistant for a recruitment agency's leadership team.

Analyse the following meeting notes and extract a structured summary. Follow these rules strictly:
- PRESERVE all numbers, names, and figures exactly as written — never paraphrase or omit them
- If pipeline values are mentioned, list every team with their exact RM figure
- If PKR/performance hits are mentioned, list every name exactly
- For ACTION ITEMS: if none are explicitly stated, infer logical next steps from the context
- For ATTENTION: flag anyone with a significantly low number compared to peers, or any risk visible in the data

Format your response EXACTLY like this (only include sections that are relevant):

📋 MEETING SUMMARY
──────────────────
📅 Date: {date}
👥 Attendees: [names]

🏆 PKR HITS (if mentioned)
• [Team name]: [member names]

📊 PIPELINE SNAPSHOT (if pipeline numbers mentioned)
• [Team 1]: RM[amount]
• [Team 2]: RM[amount]
• [Team 3]: RM[amount]
(list every team, one line each, NO total after each line)
─────────────────
💰 Total Pipeline: RM[sum of ALL teams combined, calculated once at the bottom only]

⚠️ ATTENTION NEEDED
• [Name/Team]: [specific concern — e.g. lowest pipeline, at risk of missing target]

🧠 KEY DECISIONS
• [decision]

✅ ACTION ITEMS
• [Owner]: [action] → by [deadline or ASAP]

📝 SUMMARY
[3-5 sentences covering performance, risks, and what leaders should focus on]

— Posted by Revvy 🤖

Meeting notes:
{transcript}"""


# ── Lark Base API ──────────────────────────────────────────────────────────────

def get_tenant_token():
    """Get Lark tenant access token using app credentials."""
    resp = requests.post(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10
    )
    return resp.json().get("tenant_access_token")


def fetch_pkr_data(filter_week=None):
    """Fetch PKR records from Lark Base — one page only to stay fast."""
    token = get_tenant_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_PKR_TABLE_ID}/records",
        headers=headers,
        params={"page_size": 100},
        timeout=15
    )
    data = resp.json()

    if data.get("code") != 0:
        raise Exception(f"Lark Base API error: {data.get('msg', data)}")

    records = [item.get("fields", {}) for item in data.get("data", {}).get("items", [])]

    # Filter by week if specified
    if filter_week:
        records = [r for r in records if filter_week.upper() in str(r.get("Week", "")).upper()
                   or filter_week.upper() in str(r.get("Q2 Week", "")).upper()]

    return records


def get_field(record, key, default=""):
    """Safely extract a field from a Lark Base record, handling people/link objects."""
    val = record.get(key, default)
    if val is None:
        return default
    # People field: [{'en_name': 'Fauziah', 'id': '...', ...}]
    if isinstance(val, list):
        if len(val) == 0:
            return default
        first = val[0]
        if isinstance(first, dict):
            return first.get("en_name", first.get("name", str(first)))
        return str(first)
    return val


def format_pkr_summary(records):
    """Aggregate PKR records into a compact summary to stay within AI token limits."""
    if not records:
        return "No PKR data found."

    # Find the most recent week in the data
    weeks = [str(get_field(r, "Week") or get_field(r, "Q2 Week")) for r in records]
    weeks = [w for w in weeks if w.strip()]
    latest_week = sorted(set(weeks))[-1] if weeks else None

    # Filter to latest week only
    if latest_week:
        records = [r for r in records if str(get_field(r, "Week") or get_field(r, "Q2 Week")) == latest_week]

    lines = [f"PKR Data — Week: {latest_week or 'Latest'} | {len(records)} members\n"]
    for r in records:
        am = get_field(r, "AM Name", "Unknown")
        bu = get_field(r, "BU Name", "")
        pkr_pct = r.get("Primary PKR %") or r.get("Primary PKR") or ""

        try:
            target = float(r.get("Weekly Sales Target") or 0)
            projection = float(r.get("Projection Weekly") or 0)
            actual = float(r.get("Weekly Sales wo GST") or 0)
            gap = projection - target
            status = "✅" if gap >= 0 else "⚠️"
            gap_str = f"{status} {'above' if gap >= 0 else 'below'} by RM{abs(gap):,.0f}"
            line = (f"• {am} ({bu}) | Target: RM{target:,.0f} | "
                    f"Projection: RM{projection:,.0f} | Actual: RM{actual:,.0f} | {gap_str}")
        except Exception as e:
            line = f"• {am} ({bu}) | PKR: {pkr_pct} | (number parse error: {e})"

        lines.append(line)

    return "\n".join(lines)


# ── Messaging ──────────────────────────────────────────────────────────────────

def send_lark_message(chat_id: str, text: str, receive_id_type: str = "chat_id"):
    client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).domain(lark.LARK_DOMAIN).build()
    request = CreateMessageRequest.builder() \
        .receive_id_type(receive_id_type) \
        .request_body(CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()) \
        .build()
    client.im.v1.message.create(request)


# ── Handlers ───────────────────────────────────────────────────────────────────

def handle_summarise(transcript: str, sender_id: str, preview_mode: bool = False):
    today = datetime.now().strftime("%d %B %Y, %I:%M %p")
    prompt = SUMMARISE_PROMPT.format(date=today, transcript=transcript)

    try:
        response = ai_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500
        )
        summary = response.choices[0].message.content
    except Exception as e:
        send_lark_message(sender_id, f"Sorry, I couldn't process the transcript: {e}", "open_id")
        return

    if preview_mode:
        send_lark_message(sender_id, f"👀 PREVIEW (not posted to group yet):\n\n{summary}", "open_id")
        send_lark_message(sender_id, "Use /summarise [transcript] (without 'preview') to post to the Leader Group.", "open_id")
    else:
        send_lark_message(LEADER_GROUP_CHAT_ID, summary)
        send_lark_message(sender_id, f"✅ Posted to Leader Group! Here's what was sent:\n\n{summary}", "open_id")


def handle_pkr(user_text: str, sender_id: str):
    """Fetch PKR data and return Python-calculated results — no AI math."""
    send_lark_message(sender_id, "⏳ Pulling latest PKR data from Lark Base...", "open_id")

    try:
        # Detect week from message
        week_filter = None
        for word in user_text.split():
            if word.upper().startswith("W") and word[1:].isdigit():
                week_filter = word.upper()
                break

        records = fetch_pkr_data(filter_week=week_filter)
        if not records:
            send_lark_message(sender_id, "⚠️ No PKR records found.", "open_id")
            return

        # Get latest week label
        weeks = [str(get_field(r, "Week") or get_field(r, "Q2 Week")) for r in records]
        weeks = [w for w in weeks if w.strip()]
        latest_week = sorted(set(weeks))[-1] if weeks else "Latest"

        # Filter to latest week
        week_records = [r for r in records
                        if str(get_field(r, "Week") or get_field(r, "Q2 Week")) == latest_week]

        # Build rows with Python-calculated values only
        rows = []
        for r in week_records:
            am = get_field(r, "AM Name", "Unknown")
            bu = get_field(r, "BU Name", "")
            try:
                target = float(r.get("Weekly Sales Target") or 0)
                actual = float(r.get("Weekly Sales wo GST") or 0)
                # Use Lark's pre-calculated balance directly
                balance = float(r.get("Weekly Sales Balance") or (actual - target))
            except Exception:
                continue
            rows.append({"am": am, "bu": bu, "target": target,
                         "actual": actual, "balance": balance})

        # Sort by balance (most behind first)
        rows.sort(key=lambda x: x["balance"])

        query = user_text.lower()
        if "behind" in query or "below" in query or "missing" in query:
            # Only show people who are behind (negative balance)
            behind = [r for r in rows if r["balance"] < 0]
            if not behind:
                send_lark_message(sender_id, f"✅ Everyone is on or above target for {latest_week}!", "open_id")
                return
            lines = [f"⚠️ Behind on PKR — {latest_week} ({len(behind)} members)\n"]
            for r in behind:
                lines.append(f"• {r['am']} ({r['bu']}) | Target: RM{r['target']:,.0f} | "
                             f"Actual: RM{r['actual']:,.0f} | Gap: RM{abs(r['balance']):,.0f} short")

        elif "above" in query or "hit" in query or "hitting" in query or "champion" in query:
            # Only show people on or above target
            above = [r for r in rows if r["balance"] >= 0]
            if not above:
                send_lark_message(sender_id, f"⚠️ No one is above target for {latest_week} yet.", "open_id")
                return
            lines = [f"✅ Hitting PKR — {latest_week} ({len(above)} members)\n"]
            for r in above:
                lines.append(f"• {r['am']} ({r['bu']}) | Target: RM{r['target']:,.0f} | "
                             f"Actual: RM{r['actual']:,.0f} | Surplus: RM{r['balance']:,.0f}")

        else:
            # Show everyone
            lines = [f"📊 PKR Status — {latest_week} ({len(rows)} members)\n"]
            for r in rows:
                icon = "✅" if r["balance"] >= 0 else "⚠️"
                lines.append(f"{icon} {r['am']} ({r['bu']}) | Target: RM{r['target']:,.0f} | "
                             f"Actual: RM{r['actual']:,.0f} | Balance: RM{r['balance']:,.0f}")

        send_lark_message(sender_id, "\n".join(lines), "open_id")

    except Exception as e:
        print(f"PKR error: {e}")
        send_lark_message(sender_id, f"❌ Error: {e}", "open_id")


def extract_text(msg_content: dict, msg_type: str) -> str:
    if msg_type == "post":
        lines = []
        content = msg_content.get("content", [])
        for block in content:
            line_parts = []
            for item in block:
                if item.get("tag") == "text":
                    line_parts.append(item.get("text", ""))
                elif item.get("tag") == "at":
                    line_parts.append("")
            lines.append("".join(line_parts))
        return "\n".join(lines).strip()
    else:
        return msg_content.get("text", "").strip()


def handle_message(data: P2ImMessageReceiveV1) -> None:
    msg_content = json.loads(data.event.message.content)
    msg_type = data.event.message.message_type
    user_text = extract_text(msg_content, msg_type)

    if msg_type == "text":
        for mention in msg_content.get("mentions", []):
            user_text = user_text.replace(mention.get("key", ""), "").strip()

    # Deduplicate — skip if already processed
    message_id = data.event.message.message_id
    if message_id in _seen_message_ids:
        print(f"Skipping duplicate message: {message_id}")
        return
    _seen_message_ids.add(message_id)

    sender_id = data.event.sender.sender_id.open_id
    chat_id = data.event.message.chat_id
    print(f"[{msg_type}] Revvy heard: {user_text[:80]}")
    print(f"Chat ID: {chat_id}")

    # /summarise preview
    if user_text.lower().startswith("/summarise preview "):
        transcript = user_text[len("/summarise preview "):].strip()
        if len(transcript) < 50:
            send_lark_message(sender_id, "⚠️ Transcript too short. Please paste the full meeting notes.", "open_id")
        else:
            handle_summarise(transcript, sender_id, preview_mode=True)

    # /summarise
    elif user_text.lower().startswith("/summarise "):
        transcript = user_text[len("/summarise "):].strip()
        if len(transcript) < 50:
            send_lark_message(sender_id, "⚠️ Transcript too short. Please paste the full meeting notes.", "open_id")
        else:
            handle_summarise(transcript, sender_id, preview_mode=False)

    elif user_text.lower().strip() == "/summarise":
        send_lark_message(sender_id, "📌 Usage:\n/summarise [paste meeting notes]\n/summarise preview [paste meeting notes]", "open_id")

    # /debug — show raw Lark Base response
    elif user_text.lower().strip() == "/debug":
        try:
            token = get_tenant_token()
            send_lark_message(sender_id, f"✅ Tenant token: {token[:20]}...", "open_id")
            records = fetch_pkr_data()
            if records:
                sample = records[0]
                send_lark_message(sender_id, f"✅ Got {len(records)} records\nFirst record keys: {list(sample.keys())}\nSample: {str(sample)[:300]}", "open_id")
            else:
                send_lark_message(sender_id, "⚠️ No records returned from Lark Base", "open_id")
        except Exception as e:
            send_lark_message(sender_id, f"❌ Error: {e}", "open_id")

    # /pkr — query live PKR data from Lark Base
    elif user_text.lower().startswith("/pkr"):
        handle_pkr(user_text, sender_id)

    # General chat
    else:
        try:
            response = ai_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}
                ]
            )
            reply_text = response.choices[0].message.content
        except Exception as e:
            reply_text = f"Oops, my AI brain had a hiccup: {e}"
            print(e)

        send_lark_message(sender_id, reply_text, "open_id")


event_handler = lark.EventDispatcherHandler.builder("", "") \
    .register_p2_im_message_receive_v1(handle_message) \
    .build()

if __name__ == "__main__":
    print("Revvy is connecting to Lark with Groq AI + Lark Base...")
    cli = lark.ws.Client(APP_ID, APP_SECRET, event_handler=event_handler, domain=lark.LARK_DOMAIN)
    cli.start()
