"""Set up and check the SOS on Telegram for real, without an SOS (integrations/telegram_alert.py).

1. Make the bot: in Telegram, @BotFather -> /newbot -> put the token in .env as TELEGRAM_BOT_TOKEN.
2. The emergency contact opens the bot and presses Start (or writes anything to it). Then:

       .venv/Scripts/python scripts/telegram_check.py --chat-id     # prints the chats -> TELEGRAM_CHAT_ID in .env

3. For the call: the contact sets a Telegram @username, sends /start to @CallMeBot_txtbot once, and the @username goes
   in .env as TELEGRAM_CALL_USER.
4. Check (everything says it is a TEST first):

       .venv/Scripts/python scripts/telegram_check.py               # the SOS message: text + map pin + voice note
       .venv/Scripts/python scripts/telegram_check.py --call        # + the Telegram call that reads the state

The texts are the same as a real SOS (core's templates, the cause included).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dotenv import load_dotenv  # noqa: E402

from core.safety.channels import call_text_short  # noqa: E402
from core.settings import th  # noqa: E402
from integrations import telegram_alert  # noqa: E402
from sos_call_check import sample_report  # noqa: E402

TEST = "[TEST DriveMate, nu e o urgență reală] "


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Set up and check the SOS on Telegram.")
    parser.add_argument("--chat-id", action="store_true", help="print the chats that wrote to the bot")
    parser.add_argument("--call", action="store_true", help="also place the Telegram call (CallMeBot)")
    args = parser.parse_args()
    load_dotenv(REPO_ROOT / ".env", override=False)

    if args.chat_id:
        if not (telegram_alert._env("TELEGRAM_BOT_TOKEN")):
            print("TELEGRAM_BOT_TOKEN is missing from .env")
            return 2
        try:
            found = telegram_alert.chats()
        except Exception as exc:
            print("getUpdates failed:", telegram_alert._clean(exc))
            return 1
        if not found:
            print("No chat yet: open the bot in Telegram, press Start (or write anything), then run this again.")
        for chat in found:
            print(f"TELEGRAM_CHAT_ID={chat['id']}    ({chat['name']}, @{chat['username'] or '-'})")
        return 0

    report = sample_report()
    report = report.model_copy(update={"text": TEST + report.text.removeprefix("[TEST] "),
                                       "call_text": report.call_text})
    if telegram_alert.bot_configured():
        print("Message:\n  " + report.text + "\n")
        print("Message (text + map pin + voice note):", telegram_alert.send_sos_message(report))
    else:
        print("Message: not set up (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)")
    if args.call:
        if not telegram_alert.call_configured():
            print("Call: not set up (TELEGRAM_CALL_USER in .env)")
            return 2
        text = "Test DriveMate. " + call_text_short(report)
        print("Call will say:\n  " + telegram_alert.short_text(text) + "\n")
        print("Call:", telegram_alert.place_call(text, lang=str(th("sos", "telegram_call_lang")),
                                                  repeat=int(th("sos", "call_repeat"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
