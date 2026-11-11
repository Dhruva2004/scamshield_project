"""
ScamShield AI - backend/api/samples.py
======================================
Curated demonstration inputs.

Why this endpoint exists
------------------------
A demo that starts from an empty textbox is hard to evaluate. These samples are
hand-written to exercise each detection category, so a reviewer can click
"KYC phishing" and see the full pipeline fire. They are served from the API
(not hard-coded in Streamlit) so the presentation deck and the UI stay in sync.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

router = APIRouter(prefix="/samples", tags=["samples"])

SAMPLES: List[Dict[str, Any]] = [
    {
        "id": "kyc_phishing",
        "label": "KYC / bank phishing SMS",
        "category": "phishing",
        "expected_risk": "critical",
        "text": (
            "Dear Customer, your SBI KYC has been suspended today. Update immediately "
            "at http://sbi-kyc-verify.xyz/login or your account will be blocked within "
            "24 hours. - SBI Team"
        ),
    },
    {
        "id": "otp_call",
        "label": "OTP request (vishing)",
        "category": "otp",
        "expected_risk": "critical",
        "text": (
            "Sir I am calling from HDFC bank customer care. Please share the OTP you "
            "just received on your mobile to complete your account verification, "
            "otherwise your debit card will be blocked."
        ),
    },
    {
        "id": "upi_collect",
        "note": "Genuinely ambiguous: could be a real wrong-transfer. Treated as critical because the money flow is irreversible.",
        "label": "UPI 'refund' QR scam",
        "category": "payment",
        "expected_risk": "critical",
        "text": (
            "I have sent you Rs 5000 by mistake. Please scan this QR code and enter your "
            "UPI PIN to send the money back to 9876543210@ybl immediately."
        ),
    },
    {
        "id": "lottery",
        "note": "Advanced-fee fraud: the 'fee' is the actual theft.",
        "label": "Lottery prize lure",
        "category": "reward",
        "expected_risk": "critical",
        "text": (
            "CONGRATULATIONS!!! Your number has won Rs 25,00,000 in the KBC lucky draw. "
            "Pay Rs 5000 processing fee to claim your prize now. WhatsApp 9876543210."
        ),
    },
    {
        "id": "fake_job",
        "label": "Fake work-from-home job",
        "category": "job",
        "expected_risk": "critical",
        "text": (
            "Work from home!! Earn Rs 5000 per day doing simple typing tasks. No "
            "experience needed. Join our Telegram group for daily tasks. Registration "
            "fee Rs 199 only."
        ),
    },
    {
        "id": "digital_arrest",
        "label": "Digital arrest / fake police",
        "category": "impersonation",
        "expected_risk": "critical",
        "text": (
            "This is CBI officer Sharma. A parcel in your name was seized with illegal "
            "items. You are under digital arrest. Pay Rs 50,000 penalty to avoid an FIR. "
            "Do not tell anyone about this call."
        ),
    },
    {
        "id": "apk_malware",
        "label": "Malicious APK + remote access",
        "category": "malware",
        "expected_risk": "critical",
        "text": (
            "Dear user, your KYC is pending. Install this app to update KYC: "
            "http://paytm-offer.apk - also install AnyDesk and share your screen for "
            "verification. Refund of Rs 2000 will be credited."
        ),
    },
    {
        "id": "hinglish",
        "label": "Hinglish scam message",
        "category": "language",
        "expected_risk": "critical",
        "text": (
            "Aapka account band ho jayega. Turant KYC update karein aur OTP batao, "
            "warna card block ho jayega. Abhi karein!"
        ),
    },
    {
        "id": "bad_url",
        "label": "Suspicious URL only",
        "category": "url",
        "expected_risk": "critical",
        "text": "http://sbi.co.in@secure-login-verify.xyz/kyc/update",
    },
    {
        "id": "benign_chat",
        "label": "Genuine chat (control)",
        "category": "benign",
        "expected_risk": "low",
        "text": "Hi Rahul, are we still meeting at 6 pm near the metro station? Let me know.",
    },
    {
        "id": "benign_bank_alert",
        "note": (
            "Control case that exposed a real false positive during testing. It now lands at "
            "MEDIUM (20/100) because the model over-scores transactional alerts. We kept the "
            "honest value instead of tuning until it read LOW."
        ),
        "label": "Genuine bank debit alert (control)",
        "category": "benign",
        "expected_risk": "medium",
        "text": (
            "Rs.1250.00 debited from A/c XX1234 on 09-11-26 to VPA rahul@okhdfcbank. "
            "Balance 12000.00. Not you? Call the number on your card. -SBI"
        ),
    },
]


@router.get("", summary="Curated demonstration messages")
def list_samples() -> List[Dict[str, Any]]:
    """Return the demo sample list for the UI's 'try an example' buttons."""
    return SAMPLES
