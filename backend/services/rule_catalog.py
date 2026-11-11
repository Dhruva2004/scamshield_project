"""
ScamShield AI - backend/services/rule_catalog.py
================================================
The *data* behind the rule-based detector.

Why keep rules in a separate file from the engine?
--------------------------------------------------
Separation of data and logic. A security analyst can add a rule here without
touching the scoring engine, and every rule is reviewable in one place.

Rule anatomy
------------
    RuleSpec(
        rule_id   = "R_OTP_SHARE"        stable id (used by the UI and tests)
        title     = "Asks the recipient to share an OTP"
        category  = "otp"                used for de-duplication and charts
        severity  = CRITICAL             sets the weight (0/6/12/20/32)
        patterns  = [regex, regex, ...]  ANY match triggers the rule
        min_hits  = 1                    how many distinct patterns must match
        note      = "why this matters"
        advice    = "what the user should do"
    )

Design choices worth defending in a viva
----------------------------------------
1. Patterns run on the *canonicalised* text (lowercase, leetspeak folded,
   dotted acronyms joined). That defeats "K.Y.C" and "acc0unt".
2. Patterns are plain Python regexes: no external NLP dependency, so the
   detector is fast, deterministic and fully explainable.
3. Hindi/Hinglish support is a CURATED KEYWORD LIST, not a trained model.
   We say so explicitly in the UI - this is the honest position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from backend.schemas.common import Severity


@dataclass(frozen=True)
class RuleSpec:
    """Declarative description of one detection rule."""

    rule_id: str
    title: str
    category: str
    severity: Severity
    patterns: List[str]
    description: str
    advice: str = ""
    min_hits: int = 1
    # When True the rule needs at least one *other* rule in the same message
    # to be meaningful (e.g. "a bare number is only interesting if the message
    # also asks you to call it after paying).
    requires_context: bool = False
    languages: List[str] = field(default_factory=lambda: ["en"])


# ---------------------------------------------------------------------------
# 1. OTP, PIN, password and credential requests
# ---------------------------------------------------------------------------
CREDENTIAL_RULES: List[RuleSpec] = [
    RuleSpec(
        rule_id="R_OTP_SHARE_REQUEST",
        title="Asks you to share or forward an OTP",
        category="otp",
        severity=Severity.CRITICAL,
        patterns=[
            r"\b(share|send|forward|tell|give|provide|confirm|reply with|read out)\b[^.]{0,40}\botp\b",
            r"\botp\b[^.]{0,40}\b(share|send|forward|tell|provide|confirm)\b",
            r"\b(share|send)\b[^.]{0,25}\b(one[- ]?time password|verification code|6 digit code)\b",
            # Hinglish / Hindi (curated keywords, not a trained model)
            r"\botp\b[^.]{0,30}\b(batao|bata\s?dijiye|bhejo|bhej\s?dijiye|de\s?dijiye|share\s?karein)\b",
            r"\b(otp|ओटीपी)\b[^.]{0,25}\b(बताइए|बताएं|भेजें|साझा)\b",
        ],
        description=(
            "No legitimate bank, wallet or government body ever asks you to share an "
            "OTP, verification code or PIN - not by call, SMS, WhatsApp or email."
        ),
        advice="Never share this code with anyone, even someone claiming to be your bank.",
    ),
    RuleSpec(
        rule_id="R_OTP_MENTIONED",
        title="Mentions an OTP or verification code",
        category="otp",
        severity=Severity.LOW,
        patterns=[
            r"\botp\b",
            r"\bone[- ]?time password\b",
            r"\bverification code\b",
            r"\b(?:otp|code)\s*(?:is|:)\s*\d{4,8}\b",
        ],
        description=(
            "The message contains an OTP. This is common in genuine bank alerts, so on "
            "its own it is only a weak signal - the risk comes from being asked to "
            "share it or from a link in the same message."
        ),
    ),
    RuleSpec(
        rule_id="R_PASSWORD_REQUEST",
        title="Requests a password or PIN",
        category="credential",
        severity=Severity.CRITICAL,
        patterns=[
            r"\b(password|passwd|pwd|pin|m?pin|atm pin|card pin|net ?banking password)\b[^.]{0,40}"
            r"\b(share|send|enter|provide|confirm|update|verify|reset|expire|compromis)",
            r"\b(share|send|enter|provide|confirm|update|verify)\b[^.]{0,40}"
            r"\b(password|passwd|pwd|atm pin|card pin|upi pin)\b",
            r"\b(पासवर्ड|पिन)\b[^.]{0,30}\b(भेजें|बताएं|डालें)\b",
        ],
        description=(
            "Requests for passwords, ATM PINs or UPI PINs are a direct credential-theft "
            "attempt. Banks never ask for these."
        ),
        advice="Never enter your PIN or password anywhere reached through a link.",
    ),
    RuleSpec(
        rule_id="R_CARD_DETAILS_REQUEST",
        title="Requests card details, CVV or expiry date",
        category="credential",
        severity=Severity.CRITICAL,
        patterns=[
            r"\b(cvv|cvc|card number|16 digit|card details|debit card|credit card)\b"
            r"[^.]{0,40}\b(share|send|provide|enter|update|verify|confirm|blocked|expire)",
            r"\b(share|send|provide|enter|update)\b[^.]{0,40}\b(cvv|card number|card details)\b",
        ],
        description="Card number + CVV + expiry is everything needed to make online payments.",
        advice="Never share card details; a bank already knows them.",
    ),
    RuleSpec(
        rule_id="R_AADHAAR_PAN_REQUEST",
        title="Asks for Aadhaar or PAN details",
        category="credential",
        severity=Severity.HIGH,
        patterns=[
            r"\b(aadhaar|aadhar|adhar|pan card|pan number|uidai)\b[^.]{0,45}"
            r"\b(number|details|photo|copy|share|send|update|verify|link|submit)\b",
            r"\b(share|send|submit|upload)\b[^.]{0,30}\b(aadhaar|aadhar|pan)\b",
        ],
        description=(
            "Aadhaar/PAN numbers are identity documents. They are harvested for identity "
            "theft and for opening fraudulent accounts or loans."
        ),
        advice="Share identity documents only on official portals you opened yourself.",
    ),
    RuleSpec(
        rule_id="R_CREDENTIAL_LINK_COMBO",
        title="Asks you to log in or verify credentials through a link",
        category="phishing",
        severity=Severity.HIGH,
        patterns=[
            r"\b(click|open|tap|visit|follow)\b[^.]{0,40}\b(link|here|below)\b[^.]{0,60}"
            r"\b(login|log in|sign in|verify|update|confirm|reactivate|unlock|authenticate)\b",
            r"\b(login|log ?in|sign ?in|verify|update|reactivate|unlock)\b[^.]{0,40}"
            r"\b(here|below|link|account|details)\b[^.]{0,20}\b(click|open|visit)\b",
            r"\b(click|open)\b[^.]{0,20}\b(here|link)\b[^.]{0,40}\b(kyc|pan|aadhaar|account)\b",
        ],
        description=(
            "The classic phishing pattern: a link that leads to a fake login page designed "
            "to capture your username, password or OTP."
        ),
        advice="Open your bank app directly instead of using the link.",
    ),
]

# ---------------------------------------------------------------------------
# 2. Urgency, threats and pressure
# ---------------------------------------------------------------------------
URGENCY_RULES: List[RuleSpec] = [
    RuleSpec(
        rule_id="R_URGENCY_LANGUAGE",
        title="Creates urgency or a deadline",
        category="urgency",
        severity=Severity.MEDIUM,
        patterns=[
            r"\burgent\b", r"\bimmediately\b", r"\bright now\b", r"\bright away\b",
            r"\bwithin \d+\s*(?:hours?|hrs?|minutes?|mins?|days?)\b",
            r"\blast (?:chance|warning|reminder|notice)\b", r"\bfinal (?:notice|warning|reminder)\b",
            r"\bexpir(?:e|es|ing|ed)\b", r"\bact now\b", r"\bdon'?t delay\b",
            r"\btime is running out\b", r"\bonly \d+ (?:left|remaining)\b",
            r"\bbefore it'?s too late\b", r"\bimmediate action\b",
            # Hinglish / Hindi
            r"\bturant\b", r"\bforan\b", r"\bjaldi\b", r"\babhi\b", r"\bतुरंत\b", r"\bजल्दी\b",
            r"\babhi karein\b", r"\bturant karein\b",
        ],
        description=(
            "Artificial deadlines stop you from thinking and checking. Real institutions "
            "give notice periods, not countdowns measured in minutes."
        ),
        advice="Slow down. A genuine notice will not disappear in 10 minutes.",
    ),
    RuleSpec(
        rule_id="R_THREAT_LANGUAGE",
        title="Threatens loss, blocking or legal action",
        category="threat",
        severity=Severity.HIGH,
        patterns=[
            r"\b(account|card|sim|service|number|policy|connection)\b[^.]{0,35}"
            r"\b(block(?:ed|ing)?|suspend(?:ed|ing)?|deactivat(?:ed|ing)|frozen|closed|"
            r"disconnected|terminated|cancell?ed)\b",
            r"\b(block(?:ed|ing)?|suspend(?:ed|ing)?|deactivat(?:ed|ing)|frozen)\b"
            r"[^.]{0,35}\b(account|card|sim|service|number)\b",
            r"\b(legal action|fir|police case|court notice|arrest|non-bailable|"
            r"penalty|fine of|law ?suit|recovery notice)\b",
            r"\b(will be (?:blocked|suspended|terminated|deactivated))\b",
            # Hinglish / Hindi
            r"\b(account|khata)\b[^.]{0,25}\b(band|block)\b",
            r"\b(बंद|ब्लॉक|निलंबित)\b", r"\bकानूनी कार्रवाई\b",
        ],
        description=(
            "Fear of losing money or access is the most common lever in Indian SMS and "
            "WhatsApp scams (KYC, SIM-block, electricity-disconnection scams)."
        ),
        advice="Log in through the official app to check any 'blocked' claim.",
    ),
    RuleSpec(
        rule_id="R_LEGAL_IMPERSONATION",
        title="Impersonates police, court, tax or telecom authority",
        category="impersonation",
        severity=Severity.HIGH,
        patterns=[
            r"\b(cbi|cid|police|cyber cell|trai|income tax|it department|gst department|"
            r"customs|narcotics|enforcement directorate|ed officer|rbi|sebi)\b",
            r"\b(digital arrest)\b",
            r"\b(parcel|consignment|courier)\b[^.]{0,40}\b(illegal|drugs|seized|customs)\b",
        ],
        description=(
            "'Digital arrest' and fake courier/customs calls are a fast-growing fraud in "
            "which officers demand payment to avoid arrest."
        ),
        advice=(
            "No Indian agency demands payment over WhatsApp or a video call. Verify by "
            "calling the official number yourself."
        ),
    ),
    RuleSpec(
        rule_id="R_SECRECY_DEMAND",
        title="Asks you to keep the request secret",
        category="social_engineering",
        severity=Severity.HIGH,
        patterns=[
            r"\b(do not|don'?t|never) (?:tell|inform|share (?:this )?with|discuss)\b"
            r"[^.]{0,30}\b(anyone|anybody|family|police|bank|staff)\b",
            r"\bkeep (?:this|it) (?:confidential|secret|between us)\b",
            r"\bconfidential(?:ly)?\b[^.]{0,40}\b(do not|don'?t) (?:tell|share)\b",
        ],
        description=(
            "Isolating the victim from people who would spot the scam is a textbook social "
            "engineering technique."
        ),
        advice="Talk to someone you trust before acting on a secretive request.",
    ),
]

# ---------------------------------------------------------------------------
# 3. Banking, KYC and wallet impersonation
# ---------------------------------------------------------------------------
BANKING_RULES: List[RuleSpec] = [
    RuleSpec(
        rule_id="R_KYC_SCAM",
        title="KYC update / suspension claim",
        category="kyc",
        severity=Severity.HIGH,
        patterns=[
            r"\bkyc\b[^.]{0,45}\b(update|pending|suspend|expire|complete|verify|"
            r"re[- ]?verify|incomplete|block|last date|deadline)\b",
            r"\b(update|pending|complete|verify|re[- ]?verify)\b[^.]{0,30}\bkyc\b",
            r"\bkyc\b",
            r"\bकेवाईसी\b",
        ],
        description=(
            "The 'your KYC is expiring, update now' message is India's most-reported SMS "
            "fraud. Real KYC reminders never contain a link that asks for OTP or card data."
        ),
        advice="Update KYC only inside your bank's official app or at a branch.",
    ),
    RuleSpec(
        rule_id="R_BANK_IMPERSONATION",
        title="Impersonates a bank, wallet or payment app",
        category="impersonation",
        severity=Severity.MEDIUM,
        patterns=[
            r"\b(sbi|state bank|hdfc|icici|axis bank|kotak|punjab national|pnb|bank of baroda|"
            r"canara|union bank|indusind|yes bank|idfc|federal bank|rbl|bandhan|"
            r"paytm|phonepe|phone pe|google pay|gpay|amazon pay|bhim|mobikwik|freecharge|"
            r"cred|slice|navi)\b",
            r"\b(your bank|the bank|bank team|bank officials?|net ?banking team)\b",
            r"\b(बैंक|एसबीआई|पेटीएम)\b",
        ],
        description=(
            "Brand names add instant credibility. Attackers copy the logo, sender ID and "
            "wording of real alerts, so the brand name alone proves nothing."
        ),
        advice="Check the sender ID and the link domain - not the logo.",
    ),
    RuleSpec(
        rule_id="R_GENERIC_GREETING",
        title="Generic, non-personal greeting",
        category="phishing",
        severity=Severity.LOW,
        patterns=[
            r"\bdear (?:customer|user|member|sir/madam|valued customer|account holder)\b",
            r"\b(?:dear|respected) (?:customer|client)\b",
            r"\bhello (?:user|dear)\b",
            r"\bप्रिय ग्राहक\b", r"\bप्रिय उपभोक्ता\b",
        ],
        description=(
            "Banks address you by name. 'Dear customer' in a bulk message suggests the "
            "sender does not actually know who you are."
        ),
    ),
    RuleSpec(
        rule_id="R_ACCOUNT_STATUS_ALERT",
        title="Claims an account problem (hold, freeze, limited access)",
        category="banking",
        severity=Severity.MEDIUM,
        patterns=[
            r"\b(account|card|wallet)\b[^.]{0,30}\b(on hold|under review|limited|"
            r"restricted|locked|disabled|inactive|dormant|zero balance)\b",
            r"\b(unusual|suspicious|unauthori[sz]ed)\b[^.]{0,30}\b(activity|transaction|login|access)\b",
            r"\b(debited|withdrawn|deducted)\b[^.]{0,40}\b(if not you|not done by you|unauthori)\b",
        ],
        description=(
            "Fake 'unusual activity' alerts create panic and then offer a 'fix' link or a "
            "'helpline' that collects your credentials."
        ),
        advice="Ignore contact details in the message and use the number on your card.",
    ),
]

# ---------------------------------------------------------------------------
# 4. Payments, UPI and money requests
# ---------------------------------------------------------------------------
PAYMENT_RULES: List[RuleSpec] = [
    RuleSpec(
        rule_id="R_UPI_PAYMENT_REQUEST",
        title="Requests a UPI / money transfer",
        category="payment",
        severity=Severity.HIGH,
        patterns=[
            # A bare amount is NOT a payment request - a genuine debit alert
            # also contains "Rs.1,250.00 debited". We require the *verb*.
            r"\b(pay|send|transfer|remit|deposit|credit)\b[^.]{0,35}"
            r"\b(rs\.?|inr|₹|rupees|amount|money|funds|fee|charge|deposit)\b",
            r"\b(upi|vpa)\b[^.]{0,25}\b(pay|send|transfer|scan|id|number|request)\b",
            r"\b(pay|send|transfer|scan)\b[^.]{0,25}\b(upi|vpa|qr|paytm|gpay|phonepe|@)\b",
            r"\b(processing|registration|security|joining|training|handling|delivery|"
            r"customs|courier)\s?(fee|charge|deposit|amount)\b",
            r"\b(bhej\s?dein|bhejo|transfer karein|paise bhejein|paisa bhejo)\b",
            r"\b(पैसे भेजें|भुगतान करें)\b",
        ],
        description=(
            "Any instruction to move money to a UPI ID, account number or wallet is worth "
            "verifying independently - UPI transfers are effectively irreversible."
        ),
        advice="Never send money to an unknown UPI ID; verify the payee name in your app.",
    ),
    RuleSpec(
        rule_id="R_COLLECT_REQUEST",
        title="Payment-collect / QR-scan request",
        category="payment",
        severity=Severity.HIGH,
        patterns=[
            r"\b(scan|स्कैन)\b[^.]{0,25}\b(qr|code|क्यूआर)\b",
            r"\b(qr code|qr)\b[^.]{0,30}\b(scan|pay|receive|get)\b",
            r"\b(approve|accept)\b[^.]{0,30}\b(request|collect)\b[^.]{0,20}\b(upi|pay|money)\b",
            r"\b(collect request|payment request|money request)\b",
        ],
        description=(
            "Scanning a QR code or accepting a collect request SENDS money - it never "
            "receives money. This is a frequent 'refund' scam trick."
        ),
        advice="You never need to scan a QR code or enter a PIN to RECEIVE money.",
    ),
    RuleSpec(
        rule_id="R_UNKNOWN_ACCOUNT",
        title="Directs payment to an unfamiliar account or UPI handle",
        category="payment",
        severity=Severity.MEDIUM,
        patterns=[
            # NOTE: a VPA is only suspicious when the message ASKS you to pay it.
            # "Rs.500 debited ... to VPA x@ybl" is a completed transaction and
            # must not match - verified against a real SBI debit alert.
            r"\b(?:pay|send|transfer|remit|deposit|scan|credit)\b[^.]{0,30}"
            r"\b[a-z0-9._\-]{2,}@(?:ok(?:axis|hdfcbank|icici|sbi)|ybl|paytm|ibl|axl|apl|upi|"
            r"airtel|fbl|jio|sbi|hdfcbank|icici|kotak|yesbank|idfcbank|pnb|cnrb)\b",
            r"\b(?:pay|send|transfer|remit|deposit)\b[^.]{0,30}"
            r"\b(a/?c|account)\s?(?:no|number|num)\.?\s?[:\-]?\s?\d{9,18}\b",
            r"\bifsc\b[^.]{0,20}\b[a-z]{4}0[a-z0-9]{6}\b",
            r"\baccount (?:number|details)\b[^.]{0,25}\b(share|send|provide)\b",
        ],
        description=(
            "A raw account number or UPI handle in a message is the destination of the "
            "money you are being asked to send."
        ),
    ),
    RuleSpec(
        rule_id="R_TINY_TRANSACTION_TRICK",
        title="Small 'verification' payment or refund bait",
        category="payment",
        severity=Severity.HIGH,
        patterns=[
            r"\b(rs\.?|inr|₹)\s?[1-9]\b[^.]{0,40}\b(refund|verify|verification|activate|"
            r"confirm|register|token)\b",
            r"\b(refund|cashback)\b[^.]{0,40}\b(rs\.?|inr|₹)\s?\d",
            r"\b(1 rupee|one rupee|₹1|<1)\b[^.]{0,30}\b(payment|transfer|verify|test)\b",
        ],
        description=(
            "A ₹1 'verification' payment is used to test whether a card/UPI works, or to "
            "trick you into approving a much larger autopay mandate."
        ),
    ),
    RuleSpec(
        rule_id="R_MULE_ACCOUNT",
        title="Asks to use your account to receive or route money",
        category="payment",
        severity=Severity.CRITICAL,
        patterns=[
            r"\b(use|using|lend|rent|give)\b[^.]{0,25}\b(your )?(bank )?(account|card|upi)\b"
            r"[^.]{0,40}\b(receive|transfer|commission|payment|salary)\b",
            r"\b(commission|percentage|cut)\b[^.]{0,35}\b(transfer|receive|deposit|account)\b",
            r"\b(money laundering|mule account)\b",
        ],
        description=(
            "Lending your account for someone else's transfers makes you a 'money mule' - "
            "a criminal offence in India, regardless of intent."
        ),
        advice="Never let anyone else route money through your account.",
    ),
]

# ---------------------------------------------------------------------------
# 5. Rewards, lottery, jobs, investment
# ---------------------------------------------------------------------------
LURE_RULES: List[RuleSpec] = [
    RuleSpec(
        rule_id="R_LOTTERY_PRIZE",
        title="Claims you won a lottery, prize or lucky draw",
        category="reward",
        severity=Severity.HIGH,
        patterns=[
            r"\b(you(?:'ve| have)? (?:won|been selected|is selected)|congratulations[^.]{0,40}"
            r"(won|winner|selected|lucky))\b",
            r"\b(lottery|lucky draw|jackpot|prize money|scratch card|bumper offer|sweepstake)\b",
            r"\b(winner|lucky (?:winner|customer|number))\b[^.]{0,40}\b(claim|reward|prize)\b",
            r"\b(claim|collect)\b[^.]{0,25}\b(prize|reward|winnings|amount)\b",
            # Hinglish / Hindi
            r"\b(jeet|jeeta|jeet gaye|inaam|inam|bumper)\b", r"\b(इनाम|लॉटरी|जीत)\b",
        ],
        description=(
            "You cannot win a lottery you never entered. Real prize claims never require a "
            "'processing fee', tax payment or OTP."
        ),
        advice="A genuine prize never requires an upfront payment.",
    ),
    RuleSpec(
        rule_id="R_REWARD_BAIT",
        title="Offers a free gift, voucher or cashback",
        category="reward",
        severity=Severity.MEDIUM,
        patterns=[
            r"\b(free|complimentary)\b[^.]{0,25}\b(gift|recharge|data|voucher|coupon|iphone|"
            r"laptop|smartphone|trip|holiday)\b",
            r"\b(gift (?:card|voucher|coupon)|amazon voucher|flipkart voucher|paytm cashback)\b",
            r"\b(cashback|discount)\b[^.]{0,20}\b(\d{2,3}%|up to)\b",
            r"\b(reward points|redeem)\b[^.]{0,25}\b(expire|now|click|link)\b",
            r"\b(free recharge|free gift|मुफ्त|निःशुल्क)\b",
        ],
        description=(
            "Free-gift lures are used to push users onto fake pages that harvest card "
            "details or install malicious apps."
        ),
        advice="Treat unsolicited free offers as advertising at best and phishing at worst.",
    ),
    RuleSpec(
        rule_id="R_FAKE_JOB_OFFER",
        title="Unrealistic job or work-from-home offer",
        category="job",
        severity=Severity.HIGH,
        patterns=[
            r"\b(work from home|part[- ]?time job|online job|data entry|typing job|"
            r"copy paste job|reselling|product review job|telegram task)\b",
            r"\b(earn|income|salary)\b[^.]{0,25}\b(rs\.?|inr|₹)?\s?\d{3,}[\d,]*\b"
            r"[^.]{0,20}\b(per day|daily|daily basis|per task|weekly|per hour)\b",
            r"\b(no experience|fresher|any qualification|10th pass|12th pass)\b"
            r"[^.]{0,40}\b(job|work|earning|salary)\b",
            r"\b(hr|recruiter|hiring team)\b[^.]{0,30}\b(whatsapp|telegram)\b",
            r"\b(registration fee|security deposit|training fee|joining fee)\b",
            r"\b(job|naukri|kaam)\b[^.]{0,30}\b(ghar se|ghar baithe|roz|daily)\b",
        ],
        description=(
            "Fake job scams ('earn ₹5,000/day from home') end with a registration fee, a "
            "'task' deposit, or a request for your bank credentials on day one."
        ),
        advice="A real employer never asks a candidate for money.",
    ),
    RuleSpec(
        rule_id="R_INVESTMENT_GUARANTEE",
        title="Guaranteed high returns / trading tips",
        category="investment",
        severity=Severity.HIGH,
        patterns=[
            r"\b(guaranteed|assured|risk[- ]?free|fixed)\b[^.]{0,30}\b(return|profit|income|"
            r"gain|double)\b",
            r"\b(double|triple)\b[^.]{0,25}\b(your )?(money|investment|capital)\b",
            r"\b(crypto|bitcoin|usdt|forex|binary option|sure shot|jackpot call)\b"
            r"[^.]{0,35}\b(invest|profit|return|signal|tips)\b",
            r"\b(institutional account|ipo allotment|pre-ipo|block deal)\b",
            r"\b(intraday|trading)\b[^.]{0,25}\b(tips|group|signal)\b",
        ],
        description=(
            "Guaranteed returns do not exist. Investment fraud groups build trust in a "
            "Telegram/WhatsApp 'trading group' and then block withdrawals."
        ),
        advice="Check SEBI registration before investing with anyone you met online.",
    ),
]

# ---------------------------------------------------------------------------
# 6. Links and technical red flags
# ---------------------------------------------------------------------------
def _build_link_rules() -> List[RuleSpec]:
    """
    Link rules are built here because some of them carry long, shared regex
    fragments that are easier to read when defined once.
    """
    return [
        RuleSpec(
            rule_id="R_LINK_PRESENT",
            title="Contains a link",
            category="link",
            severity=Severity.LOW,
            patterns=[r"\b(?:https?://|www\.)[^\s]+", r"\b[a-z0-9\-]+\.(?:com|in|net|org|xyz|top|"
                      r"club|site|online|shop|app|link|live|pro|cc|info|co)\b"],
            description=(
                "A link in an unsolicited message is the delivery mechanism for most "
                "phishing. Analyse the domain before opening."
            ),
        ),
        RuleSpec(
            rule_id="R_SHORTENED_LINK",
            title="Uses a link shortener",
            category="link",
            severity=Severity.MEDIUM,
            patterns=[
                r"\b(bit\.ly|tinyurl\.com|t\.co|goo\.gl|ow\.ly|is\.gd|buff\.ly|rebrand\.ly|"
                r"cutt\.ly|shorte\.st|adf\.ly|bit\.do|t\.ly|rb\.gy|shorturl\.at|tiny\.cc|"
                r"clck\.ru|s\.id|chip\.ly|lnkd\.in)\b",
            ],
            description=(
                "Shorteners hide the real destination. Legitimate banks rarely use them in "
                "security alerts."
            ),
            advice="Expand the shortened link before opening it, or type the official URL.",
        ),
        RuleSpec(
            rule_id="R_IP_LINK",
            title="Link points to a raw IP address",
            category="link",
            severity=Severity.HIGH,
            patterns=[r"https?://\d{1,3}(?:\.\d{1,3}){3}"],
            description=(
                "Legitimate services use domain names. A bare IP address in a link is a "
                "strong indicator of a hastily deployed phishing kit."
            ),
        ),
        RuleSpec(
            rule_id="R_SUSPICIOUS_TLD",
            title="Link uses a high-abuse top-level domain",
            category="link",
            severity=Severity.MEDIUM,
            patterns=[
                r"https?://[^\s/]*\.(?:xyz|top|club|icu|buzz|cam|sbs|rest|monster|quest|cfd|"
                r"cyou|loan|download|stream|win|bid|date|review|country|kim|party|science|"
                r"gdn|men|click|tk|ml|ga|cf|gq|work|life|live|shop|online|site|space|fun|"
                r"pro|info|zip|mov)\b",
            ],
            description=(
                "Certain cheap TLDs are heavily abused because registration is free or "
                "near-free and requires no identity checks."
            ),
        ),
        RuleSpec(
            rule_id="R_NON_HTTPS_LINK",
            title="Link does not use HTTPS",
            category="link",
            severity=Severity.MEDIUM,
            patterns=[r"http://[^\s]+"],
            description=(
                "Traffic over plain HTTP can be read and modified in transit. Any page that "
                "collects credentials must use HTTPS."
            ),
            advice="Never type a password on a page whose address bar does not show a lock.",
        ),
        RuleSpec(
            rule_id="R_LOOKALIKE_DOMAIN",
            title="Domain imitates a known brand",
            category="link",
            severity=Severity.HIGH,
            patterns=[
                # NOTE: the pattern must end at the TLD. Without the trailing
                # boundary it matched the *path* of the genuine
                # https://www.sbi.co.in/web/personal-banking and produced a
                # false positive (verified by test_safe_url_is_low_risk).
                # The authoritative brand check is the URL analyser; this rule
                # only provides a quick textual signal.
                r"https?://[^\s/]*\b(?:sbi|hdfc|icici|axis|kotak|pnb|bob|canara|unionbank|"
                r"indusind|idfc|yesbank|paytm|phonepe|gpay|googlepay|amazonpay|netflix|"
                r"amazon|flipkart|irctc|uidai|incometax|epfo|lic|airtel|jio|vi)\b"
                r"[a-z0-9\-]*\.(?!co\.in\b|com\b|in\b|co\b|gov\.in\b|org\b|net\b|org\.in\b)"
                r"[a-z]{2,}\b(?![\w\-])",
                r"https?://[^\s/]*(?:-verify|-kyc|-update|-login|-secure|-account|verify-|"
                r"kyc-|update-|login-|secure-|account-)[^\s/]*\.",
            ],
            description=(
                "Attackers register domains like 'sbi-kyc-verify.xyz' or 'hdfcbank-login.top'. "
                "The brand name appears in the domain, but the real brand does not own it."
            ),
            advice="Compare the domain from the right: the part before the first single slash matters.",
        ),
        RuleSpec(
            rule_id="R_URL_CREDENTIAL_PATH",
            title="Link path suggests a credential-capture page",
            category="link",
            severity=Severity.MEDIUM,
            patterns=[
                r"https?://[^\s]*/(?:login|signin|sign-in|verify|verification|kyc|update|"
                r"secure|account|auth|otp|confirm|validate|unlock|wallet|payment|pay)(?:[/?.#]|$)",
            ],
            description=(
                "Paths such as /login or /kyc on an unknown domain usually lead to a cloned "
                "page that submits your credentials to the attacker."
            ),
        ),
        RuleSpec(
            rule_id="R_APK_OR_FILE_DOWNLOAD",
            title="Pushes an app or file download",
            category="malware",
            severity=Severity.CRITICAL,
            patterns=[
                r"\b(install|download)\b[^.]{0,30}\b(apk|app|application|exe|software)\b",
                r"\.apk\b",
                r"\b(anydesk|teamviewer|quick ?support|rustdesk|screen ?share)\b",
                r"\b(remote access|screen sharing)\b[^.]{0,25}\b(app|install|allow)\b",
            ],
            description=(
                "Sideloaded APKs and remote-access tools (AnyDesk, TeamViewer, RustDesk) give "
                "the attacker full control of your phone, including your banking app."
            ),
            advice="Install apps only from the Play Store or App Store. Never install an APK sent to you.",
        ),
    ]


LINK_RULES: List[RuleSpec] = _build_link_rules()

# ---------------------------------------------------------------------------
# 7. Formatting / obfuscation signals
# ---------------------------------------------------------------------------
STYLE_RULES: List[RuleSpec] = [
    RuleSpec(
        rule_id="R_EXCESSIVE_PUNCTUATION",
        title="Excessive punctuation or emoji",
        category="obfuscation",
        severity=Severity.LOW,
        patterns=[r"[!]{2,}", r"[?]{2,}", r"[!?]{3,}"],
        description=(
            "Repeated exclamation marks and emoji are used to create alarm. Formal "
            "institutional communication almost never does this."
        ),
    ),
    RuleSpec(
        rule_id="R_OBFUSCATED_KEYWORDS",
        title="Obfuscated keywords (spaced, dotted or leetspeak)",
        category="obfuscation",
        severity=Severity.MEDIUM,
        patterns=[
            # A token mixing letters and digits that becomes a real word once
            # leetspeak is folded: acc0unt, bl0ck, ver1fy, 0tp ...
            r"\b(?=[a-z0-9]*[a-z])(?=[a-z0-9]*\d)[a-z]{3,}\d[a-z0-9]*\b",
            r"\b(?:w\s?h\s?a\s?t\s?s\s?a\s?p\s?p)\b",     # "w h a t s a p p"
            r"\b[a-z](?:\.[a-z]){2,}\b",                  # k.y.c / v.e.r.i.f.y
        ],
        description=(
            "Deliberately broken-up keywords are used to bypass spam filters and to look "
            "less machine-generated. A human reader still understands them."
        ),
    ),
    RuleSpec(
        rule_id="R_HINDI_HINGLISH_SIGNALS",
        title="Hinglish / Hindi scam phrasing",
        category="language",
        severity=Severity.MEDIUM,
        patterns=[
            r"\b(aapka|aapke|aapki)\b[^.]{0,30}\b(account|khata|card|kyc)\b",
            r"\b(band ho jayega|band ho jayega|block ho jayega|nikal jayega)\b",
            r"\b(update kar(?:e|ein|na|wana) hai|verify kar(?:e|ein|na) hai)\b",
            r"\b(jeet gaye|jeet liya|inaam|inam)\b",
            r"\b(paise|paisa)\b[^.]{0,25}\b(bhej|transfer|jama)\b",
            r"\b(abhi|turant|jaldi)\b[^.]{0,20}\b(karein|karo|kar lijiye)\b",
            r"[\u0900-\u097F]",   # any Devanagari script present
        ],
        description=(
            "Hindi/Hinglish scam wording. IMPORTANT: the ML classifier was trained on "
            "English SMS only, so these messages are caught by these curated rules - not "
            "by the machine-learning model."
        ),
    ),
    RuleSpec(
        rule_id="R_CALLBACK_NUMBER",
        title="Asks you to call an unfamiliar number",
        category="contact",
        severity=Severity.MEDIUM,
        patterns=[
            r"\b(call|contact|dial|helpline|reach)\b[^.]{0,25}\b(us|me|on|at)\b[^.]{0,20}"
            r"\b(?:\+?91[\-\s]?)?[6-9]\d{9}\b",
            r"\b(helpline|customer care|toll[- ]?free)\b[^.]{0,20}\b\d{3,}",
            r"\b(call back|phone back|missed call)\b",
            r"\b(call karein|phone karein|sampark karein)\b",
        ],
        description=(
            "A 'helpline' number inside a scam message connects straight to the fraudster, "
            "who then walks you through the theft of your own money."
        ),
        advice="Use the number printed on your card or the official website.",
    ),
    RuleSpec(
        rule_id="R_CHANNEL_SWITCH",
        title="Moves the conversation to WhatsApp/Telegram",
        category="social_engineering",
        severity=Severity.MEDIUM,
        patterns=[
            r"\b(whatsapp|telegram|signal)\b[^.]{0,30}\b(contact|message|dm|chat|join|group|number)\b",
            r"\b(contact|message|dm|chat|join)\b[^.]{0,30}\b(whatsapp|telegram)\b",
            r"\b(t\.me|wa\.me|chat\.whatsapp\.com)\b",
        ],
        description=(
            "Moving to an unmonitored channel removes the bank's or platform's fraud "
            "controls and makes the conversation harder to trace."
        ),
    ),
]


# ---------------------------------------------------------------------------
# 8. Genuine transactional-alert structure (a NEGATIVE signal, weight 0)
# ---------------------------------------------------------------------------
# Why this exists: during testing, a real SBI debit alert was flagged CRITICAL
# because the SMS-trained model scores "Rs.X debited from A/c ... to VPA ..."
# as spam - such alerts barely appear in the 2005-era UCI corpus. This rule
# recognises the structure of a genuine automated transaction notification so
# the risk assessor can dampen the ML component. It contributes ZERO points.
TRANSACTIONAL_RULES: List[RuleSpec] = [
    RuleSpec(
        rule_id="R_TRANSACTIONAL_ALERT_STRUCTURE",
        title="Matches the structure of an automated bank transaction alert",
        category="transactional",
        severity=Severity.INFO,
        patterns=[
            # amount + debit/credit verb + account reference
            r"\b(?:rs\.?|inr|₹)\s?[\d,]+(?:\.\d{1,2})?\s*(?:has been\s*)?"
            r"(?:debited|credited|withdrawn|deposited)\b[^.]{0,40}\b(?:a/c|ac|account)\b",
            r"\b(?:debited|credited)\b[^.]{0,30}\b(?:a/c|ac|account)\b[^.]{0,40}"
            r"\b(?:balance|bal)\b",
            # balance line is the strongest single marker
            r"\b(?:avl|available|updated)?\s?(?:balance|bal)\b\s*[:\-]?\s*"
            r"(?:rs\.?|inr|₹)?\s?[\d,]+(?:\.\d{1,2})?\b",
        ],
        description=(
            "The message has the shape of a genuine automated transaction notification "
            "(amount + debit/credit + masked account + balance). This lowers, but does "
            "not eliminate, suspicion - fraudsters do copy this format."
        ),
        advice="Cross-check the amount and balance in your bank app before trusting it.",
    ),
]


ALL_RULES: List[RuleSpec] = (
    CREDENTIAL_RULES
    + URGENCY_RULES
    + BANKING_RULES
    + PAYMENT_RULES
    + LURE_RULES
    + LINK_RULES
    + STYLE_RULES
    + TRANSACTIONAL_RULES
)

# Rules that are pure context (a link, a brand name, an OTP mention) and must
# never dominate the score on their own.
CONTEXT_ONLY_RULE_IDS = {
    "R_LINK_PRESENT",
    "R_OTP_MENTIONED",
    "R_BANK_IMPERSONATION",
    "R_GENERIC_GREETING",
}

RULE_INDEX = {rule.rule_id: rule for rule in ALL_RULES}


def get_rule(rule_id: str) -> RuleSpec:
    """Look up a rule by id (raises KeyError for unknown ids)."""
    return RULE_INDEX[rule_id]


def catalogue_summary() -> List[dict]:
    """Human-readable listing used by the /api/v1/rules endpoint and the UI."""
    return [
        {
            "rule_id": rule.rule_id,
            "title": rule.title,
            "category": rule.category,
            "severity": rule.severity.value,
            "weight": rule.severity.weight,
            "description": rule.description,
            "advice": rule.advice,
            "pattern_count": len(rule.patterns),
        }
        for rule in ALL_RULES
    ]
