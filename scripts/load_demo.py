"""Upload company-neutral synthetic journals and email through the public API."""

import os
from email.message import EmailMessage

import httpx

API = os.getenv("KMA_API_URL", "http://localhost:8000")


def main() -> None:
    client = httpx.Client(base_url=API, timeout=30)
    login = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "Admin123!"}
    )
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    spaces = client.get("/api/v1/spaces", headers=headers).json()
    operations = next(space for space in spaces if space["name"] == "Operations Journal")
    leadership = next(space for space in spaces if space["name"] == "Leadership Briefings")
    journal = """# Engineer Journal EJ-1042
Date: 2026-09-18
Shipment: DEMO-SG-2048
The shipment completed inspection at Jurong hub. A packaging issue was corrected.
Current status: cleared for dispatch. Next review is scheduled for 2026-09-20.
"""
    client.post(
        "/api/v1/documents",
        headers=headers,
        data={"space_id": operations["id"]},
        files={"file": ("engineer-journal.md", journal, "text/markdown")},
    ).raise_for_status()
    email = EmailMessage()
    email["Subject"] = "Synthetic leadership logistics briefing"
    email["From"] = "leader@example.invalid"
    email["To"] = "operations@example.invalid"
    email.set_content(
        "For demonstration only: the alternate carrier review remains confidential "
        "and is not approved."
    )
    client.post(
        "/api/v1/documents",
        headers=headers,
        data={"space_id": leadership["id"]},
        files={"file": ("leadership-briefing.eml", email.as_bytes(), "message/rfc822")},
    ).raise_for_status()
    print("Synthetic demo documents queued for ingestion.")


if __name__ == "__main__":
    main()
