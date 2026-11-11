"""
ScamShield AI - frontend/views/url_page.py
==========================================
The URL Analyser page.

Design decisions that matter
----------------------------
* A prominent, non-dismissible safety note explains that the link is NOT
  visited and that pattern analysis cannot prove a site is malicious.
* Preset examples cover the main attack patterns so a reviewer can see each
  indicator light up.
* The parsed URL anatomy is displayed (scheme / subdomain / domain / TLD /
  path) because "read the domain from the right" is the single most useful
  skill we can teach a user.
"""

from __future__ import annotations

import html
import json

import streamlit as st

from frontend import api_client
from frontend.components import result_view, ui

URL_EXAMPLES = {
    "Brand look-alike (SBI)": "http://sbi-kyc-verify.xyz/login/update",
    "Credentials in URL": "http://sbi.co.in@secure-login-verify.xyz/kyc",
    "IP address host": "http://192.168.4.7/bank/login.php",
    "Shortened link": "https://bit.ly/x9k2",
    "Punycode look-alike (PayPal)": "https://xn--pypal-4ve.com/login",
    "Executable download": "https://paytm-offer.apk",
    "Deep subdomains": "https://a.b.c.d.account-secure.tk/verify",
    "Genuine bank site (control)": "https://www.sbi.co.in/web/personal-banking",
}

URL_KEY = "url_input"
URL_RESULT_KEY = "url_result"


def _anatomy(analysis: dict) -> None:
    """Show how the URL decomposes - the core teaching moment."""
    st.markdown(
        f"""
        <div class="ss-card">
          <div class="ss-card-label">URL anatomy</div>
          <div class="ss-mono" style="margin-top:8px;line-height:1.9;">
            <span style="color:#96a7c4;">scheme</span> {html.escape(analysis['scheme'] or '—')}://
            <span style="color:#f59e0b;">subdomains</span> {html.escape(str(analysis['subdomain_count']))}
            &nbsp;·&nbsp;
            <span style="color:#22d3ee;font-weight:600;">domain</span>
            {html.escape(analysis['registered_domain'] or analysis['hostname'])}
            &nbsp;·&nbsp;
            <span style="color:#96a7c4;">tld</span> .{html.escape(analysis['tld'] or '—')}
            &nbsp;·&nbsp;
            <span style="color:#96a7c4;">path</span> {html.escape(analysis['path'] or '—')}
          </div>
          <div class="ss-card-foot" style="margin-top:10px;">
            HTTPS: <b>{'yes' if analysis['is_https'] else 'no'}</b> ·
            IP host: <b>{'yes' if analysis['is_ip_address'] else 'no'}</b> ·
            shortener: <b>{'yes' if analysis['is_shortener'] else 'no'}</b> ·
            length: <b>{analysis['url_length']}</b>
            {' · imitates: <b>' + html.escape(analysis['lookalike_of'] or '') + '</b>' if analysis.get('lookalike_of') else ''}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render() -> None:
    st.subheader("URL Analyser")
    st.warning(
        "**This tool never opens the link.** It performs static pattern analysis only — "
        "no HTTP request, no DNS lookup. It cannot prove a website is malicious, and a "
        "low score is not a safety guarantee."
    )

    columns = st.columns(4, gap="small")
    for index, (label, value) in enumerate(URL_EXAMPLES.items()):
        with columns[index % 4]:
            if st.button(label, key=f"url_example_{index}", width="stretch"):
                st.session_state[URL_KEY] = value
                st.session_state[URL_RESULT_KEY] = None
                st.rerun()

    url = st.text_input(
        "URL to analyse",
        key=URL_KEY,
        placeholder="https://example.com/login",
    )

    left, right = st.columns([1, 3])
    with left:
        language = st.selectbox("Explanation language", ["en", "hi", "hinglish"], key="url_lang")
    with right:
        include_explanation = st.toggle("Generate explanation", value=True, key="url_expl")

    if st.button("🔗 Analyse URL", type="primary"):
        if not url or not url.strip():
            st.warning("Please enter a URL.")
        else:
            with st.spinner("Running static checks…"):
                try:
                    st.session_state[URL_RESULT_KEY] = api_client.scan_url(
                        url=url.strip(),
                        language=language,
                        include_explanation=include_explanation,
                    )
                except api_client.APIError as exc:
                    st.error(f"Analysis failed: {exc}")
                    st.session_state[URL_RESULT_KEY] = None

    result = st.session_state.get(URL_RESULT_KEY)
    if not result:
        ui.note(
            "Checks performed: HTTPS usage, IP-literal hosts, link shorteners, punycode and "
            "homoglyph look-alikes, high-abuse TLDs, subdomain depth, brand impersonation, "
            "phishing keywords in the host/path, embedded credentials, unusual ports and "
            "executable downloads."
        )
        return

    st.divider()

    for analysis in result["urls"]["analyses"]:
        _anatomy(analysis)
        st.write("")

    result_view.render(result)

    st.download_button(
        "Download JSON",
        data=json.dumps(result, indent=2, ensure_ascii=False),
        file_name=f"scamshield_url_{result['scan_id'][:8]}.json",
        mime="application/json",
    )

    with st.expander("How to read a domain correctly"):
        st.markdown(
            """
Read a domain **from the right**, and stop at the first single slash:

| URL | Real destination | Verdict |
|---|---|---|
| `https://www.sbi.co.in/login` | `sbi.co.in` | genuine |
| `http://sbi.co.in.evil.xyz/login` | `evil.xyz` | fake |
| `http://sbi.co.in@evil.xyz/login` | `evil.xyz` | fake (everything before `@` is ignored) |
| `https://sbi-kyc-verify.xyz` | `sbi-kyc-verify.xyz` | fake (SBI does not own `.xyz`) |

Anything *before* the registered domain is a subdomain and can be chosen freely
by the attacker, so `sbi.` in a subdomain proves nothing.
"""
        )
