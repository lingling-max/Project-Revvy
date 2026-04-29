import json
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
import openai
# --- PUT YOUR SECRET CODES HERE ---
APP_ID = "cli_a96593b684b85ed4"
APP_SECRET = "REDACTED"
# --- OPENAI KEY GOES HERE ---
OPENAI_API_KEY = "sk-YOUR_COPIED_KEY_HERE"
# Connect to OpenAI
ai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
# This handles the incoming message
def handle_message(data: P2ImMessageReceiveV1) -> None:
    # Read what they said
    msg_content = json.loads(data.event.message.content)
    user_text = msg_content.get("text", "")
    sender_id = data.event.sender.sender_id.open_id
    print(f"Revvy heard: {user_text}")
    # Ask OpenAI to generate the response
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are Revvy, the AI Commercial Co-Pilot for a recruitment agency. You help Account Managers close deals, research leads, and calculate ROI. Be energetic, professional, and helpful!"},
                {"role": "user", "content": user_text}
            ]
        )
        reply_text = response.choices[0].message.content
    except Exception as e:
        reply_text = f"Oops, my AI brain had a hiccup: {e}"
        print(e)
    
    # Send the reply back to Lark
    client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).domain(lark.LARK_DOMAIN).build()
    request = CreateMessageRequest.builder() \
        .receive_id_type("open_id") \
        .request_body(CreateMessageRequestBody.builder()
            .receive_id(sender_id)
            .msg_type("text")
            .content(json.dumps({"text": reply_text}))
            .build()) \
        .build()
    
    client.im.v1.message.create(request)
# This connects Revvy directly to Lark's servers
event_handler = lark.EventDispatcherHandler.builder("", "") \
    .register_p2_im_message_receive_v1(handle_message) \
    .build()
if __name__ == "__main__":
    print("Revvy is connecting to Global Lark with ChatGPT...")
    cli = lark.ws.Client(APP_ID, APP_SECRET, event_handler=event_handler, domain=lark.LARK_DOMAIN)
    cli.start()