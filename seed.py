"""
Seed the local SQLite database with two tenant records:
  - bright-smile-dental  (dental vertical)
  - tacos-el-rey         (restaurant vertical)

Run once:  uv run python seed.py
Re-running is safe — it upserts.
"""

from db import init_db, upsert_tenant

TENANTS = [
    {
        "id": "first-national-bank",
        "vertical": "banking",
        "name": "First National Bank",
        "location": "Dallas, Texas",
        "hours": "Monday to Friday, 8am to 6pm. Saturday 9am to 1pm. Closed Sunday.",
        "phone": "214-555-0300",
        "services": [
            "account balances",
            "recent transactions",
            "bill payments",
            "card services",
            "fraud reporting",
            "loan inquiries",
        ],
        "google_calendar_id": "primary",
        "emergency_triage": (
            "If the caller reports unauthorized transactions, a lost or stolen card, "
            "or any suspected fraud, immediately tell them you are connecting them to "
            "the Fraud Prevention team and call transfer_to_human with urgency=fraud."
        ),
        "human_handoff": (
            "If the caller asks for a human, is upset, or has a complex issue you "
            "cannot resolve, offer to transfer them to a live banking specialist."
        ),
        "config": {
            "fraud_hotline": "1-800-555-3728",
            "demo_hint": (
                "Demo cards: last4=4444 phone=7890 (James Carter), "
                "last4=3333 phone=4567 (Maria Chen)"
            ),
        },
    },
    {
        "id": "bright-smile-dental",
        "vertical": "dental",
        "name": "Bright Smile Dental",
        "location": "Allen, Texas",
        "hours": "Monday to Friday, 8am to 5pm. Closed weekends.",
        "phone": "972-555-0100",
        "services": [
            "cleanings and checkups",
            "fillings",
            "crowns",
            "teeth whitening",
            "emergency visits",
        ],
        "google_calendar_id": "primary",
        "emergency_triage": (
            "If the caller describes a knocked-out tooth, severe bleeding, severe "
            "swelling, or facial trauma, treat it as an EMERGENCY: tell them to "
            "stay calm, and say you are connecting them to the on-call dentist now, "
            "then call transfer_to_human with urgency=emergency."
        ),
        "human_handoff": (
            "If the caller asks for a human, is upset, or asks something you cannot "
            "answer, offer to take a detailed message or transfer to the front desk "
            "during business hours."
        ),
        "config": {},
    },
    {
        "id": "tacos-el-rey",
        "vertical": "restaurant",
        "name": "Tacos El Rey",
        "location": "Plano, Texas",
        "hours": "Sunday to Thursday 11am to 10pm, Friday and Saturday 11am to 11pm.",
        "phone": "972-555-0200",
        "services": [
            "dine-in",
            "takeout",
            "curbside pickup",
        ],
        "google_calendar_id": "primary",
        "emergency_triage": None,
        "human_handoff": (
            "If the caller is upset or asks something you cannot answer, "
            "offer to take a message or transfer to a manager."
        ),
        "config": {
            "cuisine": "Mexican",
            "max_party_size": 12,
            "reservation_required_above": 6,
            "popular_items": [
                "birria tacos",
                "al pastor burrito",
                "queso fundido",
                "horchata",
            ],
        },
    },
]


if __name__ == "__main__":
    init_db()
    for t in TENANTS:
        upsert_tenant(t)
        print(f"[ok] Seeded tenant: {t['id']} ({t['vertical']})")
    print("\nDone. Run 'uv run bot.py --tenant bright-smile-dental' to test.")
