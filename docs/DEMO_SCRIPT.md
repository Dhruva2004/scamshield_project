# ScamShield AI — Demonstration Script

**Total: 8 minutes.** Timings are guidance; the order matters more than the clock.
Every command and every number below has been verified against this build.

---

## Before you start (5 minutes before presenting)

```powershell
# 1. Activate the environment
.\.venv\Scripts\Activate.ps1

# 2. Make sure the model exists
Test-Path models\model_logistic_regression.joblib     # must be True

# 3. Reset and seed demo data so the dashboard is populated
python scripts/seed_demo_data.py --clear

# 4. Start both services
python scripts/run_dev.py
```

Open in two browser tabs:

* **Tab A** — <http://localhost:8501> (dashboard)
* **Tab B** — <http://localhost:8000/docs> (API, for the technical questions)

> If Gemini is not configured, everything still works: explanations fall back and the UI
> states it. Say so out loud — it is a feature, not a failure.

---

## Minute 0:00 — The problem (45 s)

> "Indians lost thousands of crores to digital fraud last year, and almost all of it arrived
> as an ordinary-looking SMS or WhatsApp message. The victim is not careless — the message
> is deliberately designed to create panic. ScamShield AI answers two questions: *is this a
> scam?* and *why does the system think so?*"

Show the dashboard. Point at the KPI row:

> "Eleven analyses, ten high or critical. The charts are live from SQLite, and the model
> metrics at the bottom are measured, not typed in."

---

## Minute 0:45 — Detection, end to end (2 min)

Go to **Message Analyser** → click the **"KYC / bank phishing SMS"** sample → **Analyse**.

> "I pasted a message that claims my SBI KYC is suspended and gives me a link with a
> 24-hour deadline."

Walk down the result **in order**:

1. **Verdict banner** — `CRITICAL · 100/100 · "Do not interact with this message"`.
   > "The score is not a black box; scroll down and every point is accounted for."

2. **Rule engine column** — expand "Show all 9 findings".
   > "Nine explainable rules fired: a KYC-suspension claim, a threat of blocking, urgency
   > language, a brand-imitation domain. Every row shows the exact text that matched, so a
   > user — or an auditor — can check the reasoning themselves."

3. **ML classifier column** — `92% P(spam)`, label `spam`.
   > "Independently, a TF-IDF + Logistic Regression model trained on 5,158 real SMS messages
   > also says spam. Note the disclaimer: this is a model score, not proof of fraud."

4. **URL analysis column** — `67/100`, "Domain imitates 'SBI'".
   > "The link was never opened. The analyser noticed the domain is `sbi-kyc-verify.xyz` —
   > SBI does not own `.xyz` — that it uses plain HTTP, and that a high-abuse TLD is
   > involved."

5. **Explanation & guidance** — read one recommendation aloud.
   > "Plain language, and it ends with a concrete action plus the cybercrime helpline."

---

## Minute 2:45 — Multilingual (1 min)

Scroll back up, change **Explanation language** to **Hinglish**, analyse again.

> "Same detection, same score — only the narrative changed."

Point at the Hindi/Hinglish section of the explainer output.

> "One honest caveat: the classifier was trained on English SMS only. Here is a Hinglish
> message where the model is nearly useless…"

Back in **Message Analyser**, pick the **"Hinglish scam message"** sample and analyse it.

> "…the model says **7%** spam, but the rule engine says **100/100** — critical. The UI shows
> both numbers side by side, because pretending the model understands Hinglish would be
> dishonest. That gap is exactly what the multilingual roadmap addresses."

---

## Minute 3:45 — URL analyser (1 min)

Go to **URL Analyser** → click **"Credentials in URL"** → Analyse.

> "`http://sbi.co.in@secure-login-verify.xyz/kyc`. Everything before the `@` is ignored by
> the browser — this actually goes to `secure-login-verify.xyz`. That is a critical
> indicator."

Point at the **URL anatomy** card.

> "The UI teaches the fix: read the domain from the right, stop at the first slash."

Click **"Genuine bank site (control)"** → score **0/100**.

> "The same analyser gives a clean result on the real SBI site — it is not just flagging
> everything with 'sbi' in it."

Then state the limitation before anyone asks:

> "This tool never contacts the URL. No DNS, no HTTP. That is a hard guarantee — there is a
> test that monkeypatches `socket.connect` and fails if the analyser ever opens a
> connection. The trade-off is that it cannot detect a compromised legitimate site."

---

## Minute 4:45 — Machine learning, honestly (1.5 min)

Go to **Statistics**.

> "Three algorithms were trained and compared on a stratified 80/20 split."

Point at the comparison table:

| Model | F1 | ROC-AUC | Selected |
|---|---|---|---|
| MultinomialNB | 0.9344 | 0.9896 | |
| **LogisticRegression** | **0.9407** | **0.9985** | ✅ |
| RandomForest | 0.9435 | 0.9982 | |

> "Random Forest has the highest F1 — by 0.0028. That is a fifth of the cross-validation
> fold spread, so calling it a win would be dishonest. The rule was declared up front:
> models within 0.01 are tied, break the tie on ROC-AUC, then on simplicity.
>
> Logistic Regression wins on substance: 162 KB versus 3.3 MB, microsecond inference,
> calibrated probabilities, and per-term coefficients — which is what makes the next screen
> possible."

Scroll to **"What the model learned"**:

> "These are the actual coefficients: 'claim', 'txt', 'prize' push towards spam;
> 'ok', 'lt', 'later' push towards ham. That is the interpretability payoff."

Scroll to **"Honest limitations"** — read the false-positive row aloud:

> "A genuine SBI debit alert lands at MEDIUM, 20/100, because this 2005-era model rarely saw
> transactional alerts. We mitigated it with a structural rule that damps the ML component
> — and then we stopped. We did not tune thresholds until every test looked perfect. That
> number is printed in our docs and locked in by a test."

---

## Minute 6:15 — History and privacy (45 s)

Go to **History**.

> "Only redacted previews are stored. Phone numbers, emails, card numbers and OTP values are
> replaced before anything is written to SQLite, and before anything is sent to Gemini."

Select a scan → **Open detail** → point at the redacted text.

> "The raw message is not returned by the API unless you explicitly ask for it *and* the
> deployment allows storing it. And here — "

Point at **Clear all history**:

> "— is the user's control. One checkbox, one click, everything gone. Data protection is a
> feature, not a footnote."

---

## Minute 7:00 — Engineering quality (45 s)

Switch to **Tab B** (<http://localhost:8000/docs>).

> "Everything the UI does is a documented REST endpoint, so a React frontend or a WhatsApp
> bot could reuse the same backend unchanged."

Run in a terminal:

```powershell
pytest -q
```

> "250 automated tests in about six seconds, 79% coverage. Some are worth naming:
> one monkeypatches `socket.connect` to prove the URL analyser never opens a network
> connection; one asserts that the weights published by `/scan/explain-scoring` match the
> constants in the code, so the documentation cannot drift; one runs all eleven demo
> samples and fails if any risk level disagrees with the slide deck."

---

## Minute 7:45 — Close (15 s)

> "ScamShield AI is not a magic detector. It is an explainable system: three independent
> layers, a clear verdict, a reason for every point, honest limits, and privacy by default.
> The next step is the one that matters — a labelled corpus of real Indian scam messages, so
> the model can be judged on the traffic it is actually meant to protect."

---

## Likely questions and short answers

| Question | Answer |
|---|---|
| *Why not just use an LLM for everything?* | Non-deterministic, expensive, unauditable, and it hallucinates verdicts. Here Gemini only narrates results produced by deterministic engines. |
| *Why is accuracy not your headline metric?* | Spam is 12.4% of the data — always answering "ham" gives 87.6% accuracy and catches nothing. We report F1 and per-class recall. |
| *Why Logistic Regression over Random Forest?* | F1 gap 0.0028 is inside CV noise; LR wins on ROC-AUC (0.9985), size (162 KB vs 3.3 MB) and interpretability. |
| *What about Hindi?* | Classifier: no. Rules: curated keywords. Explanation: yes. Stated in the UI, the README and the API response. |
| *Can it be fooled?* | Yes. Novel phrasing can evade the rules, and a compromised legitimate domain passes URL analysis. Documented in `docs/LIMITATIONS.md`. |
| *How do you know it is not overfitted?* | Vectorizer fitted on train only, stratified split, 5-fold CV reported with standard deviation, and a documented false positive we did not tune away. |
| *Is any real data stored?* | Only redacted text plus a salted hash, with a retention cap and a one-click clear. |
