"""Streamlit front-end for the Lead-to-Sale MVP. Run: streamlit run streamlit_app.py
Reuses the same logic as app.py (pipeline, scoring, proposals, approvals)."""
import os
import streamlit as st
import app as core, scoring

st.set_page_config(page_title="Lead-to-Sale", layout="wide")

if not (scoring.MODELS / "active.json").exists():
    with st.spinner("Training scoring model (first run only)..."):
        scoring.train()

def secret(k, d):
    try: return st.secrets[k]
    except Exception: return os.getenv(k, d)

st.sidebar.title("Lead-to-Sale")
logged_in = st.session_state.get("user")
pages = ["Inquiry form"] + (["Dashboard", "Outbox"] if logged_in else [])
page = st.sidebar.radio("Menu", pages)

with st.sidebar:
    st.divider()
    if logged_in:
        st.write(f"Logged in: **{logged_in}**")
        if st.button("Logout"): st.session_state.pop("user"); st.rerun()
    else:
        st.subheader("Staff login")
        u = st.text_input("User"); p = st.text_input("Password", type="password")
        if st.button("Login"):
            if u.strip() == secret("DASH_USER", "admin") and p.strip() == secret("DASH_PASS", "admin123"):
                st.session_state["user"] = u.strip(); st.rerun()
            else: st.error("Wrong username or password")

if page == "Inquiry form":
    st.title("Tell us about your project")
    with st.form("inq"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name*"); email = c2.text_input("Email*")
        phone = c1.text_input("Phone"); company = c2.text_input("Company")
        service = st.selectbox("Service", [""] + scoring.SERVICES)
        desc = st.text_area("Project description*", height=150)
        budget = c1.text_input("Budget (e.g. $5000, 300k PKR)"); timeline = c2.text_input("Timeline (e.g. 2 months)")
        if st.form_submit_button("Submit inquiry"):
            try:
                core.create_lead({"name": name.strip(), "email": email.strip(), "phone": phone, "company": company, "service_interest": service,
                                  "description": desc.strip(), "budget": budget, "timeline": timeline}, "web_form")
                st.success("Thank you! We received your inquiry and will send a proposal soon.")
            except ValueError as e: st.error(str(e))

elif page == "Outbox":
    st.title("Outbox (emails)")
    st.dataframe([dict(r) for r in core.q("SELECT id,lead_id,to_addr,subject,kind,status,ts FROM outbox ORDER BY id DESC")])

else:
    import json
    user = st.session_state["user"]
    st.title("Dashboard")
    rows = [dict(r) for r in core.q("SELECT id,name,company,service_type,urgency,score,tier,status FROM leads ORDER BY id DESC")]
    f1, f2 = st.columns(2)
    tier = f1.selectbox("Tier", ["All", "Hot", "Warm", "Cold"]); status = f2.selectbox("Status", ["All"] + sorted({r["status"] for r in rows}))
    shown = [r for r in rows if (tier == "All" or r["tier"] == tier) and (status == "All" or r["status"] == status)]
    st.dataframe(shown, hide_index=True)
    if not rows: st.info("No leads yet. Submit one from the Inquiry form."); st.stop()

    lid = st.selectbox("Open lead #", [r["id"] for r in shown] or [r["id"] for r in rows])
    L = dict(core.q("SELECT * FROM leads WHERE id=?", (lid,), one=True))
    st.header(f"{L['name']}  -  {L['status']}")
    st.caption(f"{L['email']} | {L['company']} | source: {L['source']}")
    st.write(L["description"])
    a, b, c = st.columns(3)
    a.metric("Score", f"{L['score']} ({L['tier']})"); b.metric("Service", L["service_type"]); c.metric("Urgency / Budget", f"{L['urgency']} / {L['budget_band']}")
    if L["needs_review"]: st.warning("Low classification confidence - please review the service type.")
    st.subheader("Why this score")
    for f in json.loads(L["top_factors"] or "[]"): st.write(f"- {f['feature']} = {f['value']} -> {f['impact_points']:+.1f} pts")
    with st.expander("Extracted requirements"): st.json(json.loads(L["requirements"] or "{}"))

    P = core.q("SELECT * FROM proposals WHERE lead_id=? ORDER BY version DESC", (lid,))
    if P:
        cur = json.loads(P[0]["content"])
        st.subheader(f"Proposal v{P[0]['version']} - ${cur['total']:,.2f} ({P[0]['status']})")
        st.dataframe([{"Item": l["description"], "Hours": l["hours"], "Amount": l["amount"]} for l in cur["lines"]], hide_index=True)
        pdf = core.PDF_DIR / f"proposal_{P[0]['id']}.pdf"
        if pdf.exists(): st.download_button("Download proposal PDF", pdf.read_bytes(), file_name=pdf.name, mime="application/pdf")
        if L["status"] == "PENDING_APPROVAL":
            comment = st.text_input("Comment"); disc = st.number_input("Discount % (for revision)", 0.0, 50.0, 0.0)
            b1, b2, b3 = st.columns(3)
            for col, label, d in ((b1, "Approve & send", "approved"), (b2, "Request revision", "revision"), (b3, "Reject", "rejected")):
                if col.button(label):
                    try: core.decide(lid, d, user, comment, disc); st.rerun()
                    except ValueError as e: st.error(str(e))
    if L["status"] == "FOLLOW_UP_ACTIVE":
        st.subheader("Follow-ups")
        st.dataframe([dict(r) for r in core.q("SELECT step,due_at,status FROM followups WHERE lead_id=?", (lid,))], hide_index=True)
        reason = st.text_input("Outcome reason")
        w, l_ = st.columns(2)
        for col, o in ((w, "WON"), (l_, "LOST")):
            if col.button(f"Mark {o.title()}"):
                core.transition(lid, o, user, reason)
                core.q("UPDATE leads SET outcome=?,outcome_reason=? WHERE id=?", (o, reason, lid), commit=True)
                core.q("UPDATE followups SET status='stopped' WHERE lead_id=?", (lid,), commit=True); st.rerun()
    with st.expander("State timeline"):
        st.dataframe([dict(r) for r in core.q("SELECT ts,from_state,to_state,actor,reason FROM history WHERE lead_id=? ORDER BY id", (lid,))], hide_index=True)
