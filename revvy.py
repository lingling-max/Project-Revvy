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
        json={"app_id": APP_ID, "app_secret": APP_SECRET}
    )
    return resp.json().get("tenant_access_token")


def fetch_pkr_data(filter_week=None):
    """Fetch PKR records from Lark Base. Optionally filter by week label."""
    token = get_tenant_token()
    headers = {"Authorization": f"Bearer {token}"}
    records = []
    page_token = None

    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_PKR_TABLE_ID}/records",
            headers=headers,
            params=params
        )
        data = resp.json()

        if data.get("code") != 0:
            print(f"Lark Base error: {data}")
            break

        items = data.get("data", {}).get("items", [])
        for item in items:
            fields = item.get("fields", {})
            records.append(fields)

        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")

    # Filter by week if specified
    if filter_week:
        records = [r for r in records if filter_week.lower() in str(r.get("Week", "")).lower()
                   or filter_week.lower() in str(r.get("Q2 Week", "")).lower()]

    return records


def format_pkr_summary(records):
    """Format PKR records into a readable summary for AI context."""
    if not records:
        return "No PKR data found."

    lines = []
    for r in records:
        am = r.get("AM Name", "Unknown")
        bu = r.get("BU Name", "")
        target = r.get("Weekly Sales Target", "")
        projection = r.get("Projection Weekly", "")
        actual = r.get("Weekly Sales wo GST", "")
        balance = r.get("Weekly Sales Balan...", r.get("Weekly Sales Balance", ""))
        pkr = r.get("Primary PKR", "")
        week = r.get("Week", r.get("Q2 Week", ""))

        lines.append(f"- {am} ({bu}) | Week: {week} | PKR: {pkr} | Target: {target} | Projection: {projection} | Actual: {actual} | Balance: {balance}")

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
    """Fetch PKR data and answer questions about it."""
    send_lark_message(sender_id, "⏳ Pulling latest PKR data from Lark Base...", "open_id")

    # Try to detect week from message
    week_filter = None
    for word in user_text.split():
        if word.upper().startswith("W") and word[1:].isdigit():
            week_filter = word.upper()
            break

    records = fetch_pkr_data(filter_week=week_filter)
    pkr_text = format_pkr_summary(records)

    prompt = f"""You are Revvy, AI Co-Pilot for a recruitment agency.
Here is the latest PKR data from Lark Base:

{pkr_text}

User asked: {user_text}

Answer their question using the real data above. Be specific — name names, quote numbers.
If someone is at risk or behind, flag it clearly with ⚠️.
Format your answer cleanly for a Lark chat message."""

    try:
        response = ai_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000
        )
        reply = response.choices[0].message.content
    except Exception as e:
        reply = f"Error querying AI: {e}"

    send_lark_message(sender_id, reply, "open_id")


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
