"""Check the SOS call to the emergency contact for real (Twilio), without an SOS: one test call, optionally one SMS.

The call says it is a TEST first, then reads the same text as a real SOS (core's templates, the cause included), two
times. Keys and numbers come from .env (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, EMERGENCY_NUMBER).

    .venv/Scripts/python scripts/sos_call_check.py            # one test call, prints the outcome
    .venv/Scripts/python scripts/sos_call_check.py --sms      # + one test SMS with the map link
    .venv/Scripts/python scripts/sos_call_check.py --voice Google.ro-RO-Standard-A   # try another voice

Make sure the person at EMERGENCY_NUMBER knows a test call is coming. Never put 112 there.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from core.settings import render, template, th  # noqa: E402
from integrations import twilio_call  # noqa: E402
from shared.contracts import Position, SosReport  # noqa: E402


def sample_report() -> SosReport:
    """A report like a real SOS: Andrei, microsleep at 110 km/h, Maria awake, 28 s without an answer."""
    now = datetime.now()
    cause = template("sos", "cause", "microsleep").format(driver_name="Andrei", speed_kmh=110)
    fields = {
        "driver_name": "Andrei", "unresponsive_s": 28, "occupants_n": 2, "cause": cause,
        "passenger_state_text": template("sos", "passenger_state", "awake"),
        "maps_url": render("links", "maps", lat=45.7489, lon=21.2087), "time_hhmm": now.strftime("%H:%M"),
    }
    test = "Acesta este un test DriveMate, nu o urgență reală. "
    return SosReport(driver_name="Andrei", unresponsive_s=28, occupants_n=2, passenger_state="awake",
                     pos=Position(lat=45.7489, lon=21.2087), maps_url=fields["maps_url"],
                     time_hhmm=fields["time_hhmm"], ts=now.timestamp(), cause=cause,
                     text="[TEST] " + render("sos", "sms", **fields),
                     call_text=test + render("sos", "call", **fields))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="One real test call (and SMS) to the emergency contact.")
    parser.add_argument("--sms", action="store_true", help="also send one test SMS")
    parser.add_argument("--voice", default=None, help="Twilio <Say> voice (default: sos.call_voice)")
    args = parser.parse_args()
    load_dotenv(REPO_ROOT / ".env", override=False)
    if not twilio_call.configured():
        print("Twilio is not set up: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, EMERGENCY_NUMBER in .env")
        return 2
    report = sample_report()
    print("The call will say:\n  " + report.call_text + "\n")
    voice = args.voice or str(th("sos", "call_voice"))
    print(f"Calling the emergency number (voice {voice}), waiting for the outcome ...")
    print("Call:", twilio_call.place_sos_call(report, voice=voice, repeat=int(th("sos", "call_repeat"))))
    if args.sms:
        print("SMS:", twilio_call.send_sos_sms(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
