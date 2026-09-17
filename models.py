"""Data access + core business logic for Donate Now.

Money is always integer cents. Pools are virtual balances derived from the
pool_ledger; card balances are derived from card_ledger.
"""
import datetime
import db
import auth
import csv
import io
from services import payments, issuer, notify


# --------------------------------------------------------------------------
# Targets & pools
# --------------------------------------------------------------------------
# A donation target is (type, key):
#   individual -> key = str(recipient_id)
#   city       -> key = "City,ST"
#   state      -> key = "ST"
#   national   -> key = "US"

def pool_balance(conn, pool_type, pool_key):
    row = conn.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN direction='credit' THEN amount_cents ELSE 0 END), 0) -
             COALESCE(SUM(CASE WHEN direction='debit'  THEN amount_cents ELSE 0 END), 0) AS bal
           FROM pool_ledger WHERE pool_type=? AND pool_key=?""",
        (pool_type, pool_key),
    ).fetchone()
    return row["bal"]


def card_balance(conn, card_id):
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS bal FROM card_ledger WHERE card_id=?",
        (card_id,),
    ).fetchone()
    return row["bal"]


def target_label(conn, target_type, target_key):
    if target_type == "individual":
        r = conn.execute("SELECT first_name, last_name FROM recipients WHERE id=?", (target_key,)).fetchone()
        return f"{r['first_name']} {r['last_name'][:1]}." if r else f"Recipient #{target_key}"
    if target_type == "city":
        return f"the {target_key} community pool"
    if target_type == "state":
        return f"the {target_key} state pool"
    return "the national pool"


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
def create_user(email, password, role, name, phone=None, agency_id=None):
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, role, name, phone, agency_id) VALUES (?,?,?,?,?,?)",
            (email.lower().strip(), auth.hash_password(password), role, name, phone, agency_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def user_by_email(email):
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
    conn.close()
    return row


# --------------------------------------------------------------------------
# Recipients & cards (agency side)
# --------------------------------------------------------------------------
def enroll_recipient(agency_id, first_name, last_name, dob, pin, city, state,
                     photo_path=None, public_profile=False, blurb=None):
    conn = db.connect()
    try:
        cur = conn.execute(
            """INSERT INTO recipients
               (agency_id, first_name, last_name, dob, photo_path, pin_hash, city, state, public_profile, blurb, verification_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (agency_id, first_name, last_name, dob, photo_path, auth.hash_pin(pin),
             city, state, 1 if public_profile else 0, blurb, 'pending'),
        )
        rid = cur.lastrowid
        conn.commit()

        # Add default verification checklist items
        default_items = [
            "ID/Photo document uploaded",
            "Proof of address verified",
            "Income verification complete",
            "Background check passed",
            "Case manager interview completed",
            "References checked"
        ]
        for item in default_items:
            conn.execute(
                """INSERT INTO verification_checklist (recipient_id, item) VALUES (?,?)""",
                (rid, item)
            )
        conn.commit()
        return rid
    finally:
        conn.close()


def issue_card_for(recipient_id):
    card = issuer.issue_card()
    conn = db.connect()
    try:
        prev = active_card(conn, recipient_id)
        prev_bal = card_balance(conn, prev["id"]) if prev else 0
        # any existing card becomes 'replaced'
        conn.execute("UPDATE cards SET status='replaced' WHERE recipient_id=? AND status!='replaced'",
                     (recipient_id,))
        cur = conn.execute(
            "INSERT INTO cards (recipient_id, masked_number, token, expiry) VALUES (?,?,?,?)",
            (recipient_id, card["masked_number"], card["token"], card["expiry"]),
        )
        new_id = cur.lastrowid
        if prev_bal > 0:
            # carry the balance from the old card to the replacement
            conn.execute("INSERT INTO card_ledger (card_id, amount_cents, kind, ref) VALUES (?,?,?,?)",
                         (prev["id"], -prev_bal, "transfer_out", f"to card {new_id}"))
            conn.execute("INSERT INTO card_ledger (card_id, amount_cents, kind, ref) VALUES (?,?,?,?)",
                         (new_id, prev_bal, "transfer_in", f"from card {prev['id']}"))
        conn.commit()
        return new_id
    finally:
        conn.close()


def set_card_status(card_id, status):
    conn = db.connect()
    conn.execute("UPDATE cards SET status=? WHERE id=?", (status, card_id))
    conn.commit()
    conn.close()


def active_card(conn, recipient_id):
    return conn.execute(
        "SELECT * FROM cards WHERE recipient_id=? AND status='active' ORDER BY id DESC LIMIT 1",
        (recipient_id,),
    ).fetchone()


def recipients_for_agency(agency_id):
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM recipients WHERE agency_id=? ORDER BY created_at DESC", (agency_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        c = active_card(conn, r["id"])
        d["card"] = dict(c) if c else None
        d["card_balance"] = card_balance(conn, c["id"]) if c else 0
        d["individual_pool"] = pool_balance(conn, "individual", str(r["id"]))
        out.append(d)
    conn.close()
    return out


def public_recipients():
    """Recipients who opted into a public profile -- what donors browse."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM recipients WHERE public_profile=1 AND status='active' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def recipient(recipient_id):
    conn = db.connect()
    row = conn.execute("SELECT * FROM recipients WHERE id=?", (recipient_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_recipient(recipient_id, first_name=None, last_name=None, dob=None, city=None, state=None,
                    public_profile=None, blurb=None, photo_path=None, status=None):
    """Update recipient information. Only provided fields are updated."""
    conn = db.connect()
    try:
        updates = []
        params = []
        if first_name is not None:
            updates.append("first_name=?")
            params.append(first_name)
        if last_name is not None:
            updates.append("last_name=?")
            params.append(last_name)
        if dob is not None:
            updates.append("dob=?")
            params.append(dob)
        if city is not None:
            updates.append("city=?")
            params.append(city)
        if state is not None:
            updates.append("state=?")
            params.append(state)
        if public_profile is not None:
            updates.append("public_profile=?")
            params.append(1 if public_profile else 0)
        if blurb is not None:
            updates.append("blurb=?")
            params.append(blurb)
        if photo_path is not None:
            updates.append("photo_path=?")
            params.append(photo_path)
        if status is not None:
            updates.append("status=?")
            params.append(status)
        if updates:
            params.append(recipient_id)
            sql = f"UPDATE recipients SET {','.join(updates)} WHERE id=?"
            conn.execute(sql, params)
            conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Distribution: move pool funds onto a recipient card
# --------------------------------------------------------------------------
def distribute(pool_type, pool_key, recipient_id, amount_cents, actor_email):
    conn = db.connect()
    try:
        bal = pool_balance(conn, pool_type, pool_key)
        if amount_cents <= 0:
            raise ValueError("Amount must be positive.")
        if amount_cents > bal:
            raise ValueError(f"Pool only holds {fmt_money(bal)}.")
        card = active_card(conn, recipient_id)
        if not card:
            raise ValueError("Recipient has no active card. Issue one first.")

        issuer.load_funds(card["token"], amount_cents)
        conn.execute(
            "INSERT INTO pool_ledger (pool_type, pool_key, amount_cents, direction, ref) VALUES (?,?,?,?,?)",
            (pool_type, pool_key, amount_cents, "debit", f"distribution by {actor_email}"),
        )
        conn.execute(
            "INSERT INTO card_ledger (card_id, amount_cents, kind, ref) VALUES (?,?,?,?)",
            (card["id"], amount_cents, "load", f"from {pool_type} pool {pool_key}"),
        )
        conn.commit()

        r = conn.execute("SELECT * FROM recipients WHERE id=?", (recipient_id,)).fetchone()
        notify.send_sms(_recipient_phone(r), f"Donate Now: {fmt_money(amount_cents)} was loaded onto your card.")
    finally:
        conn.close()


def _recipient_phone(r):
    # Recipients without smartphones have no phone on file; SMS is a no-op then.
    return None


# --------------------------------------------------------------------------
# Donor: payment methods, donations, subscriptions
# --------------------------------------------------------------------------
def add_payment_method(user_id, number, exp, cvc):
    tok = payments.tokenize_card(number, exp, cvc)
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO payment_methods (user_id, brand, last4, exp, token) VALUES (?,?,?,?,?)",
            (user_id, tok["brand"], tok["last4"], tok["exp"], tok["token"]),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def payment_methods(user_id):
    conn = db.connect()
    rows = conn.execute("SELECT * FROM payment_methods WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _resolve_target(conn, target_type, target_key):
    if target_type == "individual":
        r = conn.execute("SELECT * FROM recipients WHERE id=? AND status='active'", (target_key,)).fetchone()
        if not r:
            raise ValueError("That recipient is not available.")
        return str(r["id"])
    if target_type == "city":
        if "," not in target_key:
            raise ValueError("City must look like 'Austin,TX'.")
        return target_key
    if target_type == "state":
        return target_key.upper()
    if target_type == "national":
        return "US"
    raise ValueError("Unknown target.")


def make_donation(donor, target_type, target_key, amount_cents, payment_method_id,
                  cover_fee, subscription_id=None):
    conn = db.connect()
    try:
        pm = conn.execute(
            "SELECT * FROM payment_methods WHERE id=? AND user_id=?",
            (payment_method_id, donor["id"]),
        ).fetchone()
        if not pm:
            raise ValueError("Choose a payment method.")
        if amount_cents < 100:
            raise ValueError("Minimum donation is $1.00.")

        key = _resolve_target(conn, target_type, target_key)
        fee = payments.compute_fee(amount_cents)
        charged = amount_cents + fee if cover_fee else amount_cents
        to_pool = amount_cents if cover_fee else amount_cents - fee

        charge = payments.create_charge(pm["token"], charged, f"Donation to {target_type} {key}")

        conn.execute(
            """INSERT INTO donations
               (donor_id, target_type, target_key, amount_cents, fee_cents, charged_cents,
                to_pool_cents, cover_fee, processor_charge_id, subscription_id, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (donor["id"], target_type, key, amount_cents, fee, charged, to_pool,
             1 if cover_fee else 0, charge["id"], subscription_id, "succeeded"),
        )
        conn.execute(
            "INSERT INTO pool_ledger (pool_type, pool_key, amount_cents, direction, ref) VALUES (?,?,?,?,?)",
            (target_type, key, to_pool, "credit", f"donation {charge['id']}"),
        )
        conn.commit()

        label = target_label(conn, target_type, key)
        notify.send_email(donor["email"], "Thank you for your donation",
                          f"Your gift of {fmt_money(amount_cents)} to {label} was received. "
                          f"Card charged {fmt_money(charged)}.")
        if donor["phone"]:
            notify.send_sms(donor["phone"], f"Donate Now: thanks! {fmt_money(amount_cents)} to {label}.")
        return charge["id"]
    finally:
        conn.close()


def create_subscription(donor, target_type, target_key, amount_cents, payment_method_id, cover_fee, cadence):
    conn = db.connect()
    try:
        key = _resolve_target(conn, target_type, target_key)
        next_run = datetime.date.today().isoformat()
        cur = conn.execute(
            """INSERT INTO subscriptions
               (donor_id, target_type, target_key, amount_cents, cover_fee, cadence, payment_method_id, next_run)
               VALUES (?,?,?,?,?,?,?,?)""",
            (donor["id"], target_type, key, amount_cents, 1 if cover_fee else 0, cadence,
             payment_method_id, next_run),
        )
        conn.commit()
        sub_id = cur.lastrowid
    finally:
        conn.close()
    # charge the first installment immediately
    run_due_subscriptions()
    return sub_id


def cancel_subscription(sub_id, donor_id):
    conn = db.connect()
    conn.execute("UPDATE subscriptions SET status='canceled' WHERE id=? AND donor_id=?", (sub_id, donor_id))
    conn.commit()
    conn.close()


def pause_subscription(sub_id, donor_id):
    """Pause an active subscription."""
    conn = db.connect()
    try:
        sub = conn.execute("SELECT * FROM subscriptions WHERE id=? AND donor_id=?", (sub_id, donor_id)).fetchone()
        if not sub:
            raise ValueError("Subscription not found.")
        if sub["status"] != "active":
            raise ValueError("Can only pause active subscriptions.")
        conn.execute("UPDATE subscriptions SET status='paused' WHERE id=?", (sub_id,))
        conn.commit()
    finally:
        conn.close()


def resume_subscription(sub_id, donor_id):
    """Resume a paused subscription."""
    conn = db.connect()
    try:
        sub = conn.execute("SELECT * FROM subscriptions WHERE id=? AND donor_id=?", (sub_id, donor_id)).fetchone()
        if not sub:
            raise ValueError("Subscription not found.")
        if sub["status"] != "paused":
            raise ValueError("Can only resume paused subscriptions.")
        conn.execute("UPDATE subscriptions SET status='active' WHERE id=?", (sub_id,))
        conn.commit()
    finally:
        conn.close()


def update_subscription(sub_id, donor_id, amount_cents=None, cadence=None):
    """Update subscription amount and/or cadence."""
    conn = db.connect()
    try:
        sub = conn.execute("SELECT * FROM subscriptions WHERE id=? AND donor_id=?", (sub_id, donor_id)).fetchone()
        if not sub:
            raise ValueError("Subscription not found.")
        if sub["status"] == "canceled":
            raise ValueError("Cannot update a canceled subscription.")
        if amount_cents is not None and amount_cents < 100:
            raise ValueError("Minimum donation is $1.00.")

        updates = []
        params = []
        if amount_cents is not None:
            updates.append("amount_cents=?")
            params.append(amount_cents)
        if cadence is not None:
            if cadence not in ("weekly", "biweekly", "monthly"):
                raise ValueError("Invalid cadence.")
            updates.append("cadence=?")
            params.append(cadence)

        if not updates:
            return

        params.append(sub_id)
        sql = f"UPDATE subscriptions SET {', '.join(updates)} WHERE id=?"
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def subscription_total_paid(sub_id):
    """Calculate total amount charged for a subscription (excluding fees)."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) total FROM donations WHERE subscription_id=? AND status='succeeded'",
            (sub_id,),
        ).fetchone()
        return row["total"] if row else 0
    finally:
        conn.close()


def run_due_subscriptions():
    """Process every active subscription whose next_run is due. Idempotent-ish:
    advances next_run after each successful charge."""
    conn = db.connect()
    today = datetime.date.today()
    due = conn.execute(
        "SELECT * FROM subscriptions WHERE status='active' AND next_run <= ?",
        (today.isoformat(),),
    ).fetchall()
    donors = {}
    for s in due:
        d = donors.get(s["donor_id"])
        if not d:
            d = conn.execute("SELECT * FROM users WHERE id=?", (s["donor_id"],)).fetchone()
            donors[s["donor_id"]] = d
    conn.close()

    processed = 0
    for s in due:
        d = donors[s["donor_id"]]
        try:
            make_donation(d, s["target_type"], s["target_key"], s["amount_cents"],
                          s["payment_method_id"], bool(s["cover_fee"]), subscription_id=s["id"])
        except ValueError:
            continue
        if s["cadence"] == "weekly":
            step = datetime.timedelta(days=7)
        elif s["cadence"] == "biweekly":
            step = datetime.timedelta(days=14)
        else:  # monthly
            step = datetime.timedelta(days=30)
        nxt = datetime.date.fromisoformat(s["next_run"]) + step
        c = db.connect()
        c.execute("UPDATE subscriptions SET next_run=? WHERE id=?", (nxt.isoformat(), s["id"]))
        c.commit()
        c.close()
        processed += 1
    return processed


def donations_for_donor(donor_id):
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM donations WHERE donor_id=? ORDER BY created_at DESC", (donor_id,)
    ).fetchall()
    out = [dict(r) for r in rows]
    for r in out:
        r["label"] = target_label(conn, r["target_type"], r["target_key"])
    conn.close()
    return out


def subscriptions_for_donor(donor_id):
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM subscriptions WHERE donor_id=? ORDER BY created_at DESC", (donor_id,)
    ).fetchall()
    out = [dict(r) for r in rows]
    for r in out:
        r["label"] = target_label(conn, r["target_type"], r["target_key"])
    conn.close()
    return out


# --------------------------------------------------------------------------
# Admin dashboard + reconciliation
# --------------------------------------------------------------------------
def dashboard():
    conn = db.connect()
    total = conn.execute(
        "SELECT COALESCE(SUM(amount_cents),0) s, COALESCE(SUM(charged_cents),0) c, "
        "COALESCE(SUM(fee_cents),0) f, COALESCE(SUM(to_pool_cents),0) p, COUNT(*) n "
        "FROM donations WHERE status='succeeded'"
    ).fetchone()
    distributed = conn.execute(
        "SELECT COALESCE(SUM(amount_cents),0) s FROM pool_ledger WHERE direction='debit'"
    ).fetchone()["s"]
    credited = conn.execute(
        "SELECT COALESCE(SUM(amount_cents),0) s FROM pool_ledger WHERE direction='credit'"
    ).fetchone()["s"]
    loaded = conn.execute("SELECT COALESCE(SUM(amount_cents),0) s FROM card_ledger").fetchone()["s"]

    donors = conn.execute(
        """SELECT u.id, u.name, u.email, u.phone,
                  COALESCE(SUM(d.amount_cents),0) lifetime, COUNT(d.id) gifts,
                  MAX(d.created_at) last_donation
           FROM users u LEFT JOIN donations d ON d.donor_id = u.id AND d.status='succeeded'
           WHERE u.role='donor'
           GROUP BY u.id ORDER BY lifetime DESC"""
    ).fetchall()

    payments_hist = conn.execute(
        """SELECT d.*, u.name donor_name, u.email donor_email
           FROM donations d JOIN users u ON u.id = d.donor_id
           ORDER BY d.created_at DESC LIMIT 100"""
    ).fetchall()
    payments_hist = [dict(r) for r in payments_hist]
    for r in payments_hist:
        r["label"] = target_label(conn, r["target_type"], r["target_key"])

    pools = conn.execute(
        """SELECT pool_type, pool_key,
                  SUM(CASE WHEN direction='credit' THEN amount_cents ELSE -amount_cents END) bal
           FROM pool_ledger GROUP BY pool_type, pool_key HAVING bal <> 0 ORDER BY bal DESC"""
    ).fetchall()

    active_subs = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(amount_cents),0) s FROM subscriptions WHERE status='active'"
    ).fetchone()

    # Recipient overview
    recipient_stats = conn.execute(
        """SELECT COUNT(*) total,
                  SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) active,
                  SUM(CASE WHEN status='inactive' THEN 1 ELSE 0 END) inactive
           FROM recipients"""
    ).fetchone()

    # Card status breakdown
    card_stats = conn.execute(
        """SELECT COUNT(*) total,
                  SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) active,
                  SUM(CASE WHEN status='frozen' THEN 1 ELSE 0 END) frozen,
                  SUM(CASE WHEN status='replaced' THEN 1 ELSE 0 END) replaced
           FROM cards"""
    ).fetchone()

    # Top recipients by funding received (individual donations only)
    top_recipients = conn.execute(
        """SELECT r.id, r.first_name, r.last_name, r.city, r.state,
                  COALESCE(SUM(CASE WHEN direction='credit' THEN amount_cents ELSE 0 END), 0) funding
           FROM recipients r
           LEFT JOIN pool_ledger pl ON pl.pool_type='individual' AND pl.pool_key=CAST(r.id AS TEXT)
           GROUP BY r.id ORDER BY funding DESC LIMIT 10"""
    ).fetchall()

    # Recent audit log
    audit_log = conn.execute(
        """SELECT user_id, action, resource, resource_id, details, created_at
           FROM audit_log ORDER BY id DESC LIMIT 20"""
    ).fetchall()

    conn.close()

    return {
        "total_gifts": total["s"],
        "total_charged": total["c"],
        "total_fees": total["f"],
        "total_to_pools": total["p"],
        "donation_count": total["n"],
        "distributed": distributed,
        "credited": credited,
        "loaded": loaded,
        "undistributed": credited - distributed,
        "donors": [dict(r) for r in donors],
        "payments": payments_hist,
        "pools": [dict(r) for r in pools],
        "active_sub_count": active_subs["n"],
        "active_sub_amount": active_subs["s"],
        # reconciliation identities (should each be True)
        "recon_charge": total["c"] == total["f"] + total["p"],
        "recon_pool": credited == total["p"],
        "recon_load": distributed == loaded,
        # New metrics
        "recipient_total": recipient_stats["total"] or 0,
        "recipient_active": recipient_stats["active"] or 0,
        "recipient_inactive": recipient_stats["inactive"] or 0,
        "card_total": card_stats["total"] or 0,
        "card_active": card_stats["active"] or 0,
        "card_frozen": card_stats["frozen"] or 0,
        "card_replaced": card_stats["replaced"] or 0,
        "top_recipients": [dict(r) for r in top_recipients],
        "audit_log": [dict(r) for r in audit_log],
    }


def notifications(limit=100):
    conn = db.connect()
    rows = conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Admin Reports (Phase 2)
# --------------------------------------------------------------------------
def compliance_report(start_date=None, end_date=None, agency_id=None):
    """Generate compliance report: donations by agency/recipient over date range."""
    conn = db.connect()
    try:
        if not start_date:
            start_date = "2000-01-01"
        if not end_date:
            end_date = "2099-12-31"

        if agency_id:
            rows = conn.execute(
                """SELECT a.id, a.name, a.city, a.state,
                          COUNT(DISTINCT d.id) donation_count,
                          SUM(d.amount_cents) total_amount,
                          SUM(d.fee_cents) total_fees,
                          SUM(d.charged_cents) total_charged
                   FROM agencies a
                   LEFT JOIN recipients r ON r.agency_id = a.id
                   LEFT JOIN donations d ON d.target_type='individual' AND d.target_key=CAST(r.id AS TEXT)
                   WHERE a.id=? AND d.created_at BETWEEN ? AND ?
                   GROUP BY a.id""",
                (agency_id, start_date, end_date),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT a.id, a.name, a.city, a.state,
                          COUNT(DISTINCT d.id) donation_count,
                          SUM(d.amount_cents) total_amount,
                          SUM(d.fee_cents) total_fees,
                          SUM(d.charged_cents) total_charged
                   FROM agencies a
                   LEFT JOIN recipients r ON r.agency_id = a.id
                   LEFT JOIN donations d ON d.target_type='individual' AND d.target_key=CAST(r.id AS TEXT)
                   WHERE d.created_at BETWEEN ? AND ?
                   GROUP BY a.id""",
                (start_date, end_date),
            ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def reconciliation_report():
    """Generate reconciliation report: compare charged amounts vs pool credits vs card loads."""
    conn = db.connect()
    try:
        total_charged = conn.execute(
            "SELECT COALESCE(SUM(charged_cents), 0) s FROM donations WHERE status='succeeded'"
        ).fetchone()["s"]

        total_fees = conn.execute(
            "SELECT COALESCE(SUM(fee_cents), 0) s FROM donations WHERE status='succeeded'"
        ).fetchone()["s"]

        total_to_pools = conn.execute(
            "SELECT COALESCE(SUM(to_pool_cents), 0) s FROM donations WHERE status='succeeded'"
        ).fetchone()["s"]

        total_pool_credits = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) s FROM pool_ledger WHERE direction='credit'"
        ).fetchone()["s"]

        total_pool_debits = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) s FROM pool_ledger WHERE direction='debit'"
        ).fetchone()["s"]

        total_card_loads = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) s FROM card_ledger"
        ).fetchone()["s"]

        return {
            "total_charged": total_charged,
            "total_fees": total_fees,
            "total_to_pools": total_to_pools,
            "total_pool_credits": total_pool_credits,
            "total_pool_debits": total_pool_debits,
            "total_card_loads": total_card_loads,
            "check_charge": total_charged == (total_fees + total_to_pools),
            "check_pool_credit": total_pool_credits == total_to_pools,
            "check_pool_debit": total_pool_debits == total_card_loads,
        }
    finally:
        conn.close()


def donor_lifetime_value_report(limit=100):
    """Generate donor retention and lifetime value metrics."""
    conn = db.connect()
    try:
        # Get all donors with metrics
        donors = conn.execute(
            """SELECT u.id, u.name, u.email,
                      COUNT(DISTINCT d.id) donation_count,
                      COALESCE(SUM(d.amount_cents), 0) lifetime_value,
                      COALESCE(SUM(CASE WHEN d.subscription_id IS NOT NULL THEN 1 ELSE 0 END), 0) recurring_count,
                      MAX(d.created_at) last_donation_date,
                      MIN(d.created_at) first_donation_date
               FROM users u
               LEFT JOIN donations d ON d.donor_id = u.id AND d.status='succeeded'
               WHERE u.role = 'donor'
               GROUP BY u.id
               ORDER BY lifetime_value DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        # Calculate retention metrics
        today = datetime.date.today()
        thirty_days_ago = today - datetime.timedelta(days=30)
        ninety_days_ago = today - datetime.timedelta(days=90)
        three_hundred_sixty_days_ago = today - datetime.timedelta(days=365)

        active_30 = conn.execute(
            "SELECT COUNT(DISTINCT donor_id) n FROM donations WHERE created_at > ? AND status='succeeded'",
            (thirty_days_ago.isoformat(),),
        ).fetchone()["n"]

        active_90 = conn.execute(
            "SELECT COUNT(DISTINCT donor_id) n FROM donations WHERE created_at > ? AND status='succeeded'",
            (ninety_days_ago.isoformat(),),
        ).fetchone()["n"]

        active_year = conn.execute(
            "SELECT COUNT(DISTINCT donor_id) n FROM donations WHERE created_at > ? AND status='succeeded'",
            (three_hundred_sixty_days_ago.isoformat(),),
        ).fetchone()["n"]

        return {
            "donors": [dict(d) for d in donors],
            "active_30_days": active_30,
            "active_90_days": active_90,
            "active_365_days": active_year,
            "total_donors": conn.execute(
                "SELECT COUNT(*) n FROM users WHERE role='donor'"
            ).fetchone()["n"],
        }
    finally:
        conn.close()


def top_donors_report(limit=20):
    """Get top donors by lifetime value."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT u.id, u.name, u.email,
                      COUNT(DISTINCT d.id) donation_count,
                      COALESCE(SUM(d.amount_cents), 0) lifetime_value,
                      MAX(d.created_at) last_donation
               FROM users u
               LEFT JOIN donations d ON d.donor_id = u.id AND d.status='succeeded'
               WHERE u.role = 'donor'
               GROUP BY u.id
               ORDER BY lifetime_value DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def top_recipients_report(limit=20):
    """Get top recipients by funding received."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT r.id, r.first_name, r.last_name, r.city, r.state, a.name agency_name,
                      COALESCE(SUM(CASE WHEN pl.direction='credit' THEN pl.amount_cents ELSE 0 END), 0) funding_received,
                      COUNT(DISTINCT pl.id) donation_count
               FROM recipients r
               LEFT JOIN agencies a ON r.agency_id = a.id
               LEFT JOIN pool_ledger pl ON pl.pool_type='individual' AND pl.pool_key=CAST(r.id AS TEXT)
               GROUP BY r.id
               ORDER BY funding_received DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def agency(agency_id):
    conn = db.connect()
    row = conn.execute("SELECT * FROM agencies WHERE id=?", (agency_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# --------------------------------------------------------------------------
# Exports (CSV and PDF)
# --------------------------------------------------------------------------
def export_donations_csv(donor_id):
    """Generate CSV export of all donations for a donor."""
    conn = db.connect()
    try:
        dons = conn.execute(
            """SELECT d.created_at, d.amount_cents, d.charged_cents, d.fee_cents,
                      d.target_type, d.target_key, d.subscription_id, s.cadence
               FROM donations d
               LEFT JOIN subscriptions s ON d.subscription_id = s.id
               WHERE d.donor_id=? AND d.status='succeeded'
               ORDER BY d.created_at DESC""",
            (donor_id,),
        ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Recipient", "Amount", "Fee", "Total Charged", "Type"])

        for d in dons:
            label = target_label(conn, d["target_type"], d["target_key"])
            don_type = f"{d['cadence']}" if d["subscription_id"] else "one-time"
            writer.writerow([
                d["created_at"][:10],
                label,
                fmt_money(d["amount_cents"]),
                fmt_money(d["fee_cents"]),
                fmt_money(d["charged_cents"]),
                don_type,
            ])

        return output.getvalue().encode("utf-8")
    finally:
        conn.close()


def export_donations_pdf(donor_id, donor_name=""):
    """Generate a simple text-based PDF report of donation history."""
    conn = db.connect()
    try:
        dons = conn.execute(
            """SELECT d.created_at, d.amount_cents, d.charged_cents, d.fee_cents,
                      d.target_type, d.target_key, d.subscription_id, s.cadence
               FROM donations d
               LEFT JOIN subscriptions s ON d.subscription_id = s.id
               WHERE d.donor_id=? AND d.status='succeeded'
               ORDER BY d.created_at DESC""",
            (donor_id,),
        ).fetchall()

        # Calculate summary stats
        total_donated = sum(d["amount_cents"] for d in dons)
        total_charged = sum(d["charged_cents"] for d in dons)
        total_fees = sum(d["fee_cents"] for d in dons)
        donation_count = len(dons)

        # Build simple PDF text content
        lines = [
            "%PDF-1.4",
            "1 0 obj",
            "<< /Type /Catalog /Pages 2 0 R >>",
            "endobj",
            "2 0 obj",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "endobj",
            "3 0 obj",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            "endobj",
            "4 0 obj",
            "stream",
        ]

        # PDF content stream (simplified)
        content = f"""BT
/F1 16 Tf
50 750 Td
(Donate Now - Donation History) Tj
0 -30 Td
/F1 12 Tf
(Donor: {donor_name}) Tj
0 -20 Td
(Report Generated: {datetime.date.today()}) Tj
0 -40 Td
(Summary) Tj
0 -20 Td
/F1 10 Tf
(Total Donations: {donation_count}) Tj
0 -15 Td
(Amount Donated: {fmt_money(total_donated)}) Tj
0 -15 Td
(Total Fees: {fmt_money(total_fees)}) Tj
0 -15 Td
(Total Charged: {fmt_money(total_charged)}) Tj
0 -35 Td
/F1 12 Tf
(Donation Details) Tj
0 -20 Td
/F1 9 Tf
"""

        # Add donation rows (simplified for PDF)
        for i, d in enumerate(dons[:50]):  # Limit to 50 for practical PDF size
            label = target_label(conn, d["target_type"], d["target_key"])[:40]
            don_type = f"{d['cadence']}" if d["subscription_id"] else "one-time"
            content += f"({d['created_at'][:10]} | {label} | {fmt_money(d['amount_cents'])}) Tj\n0 -12 Td\n"

        content += "ET"

        lines.append(content)
        lines.append("endstream")
        lines.append("endobj")
        lines.append("5 0 obj")
        lines.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        lines.append("endobj")
        lines.append("xref")
        lines.append("0 6")
        lines.append("0000000000 65535 f")
        lines.append("0000000009 00000 n")
        lines.append("0000000058 00000 n")
        lines.append("0000000115 00000 n")
        lines.append("0000000244 00000 n")
        lines.append("0000001000 00000 n")
        lines.append("trailer")
        lines.append("<< /Size 6 /Root 1 0 R >>")
        lines.append("startxref")
        lines.append("1077")
        lines.append("%%EOF")

        pdf_content = "\n".join(lines)
        return pdf_content.encode("utf-8")
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Verification & Document Management
# --------------------------------------------------------------------------
def get_documents(recipient_id):
    """Get all documents for a recipient."""
    conn = db.connect()
    try:
        docs = conn.execute(
            """SELECT d.*, u.name as uploaded_by_name FROM documents d
               LEFT JOIN users u ON d.uploaded_by=u.id
               WHERE d.recipient_id=? ORDER BY d.created_at DESC""",
            (recipient_id,)
        ).fetchall()
        return [dict(d) for d in docs]
    finally:
        conn.close()


def upload_document(recipient_id, doc_type, file_path, uploaded_by_id, notes=None):
    """Upload a verification document."""
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO documents (recipient_id, doc_type, file_path, uploaded_by, notes)
               VALUES (?,?,?,?,?)""",
            (recipient_id, doc_type, file_path, uploaded_by_id, notes)
        )
        conn.commit()
    finally:
        conn.close()


def get_verification_checklist(recipient_id):
    """Get verification checklist for a recipient."""
    conn = db.connect()
    try:
        items = conn.execute(
            """SELECT * FROM verification_checklist WHERE recipient_id=? ORDER BY id""",
            (recipient_id,)
        ).fetchall()
        return [dict(i) for i in items]
    finally:
        conn.close()


def mark_checklist_item(item_id, checked_by_id):
    """Mark a verification checklist item as complete."""
    conn = db.connect()
    try:
        conn.execute(
            """UPDATE verification_checklist SET is_complete=1, checked_by=?, checked_at=datetime('now')
               WHERE id=?""",
            (checked_by_id, item_id)
        )
        conn.commit()
    finally:
        conn.close()


def unmark_checklist_item(item_id):
    """Unmark a verification checklist item."""
    conn = db.connect()
    try:
        conn.execute(
            """UPDATE verification_checklist SET is_complete=0, checked_by=NULL, checked_at=NULL
               WHERE id=?""",
            (item_id,)
        )
        conn.commit()
    finally:
        conn.close()


def add_checklist_item(recipient_id, item_text):
    """Add a new checklist item for a recipient."""
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO verification_checklist (recipient_id, item) VALUES (?,?)""",
            (recipient_id, item_text)
        )
        conn.commit()
    finally:
        conn.close()


def verify_recipient(recipient_id, verified_by_id):
    """Mark recipient as verified."""
    conn = db.connect()
    try:
        conn.execute(
            """UPDATE recipients SET verification_status='verified', verification_date=datetime('now'),
               verified_by=? WHERE id=?""",
            (verified_by_id, recipient_id)
        )
        conn.commit()
        auth.audit_log(verified_by_id, "recipient_verified", "recipient", recipient_id,
                      "Recipient marked as verified", ip_addr="internal")
    finally:
        conn.close()


def activate_recipient(recipient_id, verified_by_id):
    """Activate a verified recipient."""
    conn = db.connect()
    try:
        conn.execute(
            """UPDATE recipients SET verification_status='active', status='active'
               WHERE id=?""",
            (recipient_id,)
        )
        conn.commit()
        auth.audit_log(verified_by_id, "recipient_activated", "recipient", recipient_id,
                      "Recipient activated", ip_addr="internal")
    finally:
        conn.close()


def reject_recipient(recipient_id, verified_by_id, reason=""):
    """Reject a recipient."""
    conn = db.connect()
    try:
        conn.execute(
            """UPDATE recipients SET verification_status='rejected', status='inactive'
               WHERE id=?""",
            (recipient_id,)
        )
        conn.commit()
        auth.audit_log(verified_by_id, "recipient_rejected", "recipient", recipient_id,
                      f"Recipient rejected: {reason}", ip_addr="internal")
    finally:
        conn.close()


def flag_recipient(recipient_id, flag_type, description, severity, flagged_by_id):
    """Create a flag/incident for a recipient."""
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO flags (recipient_id, flag_type, description, severity, flagged_by)
               VALUES (?,?,?,?,?)""",
            (recipient_id, flag_type, description, severity, flagged_by_id)
        )
        conn.commit()
        conn.execute("UPDATE recipients SET verification_status='flagged' WHERE id=?", (recipient_id,))
        conn.commit()
        auth.audit_log(flagged_by_id, "recipient_flagged", "recipient", recipient_id,
                      f"Flagged as {flag_type}: {description}", ip_addr="internal")
    finally:
        conn.close()


def get_recipient_flags(recipient_id):
    """Get all flags for a recipient."""
    conn = db.connect()
    try:
        flags = conn.execute(
            """SELECT f.*, u1.name as flagged_by_name, u2.name as resolved_by_name
               FROM flags f
               LEFT JOIN users u1 ON f.flagged_by=u1.id
               LEFT JOIN users u2 ON f.resolved_by=u2.id
               WHERE f.recipient_id=? ORDER BY f.created_at DESC""",
            (recipient_id,)
        ).fetchall()
        return [dict(f) for f in flags]
    finally:
        conn.close()


def resolve_flag(flag_id, resolved_by_id, status, notes=""):
    """Resolve/dismiss a flag."""
    conn = db.connect()
    try:
        conn.execute(
            """UPDATE flags SET status=?, resolved_by=?, resolved_at=datetime('now'), notes=?
               WHERE id=?""",
            (status, resolved_by_id, notes, flag_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_approval_queue(agency_id):
    """Get recipients pending verification for an agency."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT r.*, a.name as agency_name
               FROM recipients r
               JOIN agencies a ON r.agency_id=a.id
               WHERE r.agency_id=? AND r.verification_status IN ('pending', 'flagged')
               ORDER BY r.created_at""",
            (agency_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Multi-Agency Management
# --------------------------------------------------------------------------
def get_all_agencies():
    """Get all active agencies."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM agencies WHERE status='active' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_agency_branding(agency_id, logo_path=None, primary_color=None, secondary_color=None):
    """Update agency branding colors and logo."""
    conn = db.connect()
    try:
        updates = []
        params = []
        if logo_path is not None:
            updates.append("logo_path=?")
            params.append(logo_path)
        if primary_color is not None:
            updates.append("primary_color=?")
            params.append(primary_color)
        if secondary_color is not None:
            updates.append("secondary_color=?")
            params.append(secondary_color)
        if updates:
            params.append(agency_id)
            sql = f"UPDATE agencies SET {','.join(updates)} WHERE id=?"
            conn.execute(sql, params)
            conn.commit()
    finally:
        conn.close()


def agency_performance_metrics(agency_id):
    """Get comprehensive performance metrics for an agency."""
    conn = db.connect()
    try:
        ag = conn.execute("SELECT * FROM agencies WHERE id=?", (agency_id,)).fetchone()
        if not ag:
            return None

        metrics = dict(ag) if ag else {}

        # Recipient stats
        recips = conn.execute(
            "SELECT COUNT(*) as cnt FROM recipients WHERE agency_id=?",
            (agency_id,)
        ).fetchone()
        metrics["total_recipients"] = recips["cnt"] if recips else 0

        # Verified recipients
        verified = conn.execute(
            "SELECT COUNT(*) as cnt FROM recipients WHERE agency_id=? AND verification_status IN ('verified', 'active')",
            (agency_id,)
        ).fetchone()
        metrics["verified_recipients"] = verified["cnt"] if verified else 0

        # Total funding received
        funding = conn.execute(
            """SELECT SUM(d.to_pool_cents) as total FROM donations d
               WHERE d.target_type='individual' AND d.target_key IN
               (SELECT CAST(id AS TEXT) FROM recipients WHERE agency_id=?)""",
            (agency_id,)
        ).fetchone()
        metrics["total_funding"] = funding["total"] if funding and funding["total"] else 0

        # Active cards
        cards = conn.execute(
            """SELECT COUNT(*) as cnt FROM cards c
               WHERE c.recipient_id IN (SELECT id FROM recipients WHERE agency_id=?)
               AND c.status='active'""",
            (agency_id,)
        ).fetchone()
        metrics["active_cards"] = cards["cnt"] if cards else 0

        # Total card balance
        balance_sum = conn.execute(
            """SELECT SUM(COALESCE((SELECT SUM(amount_cents) FROM card_ledger WHERE card_id=c.id), 0)) as total
               FROM cards c
               WHERE c.recipient_id IN (SELECT id FROM recipients WHERE agency_id=?)""",
            (agency_id,)
        ).fetchone()
        metrics["total_card_balance"] = balance_sum["total"] if balance_sum and balance_sum["total"] else 0

        return metrics
    finally:
        conn.close()


def compare_agencies():
    """Compare performance across all agencies."""
    agencies = get_all_agencies()
    comparison = []
    for ag in agencies:
        metrics = agency_performance_metrics(ag["id"])
        comparison.append(metrics)
    return comparison


def request_inter_agency_transfer(from_agency_id, to_agency_id, pool_type, pool_key, amount_cents, reason, requested_by_id):
    """Request a transfer of funds from one agency's pool to another."""
    conn = db.connect()
    try:
        # Verify balance exists
        from_balance = pool_balance(conn, pool_type, pool_key)
        if amount_cents > from_balance:
            raise ValueError(f"Insufficient balance. Available: {fmt_money(from_balance)}")

        conn.execute(
            """INSERT INTO inter_agency_transfers
               (from_agency_id, to_agency_id, pool_type, pool_key, amount_cents, reason, requested_by)
               VALUES (?,?,?,?,?,?,?)""",
            (from_agency_id, to_agency_id, pool_type, pool_key, amount_cents, reason, requested_by_id)
        )
        conn.commit()
        auth.audit_log(requested_by_id, "transfer_request", "inter_agency", from_agency_id,
                      f"to_agency={to_agency_id}, amount={amount_cents}", ip_addr="internal")
    finally:
        conn.close()


def approve_inter_agency_transfer(transfer_id, approved_by_id):
    """Approve an inter-agency transfer and move the funds."""
    conn = db.connect()
    try:
        transfer = conn.execute(
            "SELECT * FROM inter_agency_transfers WHERE id=?", (transfer_id,)
        ).fetchone()
        if not transfer:
            raise ValueError("Transfer not found.")
        if transfer["status"] != "pending":
            raise ValueError("Transfer already processed.")

        # Move funds: debit from source pool, credit to destination pool
        conn.execute(
            """INSERT INTO pool_ledger (pool_type, pool_key, amount_cents, direction, ref)
               VALUES (?,?,?,?,?)""",
            (transfer["pool_type"], transfer["pool_key"], transfer["amount_cents"], "debit",
             f"transfer_to_agency_{transfer['to_agency_id']}")
        )

        # Create new pool key for destination agency
        dest_key = f"{transfer['pool_key']}_from_agency_{transfer['from_agency_id']}"
        conn.execute(
            """INSERT INTO pool_ledger (pool_type, pool_key, amount_cents, direction, ref)
               VALUES (?,?,?,?,?)""",
            (transfer["pool_type"], dest_key, transfer["amount_cents"], "credit",
             f"transfer_from_agency_{transfer['from_agency_id']}")
        )

        # Mark transfer as approved
        conn.execute(
            """UPDATE inter_agency_transfers SET status='approved', approved_by=?, approved_at=datetime('now')
               WHERE id=?""",
            (approved_by_id, transfer_id)
        )
        conn.commit()
        auth.audit_log(approved_by_id, "transfer_approved", "inter_agency", transfer_id,
                      f"from={transfer['from_agency_id']}, to={transfer['to_agency_id']}, amount={transfer['amount_cents']}", ip_addr="internal")
    finally:
        conn.close()


def get_pending_transfers(agency_id=None):
    """Get pending inter-agency transfers."""
    conn = db.connect()
    try:
        if agency_id:
            rows = conn.execute(
                """SELECT t.*, a1.name as from_agency_name, a2.name as to_agency_name, u.name as requested_by_name
                   FROM inter_agency_transfers t
                   JOIN agencies a1 ON t.from_agency_id=a1.id
                   JOIN agencies a2 ON t.to_agency_id=a2.id
                   JOIN users u ON t.requested_by=u.id
                   WHERE t.status='pending' AND (t.from_agency_id=? OR t.to_agency_id=?)
                   ORDER BY t.created_at DESC""",
                (agency_id, agency_id)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT t.*, a1.name as from_agency_name, a2.name as to_agency_name, u.name as requested_by_name
                   FROM inter_agency_transfers t
                   JOIN agencies a1 ON t.from_agency_id=a1.id
                   JOIN agencies a2 ON t.to_agency_id=a2.id
                   JOIN users u ON t.requested_by=u.id
                   WHERE t.status='pending'
                   ORDER BY t.created_at DESC"""
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Analytics & Reporting
# --------------------------------------------------------------------------
def spending_by_category(agency_id=None, days=30):
    """Analyze spending by mock category (based on card balance changes)."""
    conn = db.connect()
    try:
        # Mock spending analysis: simulate categories based on recipient patterns
        categories = {
            "Food & Groceries": 0,
            "Transportation": 0,
            "Healthcare": 0,
            "Housing": 0,
            "Utilities": 0,
            "Other": 0
        }

        # Get recipients for agency
        if agency_id:
            recips = conn.execute(
                "SELECT id FROM recipients WHERE agency_id=?", (agency_id,)
            ).fetchall()
            recip_ids = tuple(r["id"] for r in recips)
            if not recip_ids:
                return categories
        else:
            recip_ids = None

        # Calculate card balances and changes (mock spending analysis)
        for recip_id in (recip_ids if recip_ids else
                         [r["id"] for r in conn.execute("SELECT id FROM recipients").fetchall()]):
            card = conn.execute(
                "SELECT id FROM cards WHERE recipient_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (recip_id,)
            ).fetchone()
            if card:
                bal = card_balance(conn, card["id"])
                # Mock: distribute balance across categories
                if bal > 0:
                    categories["Food & Groceries"] += int(bal * 0.35)
                    categories["Transportation"] += int(bal * 0.25)
                    categories["Healthcare"] += int(bal * 0.15)
                    categories["Housing"] += int(bal * 0.15)
                    categories["Utilities"] += int(bal * 0.05)
                    categories["Other"] += bal - sum([
                        int(bal * 0.35), int(bal * 0.25), int(bal * 0.15),
                        int(bal * 0.15), int(bal * 0.05)
                    ])

        return categories
    finally:
        conn.close()


def spending_trends(agency_id=None, days=30):
    """Spending trends over time (daily breakdown)."""
    conn = db.connect()
    try:
        # Get donations from past N days
        start_date = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()[:10]

        if agency_id:
            recips = conn.execute(
                "SELECT id FROM recipients WHERE agency_id=?", (agency_id,)
            ).fetchall()
            recip_ids = tuple(r["id"] for r in recips)
            if not recip_ids:
                return {}
            placeholders = ",".join("?" * len(recip_ids))
            rows = conn.execute(f"""
                SELECT DATE(created_at) as date, SUM(to_pool_cents) as total
                FROM donations
                WHERE created_at >= ? AND target_key IN ({placeholders})
                GROUP BY DATE(created_at)
                ORDER BY date
            """, [start_date] + list(recip_ids)).fetchall()
        else:
            rows = conn.execute("""
                SELECT DATE(created_at) as date, SUM(to_pool_cents) as total
                FROM donations
                WHERE created_at >= ?
                GROUP BY DATE(created_at)
                ORDER BY date
            """, (start_date,)).fetchall()

        trends = {}
        for row in rows:
            trends[row["date"]] = row["total"] or 0

        return trends
    finally:
        conn.close()


def recipient_compliance_score(recipient_id):
    """Calculate compliance score (0-100) based on card activity."""
    conn = db.connect()
    try:
        r = conn.execute("SELECT * FROM recipients WHERE id=?", (recipient_id,)).fetchone()
        if not r:
            return 0

        score = 100
        card = active_card(conn, recipient_id)
        if not card:
            return 50  # No card = lower score

        if card["status"] != "active":
            score -= 20

        bal = card_balance(conn, card["id"])
        if bal == 0 and r["created_at"][:10] < (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()[:10]:
            score -= 10  # Old recipient with zero balance

        # Check for spending activity
        ledger = conn.execute(
            "SELECT COUNT(*) as cnt FROM card_ledger WHERE card_id=? AND kind='load'",
            (card["id"],)
        ).fetchone()
        if ledger["cnt"] == 0:
            score -= 15  # No fund loads

        return max(0, score)
    finally:
        conn.close()


def top_recipients_by_funding(agency_id=None, limit=10):
    """Top recipients by total funds received."""
    conn = db.connect()
    try:
        if agency_id:
            rows = conn.execute("""
                SELECT r.id, r.first_name, r.last_name, r.city, r.state,
                       SUM(d.to_pool_cents) as total_funding
                FROM recipients r
                LEFT JOIN donations d ON d.target_type='individual' AND d.target_key=CAST(r.id AS TEXT)
                WHERE r.agency_id=?
                GROUP BY r.id
                ORDER BY total_funding DESC
                LIMIT ?
            """, (agency_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT r.id, r.first_name, r.last_name, r.city, r.state,
                       SUM(d.to_pool_cents) as total_funding
                FROM recipients r
                LEFT JOIN donations d ON d.target_type='individual' AND d.target_key=CAST(r.id AS TEXT)
                GROUP BY r.id
                ORDER BY total_funding DESC
                LIMIT ?
            """, (limit,)).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def card_activity_summary(agency_id=None):
    """Summary of card statuses and activity."""
    conn = db.connect()
    try:
        if agency_id:
            recips = conn.execute(
                "SELECT id FROM recipients WHERE agency_id=?", (agency_id,)
            ).fetchall()
            recip_ids = tuple(r["id"] for r in recips)
            if not recip_ids:
                return {"active": 0, "frozen": 0, "replaced": 0, "total_balance": 0}
            placeholders = ",".join("?" * len(recip_ids))
            summary = conn.execute(f"""
                SELECT status, COUNT(*) as cnt, SUM(
                    (SELECT COALESCE(SUM(amount_cents), 0) FROM card_ledger WHERE card_id=c.id)
                ) as total_bal
                FROM cards c
                WHERE recipient_id IN ({placeholders})
                GROUP BY status
            """, list(recip_ids)).fetchall()
        else:
            summary = conn.execute("""
                SELECT status, COUNT(*) as cnt, SUM(
                    (SELECT COALESCE(SUM(amount_cents), 0) FROM card_ledger WHERE card_id=c.id)
                ) as total_bal
                FROM cards c
                GROUP BY status
            """).fetchall()

        result = {"active": 0, "frozen": 0, "replaced": 0, "total_balance": 0}
        for row in summary:
            result[row["status"]] = row["cnt"]
            result["total_balance"] += row["total_bal"] or 0

        return result
    finally:
        conn.close()


# --------------------------------------------------------------------------
def fmt_money(cents):
    return f"${cents / 100:,.2f}"


# --------------------------------------------------------------------------
# Meme Coin Trading
# --------------------------------------------------------------------------
def get_latest_coins(limit=50, min_risk=None, order_by="discovered_at DESC"):
    """Get latest coins with optional risk filter"""
    conn = db.connect()
    try:
        query = "SELECT c.*, ca.overall_risk_score, ca.recommendation FROM coins c LEFT JOIN coin_analysis ca ON c.id=ca.coin_id WHERE c.marked_scam=0"
        params = []

        if min_risk is not None:
            query += " AND (ca.overall_risk_score IS NULL OR ca.overall_risk_score <= ?)"
            params.append(min_risk)

        query += f" ORDER BY {order_by} LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def coin_by_address(address):
    """Get coin by token address"""
    conn = db.connect()
    try:
        coin = conn.execute("SELECT * FROM coins WHERE token_address=?", (address,)).fetchone()
        if not coin:
            return None
        analysis = conn.execute("SELECT * FROM coin_analysis WHERE coin_id=?", (coin["id"],)).fetchone()
        return {"coin": dict(coin), "analysis": dict(analysis) if analysis else None}
    finally:
        conn.close()


def coin_by_id(coin_id):
    """Get coin by ID"""
    conn = db.connect()
    try:
        return conn.execute("SELECT * FROM coins WHERE id=?", (coin_id,)).fetchone()
    finally:
        conn.close()


def analysis_for_coin(coin_id):
    """Get analysis for a coin"""
    conn = db.connect()
    try:
        return conn.execute("SELECT * FROM coin_analysis WHERE coin_id=?", (coin_id,)).fetchone()
    finally:
        conn.close()


def insert_coin(token_address, name=None, symbol=None, description=None,
                creator_wallet=None, pump_url=None, market_cap=None, holder_count=None):
    """Insert new coin to database"""
    conn = db.connect()
    try:
        cur = conn.execute(
            """INSERT INTO coins
               (token_address, name, symbol, description, creator_wallet, pump_url, market_cap, holder_count)
               VALUES (?,?,?,?,?,?,?,?)""",
            (token_address, name, symbol, description, creator_wallet, pump_url, market_cap, holder_count)
        )
        coin_id = cur.lastrowid
        conn.commit()
        return coin_id
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            # Coin already exists - update it with new data
            conn.close()
            conn = db.connect()
            result = conn.execute("SELECT id FROM coins WHERE token_address=?", (token_address,)).fetchone()
            coin_id = result["id"] if result else None

            if coin_id and (market_cap is not None or holder_count is not None):
                # Update existing coin with new values (only if they're better/non-zero)
                updates = []
                params = []
                # Only update market_cap if it's non-zero (better data)
                if market_cap and market_cap > 0:
                    updates.append("market_cap=?")
                    params.append(market_cap)
                # Only update holder_count if it's non-zero (better data)
                if holder_count and holder_count > 0:
                    updates.append("holder_count=?")
                    params.append(holder_count)
                # Always update name/symbol if provided (they don't have zero values)
                if name is not None:
                    updates.append("name=?")
                    params.append(name)
                if symbol is not None:
                    updates.append("symbol=?")
                    params.append(symbol)

                if updates:
                    params.append(coin_id)
                    query = f"UPDATE coins SET {', '.join(updates)}, last_updated=datetime('now') WHERE id=?"
                    conn.execute(query, params)
                    conn.commit()

            conn.close()
            return coin_id
        raise
    finally:
        if conn:
            conn.close()


def update_coin(coin_id, **kwargs):
    """Update coin metrics"""
    conn = db.connect()
    try:
        updates = []
        params = []
        for key, val in kwargs.items():
            if key in ['price', 'liquidity_sol', 'volume_24h', 'holder_count', 'market_cap',
                      'replies_count', 'views', 'name', 'symbol', 'description']:
                updates.append(f"{key}=?")
                params.append(val)

        if updates:
            params.append(coin_id)
            query = f"UPDATE coins SET {', '.join(updates)}, last_updated=datetime('now') WHERE id=?"
            conn.execute(query, params)
            conn.commit()
    finally:
        conn.close()


def update_coin_analysis(coin_id, rug_pull_score, honeypot_score, scam_score,
                        community_score, liquidity_score, dev_wallet_percentage=None,
                        is_liquidity_locked=None, is_mint_renounced=None,
                        has_anti_whale=None, is_contract_verified=None, recommendation=None,
                        analysis_notes=None):
    """Insert or update coin analysis"""
    conn = db.connect()
    try:
        # Calculate overall risk as weighted average
        overall_risk_score = (rug_pull_score * 0.35 + honeypot_score * 0.25 +
                             scam_score * 0.25 + community_score * 0.1 +
                             liquidity_score * 0.05)

        existing = conn.execute("SELECT id FROM coin_analysis WHERE coin_id=?", (coin_id,)).fetchone()

        if existing:
            conn.execute(
                """UPDATE coin_analysis SET
                   rug_pull_score=?, honeypot_score=?, scam_score=?, community_score=?,
                   liquidity_score=?, overall_risk_score=?, dev_wallet_percentage=?,
                   is_liquidity_locked=?, is_mint_renounced=?, has_anti_whale=?,
                   is_contract_verified=?, recommendation=?, analysis_notes=?,
                   analyzed_at=datetime('now')
                   WHERE coin_id=?""",
                (rug_pull_score, honeypot_score, scam_score, community_score, liquidity_score,
                 overall_risk_score, dev_wallet_percentage, is_liquidity_locked,
                 is_mint_renounced, has_anti_whale, is_contract_verified, recommendation,
                 analysis_notes, coin_id)
            )
        else:
            conn.execute(
                """INSERT INTO coin_analysis
                   (coin_id, rug_pull_score, honeypot_score, scam_score, community_score,
                    liquidity_score, overall_risk_score, dev_wallet_percentage, is_liquidity_locked,
                    is_mint_renounced, has_anti_whale, is_contract_verified, recommendation,
                    analysis_notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (coin_id, rug_pull_score, honeypot_score, scam_score, community_score,
                 liquidity_score, overall_risk_score, dev_wallet_percentage, is_liquidity_locked,
                 is_mint_renounced, has_anti_whale, is_contract_verified, recommendation,
                 analysis_notes)
            )
        conn.commit()
    finally:
        conn.close()


def add_to_watchlist(user_id, coin_id, alert_price=None):
    """Add coin to user's watchlist"""
    conn = db.connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO user_watchlist (user_id, coin_id, alert_price) VALUES (?,?,?)",
            (user_id, coin_id, alert_price)
        )
        conn.commit()
    finally:
        conn.close()


def remove_from_watchlist(user_id, coin_id):
    """Remove coin from user's watchlist"""
    conn = db.connect()
    try:
        conn.execute("DELETE FROM user_watchlist WHERE user_id=? AND coin_id=?", (user_id, coin_id))
        conn.commit()
    finally:
        conn.close()


def get_user_watchlist(user_id):
    """Get user's watchlist with analysis"""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT w.*, c.*, ca.overall_risk_score, ca.recommendation
               FROM user_watchlist w
               JOIN coins c ON w.coin_id=c.id
               LEFT JOIN coin_analysis ca ON c.id=ca.coin_id
               WHERE w.user_id=?
               ORDER BY w.added_at DESC""",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def log_trade(user_id, coin_id, action, amount_sol, price_at_trade=None,
             entry_price=None, exit_price=None, profit_loss_sol=None, notes=None, tx_signature=None):
    """Log a trade (manual record keeping, not execution)"""
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO user_trades
               (user_id, coin_id, action, amount_sol, price_at_trade, entry_price, exit_price,
                profit_loss_sol, notes, tx_signature)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user_id, coin_id, action, amount_sol, price_at_trade, entry_price, exit_price,
             profit_loss_sol, notes, tx_signature)
        )
        conn.commit()
    finally:
        conn.close()


def get_user_trades(user_id, limit=100):
    """Get user's trade history"""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT t.*, c.name, c.symbol, c.token_address
               FROM user_trades t
               JOIN coins c ON t.coin_id=c.id
               WHERE t.user_id=?
               ORDER BY t.traded_at DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_coin_scam(coin_id, reason):
    """Mark a coin as a scam"""
    conn = db.connect()
    try:
        conn.execute("UPDATE coins SET marked_scam=1, scam_reason=? WHERE id=?", (reason, coin_id))
        conn.commit()
    finally:
        conn.close()
