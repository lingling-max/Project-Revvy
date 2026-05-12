import json
import os
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

ai_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = "You are Revvy, the AI Commercial Co-Pilot for a recruitment agency. You help Account Managers close deals, research leads, and calculate ROI. Be energetic, professional, and helpful!"

SUMMARISE_PROMPT = """You are Revvy, an AI assistant for a recruitment agency's leadership team.

Analyse the following meeting transcript and extract:
1. Meeting title (infer from context)
2. Attendees (names mentioned)
3. Key decisions made
4. Action items (each with owner name and deadline if mentioned)
5. A 3-5 sentence summary

Format your response EXACTLY like this:

📋 MEETING SUMMARY
──────────────────
📅 Date: {date}
👥 Attendees: [names separated by commas]

🧠 KEY DECISIONS
• [decision 1]
• [decision 2]

✅ ACTION ITEMS
• [Owner]: [action] → by [deadline or "ASAP" if not mentioned]

📝 SUMMARY
[3-5 sentence overview of what was discussed and decided]

— Posted by Revvy 🤖

Transcript:
{transcript}"""


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


def handle_summarise(transcript: str, sender_id: str, preview_mode: bool = False):
    today = datetime.now().strftime("%d %B %Y, %I:%M %p")
    prompt = SUMMARISE_PROMPT.format(date=today, transcript=transcript)

    try:
        response = ai_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024
        )
        summary = response.choices[0].message.content
    except Exception as e:
        send_lark_message(sender_id, f"Sorry, I couldn't process the transcript: {e}", "open_id")
        return

    if preview_mode:
        send_lark_message(sender_id, f"👀 PREVIEW (not posted to group yet):\n\n{summary}", "open_id")
        send_lark_message(sender_id, "Reply /confirm to post this to the Leader Group, or /discard to cancel.", "open_id")
    else:
        send_lark_message(LEADER_GROUP_CHAT_ID, summary)
        send_lark_message(sender_id, "✅ Meeting summary posted to the Leader Group!", "open_id")


def handle_message(data: P2ImMessageReceiveV1) -> None:
    msg_content = json.loads(data.event.message.content)
    # Strip @mentions from group messages
    user_text = msg_content.get("text", "").strip()
    for mention in msg_content.get("mentions", []):
        user_text = user_text.replace(mention.get("key", ""), "").strip()

    sender_id = data.event.sender.sender_id.open_id
    chat_id = data.event.message.chat_id
    print(f"Revvy heard: {user_text}")
    print(f"Chat ID: {chat_id}")

    # /summarise preview [transcript]
    if user_text.lower().startswith("/summarise preview "):
        transcript = user_text[len("/summarise preview "):].strip()
        if len(transcript) < 50:
            send_lark_message(sender_id, "⚠️ Transcript too short. Please paste the full meeting transcript after /summarise preview", "open_id")
        else:
            handle_summarise(transcript, sender_id, preview_mode=True)

    # /summarise [transcript]
    elif user_text.lower().startswith("/summarise "):
        transcript = user_text[len("/summarise "):].strip()
        if len(transcript) < 50:
            send_lark_message(sender_id, "⚠️ Transcript too short. Please paste the full meeting transcript after /summarise", "open_id")
        else:
            handle_summarise(transcript, sender_id, preview_mode=False)

    # /summarise with no transcript
    elif user_text.lower().strip() == "/summarise":
        send_lark_message(sender_id, "📌 How to use:\n\n/summarise [paste transcript here]\n\nOr to preview before posting:\n/summarise preview [paste transcript here]", "open_id")

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
    print("Revvy is connecting to Lark with Groq AI...")
    cli = lark.ws.Client(APP_ID, APP_SECRET, event_handler=event_handler, domain=lark.LARK_DOMAIN)
    cli.start()
