import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import openai
import time

# Email configuration with hardcoded credentials
EMAIL_SENDER = "hope.aiv111@gmail.com"
EMAIL_PASSWORD = "beyqxmupdwkiohot"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Validate email configuration
if not EMAIL_SENDER or not EMAIL_PASSWORD:
    print("[Email Config Error] EMAIL_SENDER or EMAIL_PASSWORD are not set")
else:
    print(f"[Email Config] Loaded email credentials for sender: {EMAIL_SENDER}")

# In-memory state for email flow (key: session_id, value: {state, data, timestamp})
email_flow_state = {}

# Clean up old states (older than 5 minutes)
def cleanup_email_flow_state():
    current_time = time.time()
    expired_keys = [k for k, v in email_flow_state.items() if current_time - v["timestamp"] > 300]
    for key in expired_keys:
        del email_flow_state[key]
        print(f"[Email Flow] Cleared expired state for session_id: {key}")

def send_email(recipient: str, subject: str, message: str, tone: str = "neutral") -> str:
    """Send an email and return a styled response message."""
    email_pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    if not re.match(email_pattern, recipient):
        print(f"[Email Error] Invalid recipient email address: {recipient}")
        if tone == "casual":
            return f"⚠️ Yo, that email address ‘{recipient}’ doesn’t look right, fam! Try again? 🙂😉"
        elif tone == "genz":
            return f"⚠️ Yo fam, that email ‘{recipient}’ is sus—check it again! 😎🔥"
        elif tone == "professional":
            return f"⚠️ The email address ‘{recipient}’ is invalid. Please provide a valid address. 📌"
        elif tone == "friendly":
            return f"⚠️ Oops, that email address ‘{recipient}’ doesn’t look right! Could you check it? 😊🌟"
        elif tone == "playful":
            return f"⚠️ Whoops, that email ‘{recipient}’ isn’t quite right! Try again, silly! 😜🎉"
        elif tone == "sad":
            return f"⚠️ I’m sorry, that email address ‘{recipient}’ doesn’t seem valid. Could you try again? 😔🥺"
        return f"⚠️ Invalid email address: {recipient}"
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("[Email Error] Email credentials not configured")
        if tone == "casual":
            return "⚠️ My bad, fam—no email creds set up! Can’t send yet. 🙂😉"
        elif tone == "genz":
            return "⚠️ Yo, no email creds, fam! Can’t send this—fix it? 😎🔥"
        elif tone == "professional":
            return "⚠️ Email credentials are not configured. Please contact support. 📌"
        elif tone == "friendly":
            return "⚠️ Oh no, I don’t have email credentials set up! Can’t send yet. 😊🌟"
        elif tone == "playful":
            return "⚠️ Oopsie, no email setup—silly me! Can’t send yet! 😜🎉"
        elif tone == "sad":
            return "⚠️ I’m sorry, I don’t have email credentials set up to send this. 😔🥺"
        return "⚠️ Email credentials are not configured."
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = recipient
    msg['Subject'] = subject
    corrected_message = message.replace("tommorow", "tomorrow")
    msg.attach(MIMEText(corrected_message, 'plain'))
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, recipient, msg.as_string())
        server.quit()
        print(f"[Email] Successfully sent email to: {recipient}")
        if tone == "casual":
            return f"✅ Email sent to {recipient}, fam! What’s next? 🙂😉"
        elif tone == "genz":
            return f"✅ Yo, email sent to {recipient}! Straight fire, fam! What’s the vibe now? 😎🚀"
        elif tone == "professional":
            return f"✅ Email successfully sent to {recipient}. 📌"
        elif tone == "friendly":
            return f"✅ Email sent to {recipient}! Let me know what’s next! 😊🌟"
        elif tone == "playful":
            return f"✅ Woohoo, email sent to {recipient}! What fun thing we doing now? 😜🎉"
        elif tone == "sad":
            return f"✅ I sent the email to {recipient} for you. Hope it helps. 😔🥺"
        return f"✅ Email successfully sent to {recipient}!"
    except Exception as e:
        print(f"[Email Error] Failed to send email: {str(e)}")
        if tone == "casual":
            return f"⚠️ Oops, fam—couldn’t send the email: {str(e)}. Try again? 🙂😉"
        elif tone == "genz":
            return f"⚠️ Yo, something broke sending that email: {str(e)}. Let’s retry, fam! 😎🔥"
        elif tone == "professional":
            return f"⚠️ Failed to send email: {str(e)}. Please try again. 📌"
        elif tone == "friendly":
            return f"⚠️ Oh no, I couldn’t send the email: {str(e)}. Let’s try again! 😊🌟"
        elif tone == "playful":
            return f"⚠️ Whoops, the email didn’t send: {str(e)}! Let’s give it another go! 😜🎉"
        elif tone == "sad":
            return f"⚠️ I’m sorry, I couldn’t send the email: {str(e)}. Want to try again? 😔🥺"
        return f"⚠️ Failed to send email: {str(e)}"

def process_email_intent(prompt: str, session_id: str, openai_api_key: str) -> dict:
    """Process email-related intents and return a structured response."""
    openai.api_key = openai_api_key
    prompt_lower = prompt.lower().strip()
    cleanup_email_flow_state()
    email_intents = [
        "send email", "send an email", "email to", "shoot an email",
        "write an email", "compose email", "email", "mail to", "write me an email"
    ]
    cancel_keywords = ["cancel", "stop", "nevermind", "forget it"]
    if any(keyword in prompt_lower for keyword in cancel_keywords):
        if session_id in email_flow_state:
            del email_flow_state[session_id]
            print(f"[Email Flow] Canceled email flow for session_id: {session_id}")
        return {"reply": "Email flow canceled. What would you like to do next?", "draft": None}
    is_email_intent = any(intent in prompt_lower for intent in email_intents)
    if is_email_intent:
        print(f"[Email Flow] Detected email intent: {prompt}")
        email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
        email_match = re.search(email_pattern, prompt_lower)
        recipient = email_match.group(0) if email_match else None
        if session_id not in email_flow_state:
            email_flow_state[session_id] = {
                "state": "email_recipient_input",
                "data": {"initial_message": prompt},
                "timestamp": time.time()
            }
            print(f"[Email Flow] Set state to email_recipient_input for session_id: {session_id}")
            if recipient:
                email_flow_state[session_id]["data"]["recipient"] = recipient
                email_flow_state[session_id]["state"] = "email_message_input"
                return {
                    "reply": f"Got the recipient: {recipient}! What’s the email about? (e.g., ‘about a meeting tomorrow at 11 AM’)",
                    "draft": None
                }
            return {
                "reply": "Cool, let’s send an email! Who’s it going to? Give me an email address like ‘someone@example.com’.",
                "draft": None
            }
    if session_id in email_flow_state:
        state_data = email_flow_state[session_id]["data"]
        state = email_flow_state[session_id]["state"]
        if state == "email_recipient_input":
            email_pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
            email_match = re.search(email_pattern, prompt)
            if email_match:
                recipient = email_match.group(0)
                print(f"[Email Flow] Extracted recipient: {recipient} for session_id: {session_id}")
                state_data["recipient"] = recipient
                email_flow_state[session_id]["state"] = "email_message_input"
                email_flow_state[session_id]["timestamp"] = time.time()
                return {
                    "reply": f"Got the recipient: {recipient}! What’s the email about? (e.g., ‘about a meeting tomorrow at 11 AM’)",
                    "draft": None
                }
            else:
                return {
                    "reply": f"That doesn’t look like a valid email address. Please try again with something like ‘someone@example.com’.",
                    "draft": None
                }
        elif state == "email_message_input":
            state_data["message_content"] = prompt
            recipient = state_data.get("recipient")
            recipient_name = recipient.split("@")[0].capitalize()
            initial_message = state_data.get("initial_message", prompt)
            openai_prompt = (
                f"Generate a professional email draft based on the user’s request: '{initial_message}'. "
                f"If the request is vague, use the latest message: '{prompt}'. "
                f"Address it to {recipient_name} ({recipient}). "
                f"Include a subject, greeting, body, and closing, signed as Hope. "
                f"Keep it concise and professional, suitable for a hotel assistant."
            )
            try:
                response = openai.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are Hope, a helpful AI assistant. Generate a professional email draft with a subject, greeting, body, and closing."},
                        {"role": "user", "content": openai_prompt}
                    ],
                    max_tokens=200
                )
                email_draft = response.choices[0].message.content.strip()
                print(f"[Email Flow] Generated email draft: {email_draft}")
                subject_match = re.search(r"Subject:\s*(.+)", email_draft, re.IGNORECASE)
                if not subject_match:
                    raise ValueError("No subject found in OpenAI response")
                subject = subject_match.group(1).strip()
                message = email_draft[subject_match.end():].strip()
                if not message:
                    raise ValueError("No message body found in OpenAI response")
                state_data["subject"] = subject
                state_data["message"] = message
                email_flow_state[session_id] = {
                    "state": "email_draft_confirmation",
                    "data": state_data,
                    "timestamp": time.time()
                }
                print(f"[Email Flow] Set state to email_draft_confirmation for session_id: {session_id}")
                return {
                    "reply": f"Here’s the email draft. Is this okay? Say ‘yes’ to send, ‘cancel’ to stop, or suggest changes.",
                    "draft": {
                        "to": recipient,
                        "subject": subject,
                        "message": message
                    }
                }
            except Exception as e:
                print(f"[Email Flow] OpenAI error: {str(e)}")
                subject = f"Message from Hope about {initial_message}"
                message = f"Hello {recipient_name}, {prompt}. Best, Hope"
                state_data["subject"] = subject
                state_data["message"] = message
                email_flow_state[session_id] = {
                    "state": "email_draft_confirmation",
                    "data": state_data,
                    "timestamp": time.time()
                }
                print(f"[Email Flow] Set state to email_draft_confirmation with fallback draft for session_id: {session_id}")
                return {
                    "reply": f"Here’s the email draft (fallback due to OpenAI error). Is this okay? Say ‘yes’ to send, ‘cancel’ to stop, or suggest changes.",
                    "draft": {
                        "to": recipient,
                        "subject": subject,
                        "message": message
                    }
                }
        elif state == "email_draft_confirmation":
            if prompt_lower == "yes":
                print(f"[Email Flow] User confirmed draft for session_id: {session_id}")
                recipient = state_data.get("recipient")
                subject = state_data.get("subject")
                message = state_data.get("message")
                result = send_email(recipient, subject, message, tone="professional")
                del email_flow_state[session_id]
                print(f"[Email Flow] Cleared state for session_id: {session_id}")
                return {"reply": result, "draft": None}
            elif any(keyword in prompt_lower for keyword in cancel_keywords):
                del email_flow_state[session_id]
                print(f"[Email Flow] Canceled email flow for session_id: {session_id}")
                return {"reply": "Email flow canceled. What would you like to do next?", "draft": None}
            else:
                openai_prompt = (
                    f"Here’s an email draft:\n\n"
                    f"Subject: {state_data.get('subject')}\n\n"
                    f"{state_data.get('message')}\n\n"
                    f"The user requested a change: '{prompt}'. "
                    f"Modify the email accordingly, keeping it professional, with a subject, greeting, body, and closing, signed as Hope."
                )
                try:
                    response = openai.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": "You are Hope, a helpful AI assistant. Modify the email draft professionally with a subject, greeting, body, and closing."},
                            {"role": "user", "content": openai_prompt}
                        ],
                        max_tokens=200
                    )
                    email_draft = response.choices[0].message.content.strip()
                    print(f"[Email Flow] Modified email draft: {email_draft}")
                    subject_match = re.search(r"Subject:\s*(.+)", email_draft, re.IGNORECASE)
                    subject = subject_match.group(1).strip() if subject_match else state_data.get("subject")
                    message = email_draft[subject_match.end():].strip() if subject_match else state_data.get("message")
                    if not subject or not message:
                        subject = state_data.get("subject")
                        message = state_data.get("message")
                        print(f"[Email Flow] Reverted to original draft due to invalid OpenAI response")
                    state_data["subject"] = subject
                    state_data["message"] = message
                    email_flow_state[session_id]["timestamp"] = time.time()
                    return {
                        "reply": f"Here’s the updated email draft. Is this okay? Say ‘yes’ to send, ‘cancel’ to stop, or suggest more changes.",
                        "draft": {
                            "to": state_data.get("recipient"),
                            "subject": subject,
                            "message": message
                        }
                    }
                except Exception as e:
                    print(f"[Email Flow] OpenAI error: {str(e)}")
                    return {
                        "reply": f"Oops, I hit a snag updating the email draft: {str(e)}. Try again, say ‘yes’ to send, or ‘cancel’ to stop.",
                        "draft": {
                            "to": state_data.get("recipient"),
                            "subject": state_data.get("subject"),
                            "message": state_data.get("message")
                        }
                    }
    return {"reply": None, "draft": None}