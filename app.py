#!/usr/bin/env python3
"""Netanya Padel - רישום ותפעול טורנירי פאדל"""

import functools
import json
import os
import random
import ssl
import string
import urllib.error
import urllib.request
from urllib.parse import quote

from flask import (Flask, flash, jsonify, redirect, render_template, request,
                    session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import tournament_engine as engine

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SERVICE_KEY    = os.environ.get("SUPABASE_SERVICE_KEY", "")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")

STAGE_LABELS = {
    "group": "שלב הבתים",
    "quarterfinal": "רבע גמר",
    "semifinal": "חצי גמר",
    "final": "גמר",
}
app.jinja_env.globals["STAGE_LABELS"] = STAGE_LABELS
STAGE_SORT_ORDER = {"group": 0, "quarterfinal": 1, "semifinal": 2, "final": 3}

STATUS_LABELS = {
    "open": "פתוח להרשמה",
    "full": "הגרלה בוצעה",
    "in_progress": "בעיצומו",
    "completed": "הסתיים",
}
app.jinja_env.globals["STATUS_LABELS"] = STATUS_LABELS

_ssl_ctx = ssl.create_default_context()


# ─── Supabase REST helpers ─────────────────────────────────────────────────
def _request(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else []
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {method} {url}: {e.read().decode()}")


def _supa(method, path, body=None):
    if not SERVICE_KEY or not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not configured")
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    return _request(method, f"{SUPABASE_URL}{path}", body, headers)


def db_get(path):
    return _supa("GET", path)


def db_insert(table, row):
    result = _supa("POST", f"/rest/v1/{table}", row)
    return result[0] if isinstance(result, list) and result else result


def db_insert_many(table, rows):
    if not rows:
        return []
    return _supa("POST", f"/rest/v1/{table}", rows)


def db_patch(table, filter_qs, updates):
    return _supa("PATCH", f"/rest/v1/{table}?{filter_qs}", updates)


# ─── Data access ────────────────────────────────────────────────────────────
def get_user_by_id(user_id):
    rows = db_get(f"/rest/v1/padel_users?id=eq.{quote(user_id)}&select=*")
    return rows[0] if rows else None


def get_user_by_username(username):
    rows = db_get(f"/rest/v1/padel_users?username=eq.{quote(username)}&select=*")
    return rows[0] if rows else None


def update_user(user_id, updates):
    db_patch("padel_users", f"id=eq.{user_id}", updates)


def list_users():
    return db_get("/rest/v1/padel_users?select=*&order=created_at.desc")


def search_users(q, exclude_ids=()):
    like = quote(f"%{q}%")
    rows = db_get(
        f"/rest/v1/padel_users?or=(username.ilike.{like},phone.ilike.{like})"
        f"&select=id,username,phone&order=username.asc&limit=10"
    )
    return [r for r in rows if r["id"] not in exclude_ids]


def create_user(username, phone, password, is_admin=False):
    return db_insert("padel_users", {
        "username": username,
        "phone": phone,
        "password_hash": generate_password_hash(password),
        "is_admin": is_admin,
    })


def list_tournaments():
    return db_get("/rest/v1/padel_tournaments?select=*&order=date.desc")


def get_tournament(tid):
    rows = db_get(f"/rest/v1/padel_tournaments?id=eq.{quote(tid)}&select=*")
    return rows[0] if rows else None


def create_tournament(name, date, level, pairs_count, game_target, created_by):
    return db_insert("padel_tournaments", {
        "name": name, "date": date, "level": level,
        "pairs_count": pairs_count, "groups_count": pairs_count // 4,
        "game_target": game_target, "status": "open", "created_by": created_by,
    })


def update_tournament_status(tid, status, winner_pair_id=None):
    updates = {"status": status}
    if winner_pair_id is not None:
        updates["winner_pair_id"] = winner_pair_id
    db_patch("padel_tournaments", f"id=eq.{tid}", updates)


def delete_pairs(pair_ids):
    if not pair_ids:
        return
    ids = ",".join(pair_ids)
    _supa("DELETE", f"/rest/v1/padel_pairs?id=in.({ids})")


def list_pairs(tid):
    return db_get(f"/rest/v1/padel_pairs?tournament_id=eq.{quote(tid)}&select=*&order=created_at.asc")


def list_pairs_for_user(user_id):
    uid = quote(user_id)
    return db_get(
        f"/rest/v1/padel_pairs?or=(player1_id.eq.{uid},player2_id.eq.{uid})"
        f"&select=*&order=created_at.desc"
    )


def create_pair(tournament_id, p1_id, p1_name, p1_phone, p2_id, p2_name, p2_phone, added_by):
    return db_insert("padel_pairs", {
        "tournament_id": tournament_id,
        "player1_id": p1_id, "player1_name": p1_name, "player1_phone": p1_phone,
        "player2_id": p2_id, "player2_name": p2_name, "player2_phone": p2_phone,
        "added_by": added_by,
    })


def update_pair_group(pid, group_number):
    db_patch("padel_pairs", f"id=eq.{pid}", {"group_number": group_number})


def list_matches(tid):
    return db_get(
        f"/rest/v1/padel_matches?tournament_id=eq.{quote(tid)}"
        f"&select=*&order=stage.asc,group_number.asc,match_index.asc"
    )


def get_match(mid):
    rows = db_get(f"/rest/v1/padel_matches?id=eq.{quote(mid)}&select=*")
    return rows[0] if rows else None


def create_matches(rows):
    if rows:
        db_insert_many("padel_matches", rows)


def update_match_score(mid, score_a, score_b, winner_pair_id):
    db_patch("padel_matches", f"id=eq.{mid}", {
        "score_a": score_a, "score_b": score_b, "winner_pair_id": winner_pair_id,
    })


# ─── Auth ───────────────────────────────────────────────────────────────────
def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


# ─── Tournament engine glue ─────────────────────────────────────────────────
def maybe_run_draw(tournament):
    """If the tournament just filled up, shuffle pairs into groups and create group matches."""
    pairs = list_pairs(tournament["id"])
    if len(pairs) < tournament["pairs_count"]:
        return
    pair_ids = [p["id"] for p in pairs]
    assignments, matches = engine.run_draw(pair_ids)
    for pid, group_number in assignments.items():
        update_pair_group(pid, group_number)
    create_matches([
        {**m, "tournament_id": tournament["id"], "game_target": tournament["game_target"]}
        for m in matches
    ])
    update_tournament_status(tournament["id"], "full")


def stage_order_for(tournament):
    return ["group"] + (["quarterfinal"] if tournament["groups_count"] == 4 else []) + ["semifinal", "final"]


def editable_stages(tournament, matches):
    """A stage's scores stay editable as long as nothing 'real' has been decided downstream
    of it yet. Once any match in a later stage has a recorded winner, everything upstream of
    it locks - editing it would silently invalidate a result that already happened."""
    order = stage_order_for(tournament)
    editable = set()
    for i, stage in enumerate(order):
        stage_matches = [m for m in matches if m["stage"] == stage]
        if not stage_matches:
            continue
        downstream_played = any(
            m["winner_pair_id"] is not None
            for later_stage in order[i + 1:]
            for m in matches if m["stage"] == later_stage
        )
        if not downstream_played:
            editable.add(stage)
    return editable


def delete_matches(match_ids):
    if not match_ids:
        return
    ids = ",".join(match_ids)
    _supa("DELETE", f"/rest/v1/padel_matches?id=in.({ids})")


def delete_tournament(tid):
    """Cascade delete: clear the tournament's winner_pair_id (it FKs into padel_pairs, so it
    has to go before the pairs do), then matches, then pairs, then the tournament row itself."""
    db_patch("padel_tournaments", f"id=eq.{tid}", {"winner_pair_id": None})
    delete_matches([m["id"] for m in list_matches(tid)])
    delete_pairs([p["id"] for p in list_pairs(tid)])
    _supa("DELETE", f"/rest/v1/padel_tournaments?id=eq.{tid}")


def _latest_complete_stage(tournament, matches):
    """The furthest stage that has matches AND all of them have a recorded winner.
    Returns None if no stage is fully complete yet, or if that stage is already the final
    (nothing left to advance to)."""
    order = stage_order_for(tournament)
    current_stage = None
    for stage in order:
        if any(m["stage"] == stage for m in matches):
            current_stage = stage
    if current_stage is None or current_stage == order[-1]:
        return None
    stage_matches = [m for m in matches if m["stage"] == current_stage]
    if any(m["winner_pair_id"] is None for m in stage_matches):
        return None
    return current_stage


def stage_pending_advance(tournament, matches):
    """The name of the next stage if the current stage just finished but the admin hasn't
    picked a game target and advanced yet - i.e. the UI should prompt for one. None otherwise."""
    order = stage_order_for(tournament)
    complete_stage = _latest_complete_stage(tournament, matches)
    if complete_stage is None:
        return None
    next_stage_name = order[order.index(complete_stage) + 1]
    if any(m["stage"] == next_stage_name for m in matches):
        return None  # already advanced
    return next_stage_name


def _tiebreak_winners_by_group(tid):
    """{group_number: {frozenset({pair_a, pair_b}): winner_pair_id}} from completed tiebreak matches."""
    by_group = {}
    for m in list_matches(tid):
        if m["stage"] != "tiebreak" or m["winner_pair_id"] is None:
            continue
        by_group.setdefault(m["group_number"], {})[frozenset((m["pair_a_id"], m["pair_b_id"]))] = m["winner_pair_id"]
    return by_group


def _next_stage_matches(tournament, from_stage, stage_matches, pairs):
    """Pure computation of what the next stage's matches should be, given `from_stage` is
    fully complete. Returns (next_stage_name_or_None, [match dicts without game_target/tournament_id])."""
    groups_count = tournament["groups_count"]
    if from_stage == "group":
        tiebreaks_by_group = _tiebreak_winners_by_group(tournament["id"])
        standings_by_group = {}
        for g in range(1, groups_count + 1):
            group_pair_ids = [p["id"] for p in pairs if p["group_number"] == g]
            group_matches = [m for m in stage_matches if m["group_number"] == g]
            ranked_ids, _ = engine.compute_group_standings(
                group_pair_ids, group_matches, tiebreaks_by_group.get(g))
            standings_by_group[g] = ranked_ids
        return engine.generate_next_stage(
            tournament["pairs_count"], groups_count, "group", standings_by_group=standings_by_group)
    winners = [m["winner_pair_id"] for m in stage_matches]
    return engine.generate_next_stage(
        tournament["pairs_count"], groups_count, from_stage, stage_winner_ids_in_order=winners)


def advance_to_next_stage(tournament, game_target):
    """Admin-triggered: the current stage just finished and nothing has been generated for
    the next one yet. Creates the next stage's matches with the chosen game_target."""
    tid = tournament["id"]
    matches = list_matches(tid)
    from_stage = _latest_complete_stage(tournament, matches)
    if from_stage is None:
        return
    order = stage_order_for(tournament)
    next_stage_name = order[order.index(from_stage) + 1]
    if any(m["stage"] == next_stage_name for m in matches):
        return  # already advanced - never overwrite

    pairs = list_pairs(tid)
    stage_matches = sorted([m for m in matches if m["stage"] == from_stage], key=lambda m: m["match_index"])
    next_stage, next_matches = _next_stage_matches(tournament, from_stage, stage_matches, pairs)
    if next_stage is None:
        return
    rows = [{**m, "tournament_id": tid, "stage": next_stage, "game_target": game_target} for m in next_matches]
    create_matches(rows)


def recompute_from_stage(tournament, edited_stage):
    """Called after a score is saved for a match in `edited_stage`. If that stage is now fully
    complete AND the admin already advanced past it (the next stage's matches exist), regenerates
    those next-stage matches from the fresh results - keeping the game_target already chosen for
    them. If the admin hasn't advanced yet, does nothing (that's a manual action, see
    advance_to_next_stage). By the editable_stages() rule this is only ever reached while the
    next-stage matches are still entirely unplayed, so nothing real is lost."""
    tid = tournament["id"]
    order = stage_order_for(tournament)
    if edited_stage not in order:
        return

    matches = list_matches(tid)

    if edited_stage == order[-1]:  # editing the final
        final_matches = [m for m in matches if m["stage"] == "final"]
        if final_matches and final_matches[0]["winner_pair_id"]:
            update_tournament_status(tid, "completed", winner_pair_id=final_matches[0]["winner_pair_id"])
        return

    pairs = list_pairs(tid)
    stage_matches = sorted([m for m in matches if m["stage"] == edited_stage], key=lambda m: m["match_index"])
    if any(m["winner_pair_id"] is None for m in stage_matches):
        return  # stage not complete yet, nothing to (re)generate

    next_stage_name = order[order.index(edited_stage) + 1]
    existing_next = [m for m in matches if m["stage"] == next_stage_name]
    if not existing_next:
        return  # admin hasn't advanced to this stage yet - leave it for advance_to_next_stage
    if any(m["winner_pair_id"] is not None for m in existing_next):
        return  # downstream already has a real result - never touch it

    game_target = existing_next[0]["game_target"]
    next_stage, next_matches = _next_stage_matches(tournament, edited_stage, stage_matches, pairs)
    delete_matches([m["id"] for m in existing_next])

    if next_stage is None:
        update_tournament_status(tid, "completed", winner_pair_id=stage_matches[0]["winner_pair_id"])
        return

    rows = [{**m, "tournament_id": tid, "stage": next_stage, "game_target": game_target} for m in next_matches]
    create_matches(rows)


def resolve_player_slot(form, prefix, allow_new):
    """Resolve one side of a pair from form data. Returns (user_id_or_None, name, phone).
    Raises ValueError with a Hebrew message the caller can flash straight to the user."""
    mode = form.get(f"{prefix}_mode", "guest")

    if mode == "existing":
        uid = form.get(f"{prefix}_user_id", "").strip()
        if not uid:
            raise ValueError("יש לבחור משתמש קיים מהרשימה")
        user = get_user_by_id(uid)
        if not user:
            raise ValueError("המשתמש שנבחר לא נמצא")
        return user["id"], user["username"], user["phone"]

    if mode == "guest":
        name = form.get(f"{prefix}_guest_name", "").strip()
        phone = form.get(f"{prefix}_guest_phone", "").strip()
        if not name:
            raise ValueError("יש להזין שם משתתף/ת")
        return None, name, phone or "לא צוין"

    if mode == "new" and allow_new:
        username = form.get(f"{prefix}_new_username", "").strip()
        phone = form.get(f"{prefix}_new_phone", "").strip()
        password = form.get(f"{prefix}_new_password", "").strip()
        if not username or not phone:
            raise ValueError("יש להזין שם משתמש וטלפון עבור המשתמש החדש")
        if get_user_by_username(username):
            raise ValueError(f"שם המשתמש '{username}' כבר תפוס")
        generated = False
        if not password:
            password = "".join(random.choices(string.digits, k=6))
            generated = True
        user = create_user(username, phone, password)
        if generated:
            flash(f"נוצר משתמש חדש '{username}' עם סיסמה זמנית: {password}", "info")
        return user["id"], user["username"], user["phone"]

    raise ValueError("בחירה לא תקינה")


def pair_conflicts(existing_pairs, *user_ids):
    taken = set()
    for p in existing_pairs:
        if p["player1_id"]:
            taken.add(p["player1_id"])
        if p["player2_id"]:
            taken.add(p["player2_id"])
    return any(uid and uid in taken for uid in user_ids)


# ─── Auth routes ─────────────────────────────────────────────────────────────
@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not phone:
            flash("נא למלא שם משתמש וטלפון", "error")
        elif not password or len(password) < 4:
            flash("סיסמה חייבת להכיל לפחות 4 תווים", "error")
        elif get_user_by_username(username):
            flash("שם המשתמש כבר תפוס, בחר/י שם אחר", "error")
        else:
            is_admin = bool(ADMIN_USERNAME) and username == ADMIN_USERNAME
            user = create_user(username, phone, password, is_admin=is_admin)
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = user["is_admin"]
            return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("user_id"):
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = get_user_by_username(username)
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = user["is_admin"]
            return redirect(url_for("index"))
        flash("שם משתמש או סיסמה שגויים", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


def build_profile_history(user_id):
    """One entry per tournament the user has a pair in: who their partner was, whether
    they were crowned champion, and every match their pair played with its result."""
    history = []
    for pair in list_pairs_for_user(user_id):
        tournament = get_tournament(pair["tournament_id"])
        if not tournament:
            continue
        partner_name = pair["player2_name"] if pair["player1_id"] == user_id else pair["player1_name"]
        pairs_by_id = {p["id"]: p for p in list_pairs(pair["tournament_id"])}

        my_matches = []
        for m in list_matches(pair["tournament_id"]):
            if m["pair_a_id"] != pair["id"] and m["pair_b_id"] != pair["id"]:
                continue
            opponent_id = m["pair_b_id"] if m["pair_a_id"] == pair["id"] else m["pair_a_id"]
            my_matches.append({
                "stage": m["stage"],
                "opponent": pairs_by_id.get(opponent_id),
                "score_a": m["score_a"], "score_b": m["score_b"],
                "played": m["winner_pair_id"] is not None,
                "won": (m["winner_pair_id"] == pair["id"]) if m["winner_pair_id"] else None,
            })
        my_matches.sort(key=lambda mm: STAGE_SORT_ORDER.get(mm["stage"], 99))

        history.append({
            "tournament": tournament,
            "partner_name": partner_name,
            "is_champion": tournament.get("winner_pair_id") == pair["id"],
            "matches": my_matches,
        })
    history.sort(key=lambda h: h["tournament"]["date"], reverse=True)
    return history


@app.route("/profile")
@login_required
def profile():
    user = get_user_by_id(session["user_id"])
    history = build_profile_history(user["id"])
    return render_template("profile.html", user=user, history=history)


@app.route("/profile/phone", methods=["POST"])
@login_required
def update_phone():
    phone = request.form.get("phone", "").strip()
    if not phone:
        flash("נא להזין מספר טלפון", "error")
    else:
        update_user(session["user_id"], {"phone": phone})
        flash("הטלפון עודכן בהצלחה", "success")
    return redirect(url_for("profile"))


@app.route("/profile/password", methods=["POST"])
@login_required
def update_password():
    current = request.form.get("current_password", "").strip()
    new = request.form.get("new_password", "").strip()
    confirm = request.form.get("confirm_password", "").strip()
    user = get_user_by_id(session["user_id"])
    if not check_password_hash(user["password_hash"], current):
        flash("הסיסמה הנוכחית שגויה", "error")
    elif not new or len(new) < 4:
        flash("סיסמה חדשה חייבת להכיל לפחות 4 תווים", "error")
    elif new != confirm:
        flash("הסיסמאות החדשות אינן תואמות", "error")
    else:
        update_user(session["user_id"], {"password_hash": generate_password_hash(new)})
        flash("הסיסמה עודכנה בהצלחה", "success")
    return redirect(url_for("profile"))


# ─── Dashboard & tournament creation ────────────────────────────────────────
@app.route("/")
@login_required
def index():
    tournaments = list_tournaments()
    return render_template("index.html", tournaments=tournaments)


@app.route("/tournaments/new", methods=["GET", "POST"])
@admin_required
def tournament_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        date = request.form.get("date", "").strip()
        level = request.form.get("level", "").strip()
        pairs_count = request.form.get("pairs_count", "")
        game_target = request.form.get("game_target", "")
        if not name or not date or not level:
            flash("נא למלא את כל השדות", "error")
        elif pairs_count not in ("8", "16"):
            flash("יש לבחור כמות זוגות תקינה", "error")
        elif game_target not in ("4", "6", "8"):
            flash("יש לבחור משך משחק תקין", "error")
        else:
            t = create_tournament(name, date, level, int(pairs_count), int(game_target), session["user_id"])
            return redirect(url_for("tournament_detail", tid=t["id"]))
    return render_template("tournament_new.html")


@app.route("/tournaments/<tid>/delete", methods=["POST"])
@admin_required
def delete_tournament_route(tid):
    tournament = get_tournament(tid)
    if not tournament:
        return redirect(url_for("index"))
    delete_tournament(tid)
    flash(f"הטורניר '{tournament['name']}' נמחק", "success")
    return redirect(url_for("index"))


@app.route("/admin/users/new", methods=["GET", "POST"])
@admin_required
def admin_user_new():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        is_admin = request.form.get("is_admin") == "on"
        if not username or not phone:
            flash("נא למלא שם משתמש וטלפון", "error")
        elif get_user_by_username(username):
            flash("שם המשתמש כבר תפוס", "error")
        else:
            generated = False
            if not password:
                password = "".join(random.choices(string.digits, k=6))
                generated = True
            create_user(username, phone, password, is_admin=is_admin)
            role = "אדמין" if is_admin else "משתמש"
            msg = f"נוצר {role} חדש: '{username}'"
            if generated:
                msg += f" עם סיסמה זמנית: {password}"
            flash(msg, "success")
            return redirect(url_for("admin_user_new"))
    return render_template("admin_user_new.html")


@app.route("/admin/users")
@admin_required
def admin_users():
    users = list_users()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/<uid>/edit", methods=["GET", "POST"])
@admin_required
def admin_user_edit(uid):
    user = get_user_by_id(uid)
    if not user:
        return redirect(url_for("admin_users"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        is_admin = request.form.get("is_admin") == "on"

        existing = get_user_by_username(username) if username else None
        if not username or not phone:
            flash("נא למלא שם משתמש וטלפון", "error")
        elif existing and existing["id"] != uid:
            flash("שם המשתמש כבר תפוס", "error")
        elif password and len(password) < 4:
            flash("סיסמה חדשה חייבת להכיל לפחות 4 תווים", "error")
        elif uid == session["user_id"] and not is_admin:
            flash("אי אפשר להסיר הרשאת אדמין מעצמך", "error")
        else:
            updates = {"username": username, "phone": phone, "is_admin": is_admin}
            if password:
                updates["password_hash"] = generate_password_hash(password)
            update_user(uid, updates)
            if uid == session["user_id"]:
                session["username"] = username
                session["is_admin"] = is_admin
            flash("הפרטים עודכנו בהצלחה", "success")
            return redirect(url_for("admin_users"))
        return render_template("admin_user_edit.html", user=user)

    return render_template("admin_user_edit.html", user=user)


# ─── Tournament detail, registration, draw, scoring ─────────────────────────
@app.route("/tournaments/<tid>")
@login_required
def tournament_detail(tid):
    tournament = get_tournament(tid)
    if not tournament:
        return redirect(url_for("index"))

    pairs = list_pairs(tid)
    pairs_by_id = {p["id"]: p for p in pairs}
    matches = list_matches(tid)
    user_id = session.get("user_id")

    already_in = pair_conflicts(pairs, user_id)
    spots_left = tournament["pairs_count"] - len(pairs)

    groups = {}
    if tournament["status"] in ("full", "in_progress", "completed"):
        for g in range(1, tournament["groups_count"] + 1):
            group_pairs = [p for p in pairs if p["group_number"] == g]
            group_pair_ids = [p["id"] for p in group_pairs]
            group_matches = sorted(
                [m for m in matches if m["stage"] == "group" and m["group_number"] == g],
                key=lambda m: m["match_index"],
            )
            completed = [m for m in group_matches if m["winner_pair_id"]]
            tiebreak_matches = sorted(
                [m for m in matches if m["stage"] == "tiebreak" and m["group_number"] == g],
                key=lambda m: m["match_index"],
            )
            tiebreak_winners = {
                frozenset((m["pair_a_id"], m["pair_b_id"])): m["winner_pair_id"]
                for m in tiebreak_matches if m["winner_pair_id"]
            }
            ranked_ids, stats = engine.compute_group_standings(group_pair_ids, completed, tiebreak_winners)

            unresolved_ties = []
            if len(completed) == len(group_matches) and group_matches:
                for bucket in engine.find_stat_ties(group_pair_ids, stats):
                    resolved = any(
                        frozenset((a, b)) in tiebreak_winners
                        for a in bucket for b in bucket if a != b
                    )
                    if not resolved:
                        unresolved_ties.append([pairs_by_id[pid] for pid in bucket])

            groups[g] = {
                "matches": group_matches,
                "tiebreak_matches": tiebreak_matches,
                "standings": [{"pair": pairs_by_id[pid], **stats[pid]} for pid in ranked_ids],
                "unresolved_ties": unresolved_ties,
            }

    knockout_stages = []
    for stage in ("quarterfinal", "semifinal", "final"):
        stage_matches = sorted([m for m in matches if m["stage"] == stage], key=lambda m: m["match_index"])
        if stage_matches:
            knockout_stages.append((stage, stage_matches))

    winner_pair = pairs_by_id.get(tournament.get("winner_pair_id"))
    editable = editable_stages(tournament, matches)
    pending_stage = stage_pending_advance(tournament, matches)

    return render_template(
        "tournament_detail.html",
        tournament=tournament,
        pairs=pairs,
        pairs_by_id=pairs_by_id,
        already_in=already_in,
        spots_left=spots_left,
        groups=groups,
        knockout_stages=knockout_stages,
        winner_pair=winner_pair,
        editable_stages=editable,
        pending_stage=pending_stage,
    )


@app.route("/tournaments/<tid>/register", methods=["POST"])
@login_required
def register_pair(tid):
    tournament = get_tournament(tid)
    if not tournament or tournament["status"] != "open":
        flash("ההרשמה לטורניר זה סגורה", "error")
        return redirect(url_for("tournament_detail", tid=tid))

    pairs = list_pairs(tid)
    if len(pairs) >= tournament["pairs_count"]:
        flash("הטורניר מלא", "error")
        return redirect(url_for("tournament_detail", tid=tid))

    user_id = session["user_id"]
    if pair_conflicts(pairs, user_id):
        flash("את/ה כבר רשום/ה לטורניר הזה", "error")
        return redirect(url_for("tournament_detail", tid=tid))

    me = get_user_by_id(user_id)
    try:
        p2_id, p2_name, p2_phone = resolve_player_slot(request.form, "p2", allow_new=False)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("tournament_detail", tid=tid))

    if pair_conflicts(pairs, p2_id):
        flash("השותף/ה שנבחר/ה כבר רשום/ה לטורניר הזה", "error")
        return redirect(url_for("tournament_detail", tid=tid))

    create_pair(tid, user_id, me["username"], me["phone"], p2_id, p2_name, p2_phone, added_by=user_id)
    tournament = get_tournament(tid)
    maybe_run_draw(tournament)
    flash("נרשמתם לטורניר בהצלחה!", "success")
    return redirect(url_for("tournament_detail", tid=tid))


@app.route("/tournaments/<tid>/admin-add-pair", methods=["POST"])
@admin_required
def admin_add_pair(tid):
    tournament = get_tournament(tid)
    if not tournament or tournament["status"] != "open":
        flash("אי אפשר להוסיף זוגות לטורניר שאינו פתוח להרשמה", "error")
        return redirect(url_for("tournament_detail", tid=tid))

    pairs = list_pairs(tid)
    if len(pairs) >= tournament["pairs_count"]:
        flash("הטורניר מלא", "error")
        return redirect(url_for("tournament_detail", tid=tid))

    try:
        p1_id, p1_name, p1_phone = resolve_player_slot(request.form, "p1", allow_new=True)
        p2_id, p2_name, p2_phone = resolve_player_slot(request.form, "p2", allow_new=True)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("tournament_detail", tid=tid))

    if pair_conflicts(pairs, p1_id, p2_id):
        flash("אחד המשתתפים כבר רשום לטורניר הזה", "error")
        return redirect(url_for("tournament_detail", tid=tid))

    create_pair(tid, p1_id, p1_name, p1_phone, p2_id, p2_name, p2_phone, added_by=session["user_id"])
    tournament = get_tournament(tid)
    maybe_run_draw(tournament)
    flash("הזוג נוסף לטורניר", "success")
    return redirect(url_for("tournament_detail", tid=tid))


@app.route("/tournaments/<tid>/start", methods=["POST"])
@admin_required
def start_tournament(tid):
    tournament = get_tournament(tid)
    if tournament and tournament["status"] == "full":
        update_tournament_status(tid, "in_progress")
        flash("הטורניר התחיל!", "success")
    return redirect(url_for("tournament_detail", tid=tid))


@app.route("/tournaments/<tid>/advance-stage", methods=["POST"])
@admin_required
def advance_stage(tid):
    tournament = get_tournament(tid)
    if not tournament:
        return redirect(url_for("index"))
    game_target = request.form.get("game_target", "")
    if game_target not in ("4", "6", "8"):
        flash("יש לבחור עד כמה games תקין", "error")
        return redirect(url_for("tournament_detail", tid=tid))
    matches = list_matches(tid)
    if stage_pending_advance(tournament, matches) is None:
        flash("אין שלב הממתין להתקדמות כרגע", "error")
        return redirect(url_for("tournament_detail", tid=tid))
    advance_to_next_stage(tournament, int(game_target))
    flash("השלב הבא נוצר!", "success")
    return redirect(url_for("tournament_detail", tid=tid))


@app.route("/tournaments/<tid>/groups/<int:g>/tiebreak", methods=["POST"])
@admin_required
def create_tiebreak(tid, g):
    tournament = get_tournament(tid)
    if not tournament:
        return redirect(url_for("index"))
    pair_a_id = request.form.get("pair_a_id", "")
    pair_b_id = request.form.get("pair_b_id", "")
    if not pair_a_id or not pair_b_id or pair_a_id == pair_b_id:
        flash("יש לבחור שני זוגות שונים", "error")
        return redirect(url_for("tournament_detail", tid=tid))

    matches = list_matches(tid)
    group_matches = [m for m in matches if m["stage"] == "group" and m["group_number"] == g]
    game_target = group_matches[0]["game_target"] if group_matches else tournament["game_target"]
    existing_tiebreaks = [m for m in matches if m["stage"] == "tiebreak" and m["group_number"] == g]

    create_matches([{
        "tournament_id": tid, "stage": "tiebreak", "group_number": g,
        "match_index": len(existing_tiebreaks),
        "pair_a_id": pair_a_id, "pair_b_id": pair_b_id, "game_target": game_target,
    }])
    flash("משחק טיי-ברייק נוצר — הזן/י את התוצאה כשהוא מסתיים", "success")
    return redirect(url_for("tournament_detail", tid=tid))


@app.route("/matches/<mid>/score", methods=["POST"])
@admin_required
def submit_score(mid):
    match = get_match(mid)
    if not match:
        return redirect(url_for("index"))
    tournament = get_tournament(match["tournament_id"])

    if match["winner_pair_id"] is not None:
        matches = list_matches(tournament["id"])
        editable = editable_stages(tournament, matches)
        is_editable = match["stage"] in editable or (match["stage"] == "tiebreak" and "group" in editable)
        if not is_editable:
            flash("אי אפשר לערוך תוצאה זו - השלב הבא כבר שוחק", "error")
            return redirect(url_for("tournament_detail", tid=tournament["id"]))

    try:
        score_a = int(request.form.get("score_a", ""))
        score_b = int(request.form.get("score_b", ""))
        if score_a < 0 or score_b < 0:
            raise ValueError
        winner = engine.score_winner(match["pair_a_id"], match["pair_b_id"], score_a, score_b)
    except ValueError:
        flash("תוצאה לא תקינה - אין תיקו בפאדל", "error")
        return redirect(url_for("tournament_detail", tid=tournament["id"]))

    update_match_score(mid, score_a, score_b, winner)
    tournament = get_tournament(tournament["id"])
    # a tiebreak match's result only matters as an input to the group standings
    recompute_stage = "group" if match["stage"] == "tiebreak" else match["stage"]
    recompute_from_stage(tournament, recompute_stage)
    return redirect(url_for("tournament_detail", tid=tournament["id"]))


@app.route("/api/users/search")
@login_required
def api_users_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    return jsonify(search_users(q, exclude_ids=(session.get("user_id"),)))


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
