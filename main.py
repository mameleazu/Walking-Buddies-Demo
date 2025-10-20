import os
import time
from datetime import datetime, timedelta, date
from typing import Dict, Any, List

import pandas as pd
import streamlit as st

APP_NAME = "Walking Buddies"
st.set_page_config(page_title=APP_NAME, page_icon="👟", layout="wide")

# =====================================
# Session State (safe defaults)
# =====================================
def _ensure_state():
    ss = st.session_state
    ss.setdefault("users", {})            # user_id -> dict
    ss.setdefault("teams", {})            # team_name -> {"captain":..., "members": set()}
    ss.setdefault("invites", [])          # list of {inviter, friend, ts}
    ss.setdefault("routes", [])           # list of {user_id, name, distance_km, notes, created_at}
    ss.setdefault("reminders", {          # in-app reminders (local)
        "walk_enabled": True,
        "walk_every_min": 120,
        "stand_enabled": True,
        "stand_every_min": 30,
        "next_walk_at": None,
        "next_stand_at": None,
        "last_walk_logged_at": None,
        "last_stand_ack_at": None,
        "snooze_minutes": 10,
    })
    # Challenge catalog & user progress
    ss.setdefault("challenge_catalog", [
        {
            "id": "daily_5000",
            "name": "Daily Step Goal",
            "desc": "Hit 5,000 steps today for bonus points",
            "type": "daily_steps",
            "target": 5000,
            "period": "daily",
            "reward_points": 50,
        },
        {
            "id": "weekend_walkathon",
            "name": "Weekend Walkathon",
            "desc": "Walk 10 miles over the weekend (Sat–Sun)",
            "type": "distance_period",
            "target_miles": 10.0,
            "period": "weekend",
            "reward_points": 150,
        },
        {
            "id": "photo_share",
            "name": "Photo Challenge",
            "desc": "Share a scenic walk photo this week",
            "type": "boolean_weekly",
            "target": 1,
            "period": "weekly",
            "reward_points": 20,
        },
        {
            "id": "invite_3",
            "name": "Invite Challenge",
            "desc": "Invite 3 friends into the app this month",
            "type": "count_monthly",
            "target": 3,
            "period": "monthly",
            "reward_points": 100,
        },
        {
            "id": "team_100_miles",
            "name": "Team Mileage Goal",
            "desc": "Teams aim for 100 miles combined in a week",
            "type": "team_distance_weekly",
            "target_miles": 100.0,
            "period": "weekly",
            "reward_points": 300,
        },
        {
            "id": "relay_pass_baton",
            "name": "Relay Challenge",
            "desc": "Each member walks 2 miles this week to pass the baton",
            "type": "team_each_member_distance_weekly",
            "target_miles": 2.0,
            "period": "weekly",
            "reward_points": 200,
        },
        {
            "id": "city_explorer",
            "name": "City Explorer",
            "desc": "Complete walks in 5 different neighborhoods this month",
            "type": "distinct_routes_monthly",
            "target_count": 5,
            "period": "monthly",
            "reward_points": 120,
        }
    ])
    # Per-user challenge state
    ss.setdefault("user_challenges", {})  # user_id -> {challenge_id: {"joined": bool, "progress": dict, "completed": bool, "last_reset": date}}
    # Autorefresh cadence (for reminders UI)
    ss.setdefault("ui_refresh_secs", 60)

_ensure_state()

POINT_RULES = {
    "base_per_minute": 1,
    "streak_7": 10,
    "streak_30": 50,
    "group_walk_bonus": 20,
    "invite_bonus": 50,
    "photo_share": 5,
}

TIERS = [
    ("Platinum", 5000),
    ("Gold", 1000),
    ("Silver", 500),
    ("Bronze", 0),
]

# =====================================
# Helpers
# =====================================
def ensure_user(user_id: str, display_name: str = None) -> Dict[str, Any]:
    u = st.session_state.users.setdefault(
        user_id,
        {
            "name": display_name or user_id,
            "points": 0,
            "team": None,
            "walk_dates": [],            # list of datetime stamps when any walk was logged
            "steps_log": {},             # date_iso -> steps int
            "minutes_log": {},           # date_iso -> minutes int
            "distance_miles_log": {},    # date_iso -> miles float
            "photos_this_week": 0,
            "invites_this_month": 0,
            "routes_completed_month": set(),  # set of route names to count distinct neighborhoods
        },
    )
    # backfills
    u.setdefault("name", display_name or user_id)
    u.setdefault("points", 0)
    u.setdefault("team", None)
    u.setdefault("walk_dates", [])
    u.setdefault("steps_log", {})
    u.setdefault("minutes_log", {})
    u.setdefault("distance_miles_log", {})
    u.setdefault("photos_this_week", 0)
    u.setdefault("invites_this_month", 0)
    u.setdefault("routes_completed_month", set())
    return u

def calc_streak(dates: List[datetime]) -> int:
    if not dates:
        return 0
    dates_sorted = sorted({d.date() for d in dates}, reverse=True)
    streak = 0
    today = datetime.now().date()
    for d in dates_sorted:
        if d == today - timedelta(days=streak):
            streak += 1
        elif d < today - timedelta(days=streak):
            break
    return streak

def tier_for_points(points: int) -> str:
    for name, threshold in TIERS:
        if points >= threshold:
            return name
    return "Bronze"

def add_points(user_id: str, pts: int, reason: str = ""):
    u = ensure_user(user_id, user_id)
    u["points"] = int(u.get("points", 0)) + int(pts)
    if reason:
        st.toast(f"+{pts} pts: {reason}")

def award_walk(user_id: str, minutes: int, steps: int, miles: float, is_group: bool, shared_photo: bool):
    u = ensure_user(user_id, user_id)
    today_iso = date.today().isoformat()

    # Logs
    u["walk_dates"].append(datetime.now())
    u["minutes_log"][today_iso] = int(u["minutes_log"].get(today_iso, 0)) + int(minutes)
    u["steps_log"][today_iso] = int(u["steps_log"].get(today_iso, 0)) + int(steps)
    u["distance_miles_log"][today_iso] = float(u["distance_miles_log"].get(today_iso, 0.0)) + float(miles)

    # Base points
    gained = int(minutes) * POINT_RULES["base_per_minute"]

    # Group & photo
    if is_group:
        gained += POINT_RULES["group_walk_bonus"]
    if shared_photo:
        gained += POINT_RULES["photo_share"]
        u["photos_this_week"] += 1

    # Streaks
    streak = calc_streak(u["walk_dates"])
    if streak >= 30:
        gained += POINT_RULES["streak_30"]
    elif streak >= 7:
        gained += POINT_RULES["streak_7"]

    u["points"] = int(u.get("points", 0)) + gained

    # Update reminders baseline
    st.session_state.reminders["last_walk_logged_at"] = datetime.now()

    # Update challenge progress
    update_challenges_progress_after_walk(user_id, steps=steps, miles=miles, shared_photo=shared_photo)

    return gained, u["points"], streak

def invite_friend(inviter_id: str, friend_email: str):
    st.session_state.invites.append({"inviter": inviter_id, "friend": friend_email, "ts": time.time()})
    u = ensure_user(inviter_id, inviter_id)
    u["points"] = int(u.get("points", 0)) + POINT_RULES["invite_bonus"]
    u["invites_this_month"] = int(u.get("invites_this_month", 0)) + 1
    # Update challenge progress
    update_challenges_progress_after_invite(inviter_id)
    return u["points"]

def get_leaderboards():
    users_raw = st.session_state.get("users", {})
    user_rows = []
    team_points = {}
    for uid, u in users_raw.items():
        user_rows.append({
            "user": (u.get("name") or uid),
            "points": int(u.get("points", 0)),
            "team": (u.get("team") or ""),
        })
        t = u.get("team")
        if t:
            team_points[t] = int(team_points.get(t, 0)) + int(u.get("points", 0))

    users_df = pd.DataFrame(user_rows, columns=["user", "points", "team"])
    if not users_df.empty and "points" in users_df.columns:
        users_df = users_df.sort_values("points", ascending=False).reset_index(drop=True)

    teams_df = pd.DataFrame([{"team": k, "points": v} for k, v in team_points.items()], columns=["team", "points"])
    if not teams_df.empty and "points" in teams_df.columns:
        teams_df = teams_df.sort_values("points", ascending=False).reset_index(drop=True)
    return users_df, teams_df

# =====================================
# In-App Reminders (no push services)
# =====================================
def init_reminders():
    r = st.session_state.reminders
    now = datetime.now()
    if r["next_walk_at"] is None and r["walk_enabled"]:
        r["next_walk_at"] = now + timedelta(minutes=int(r["walk_every_min"]))
    if r["next_stand_at"] is None and r["stand_enabled"]:
        r["next_stand_at"] = now + timedelta(minutes=int(r["stand_every_min"]))

def check_and_display_reminders():
    """Use autorefresh to poll and display reminders inside the app UI."""
    r = st.session_state.reminders
    now = datetime.now()
    # Walk reminder
    if r["walk_enabled"] and r["next_walk_at"] and now >= r["next_walk_at"]:
        st.warning("🚶 Time for a walk reminder!")
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Start Walk Now"):
                # Reset next walk reminder relative to now
                r["next_walk_at"] = now + timedelta(minutes=int(r["walk_every_min"]))
                st.session_state.reminders["last_walk_logged_at"] = now
                st.success("Great! Log your walk in the 'Log Walk' tab.")
        with col2:
            if st.button("Snooze 10 min"):
                r["next_walk_at"] = now + timedelta(minutes=int(r["snooze_minutes"]))
                st.info("Snoozed.")
        with col3:
            if st.button("Dismiss"):
                r["next_walk_at"] = now + timedelta(minutes=int(r["walk_every_min"]))
    # Stand reminder
    if r["stand_enabled"] and r["next_stand_at"] and now >= r["next_stand_at"]:
        st.info("🧍 Stand/Stretch reminder!")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("I Stood/Stretch"):
                r["last_stand_ack_at"] = now
                r["next_stand_at"] = now + timedelta(minutes=int(r["stand_every_min"]))
                st.success("Nice! Keep moving 🎉")
        with c2:
            if st.button("Snooze 5 min"):
                r["next_stand_at"] = now + timedelta(minutes=5)
                st.info("Snoozed.")

# =====================================
# Challenges logic (offline)
# =====================================
def _period_key(ch):
    """Return a key to detect period boundaries for reset logic."""
    p = ch.get("period")
    today = date.today()
    if p == "daily":
        return today.isoformat()
    if p == "weekly":
        # ISO week
        y, w, _ = today.isocalendar()
        return f"{y}-W{w:02d}"
    if p == "weekend":
        # Group Sat-Sun as a "weekend key" based on the Saturday date
        weekday = today.weekday()  # Mon=0..Sun=6
        saturday = today + timedelta(days=(5 - weekday)) if weekday <= 5 else today - timedelta(days=(weekday - 5))
        return f"weekend-{saturday.isoformat()}"
    if p == "monthly":
        return f"{today.year}-{today.month:02d}"
    return "alltime"

def _ensure_user_challenge(user_id: str, ch_id: str):
    uc = st.session_state.user_challenges.setdefault(user_id, {})
    if ch_id not in uc:
        uc[ch_id] = {"joined": False, "progress": {}, "completed": False, "last_reset": None}
    # Reset by period key
    ch = next((c for c in st.session_state.challenge_catalog if c["id"] == ch_id), None)
    if ch:
        key = _period_key(ch)
        if uc[ch_id]["last_reset"] != key:
            uc[ch_id]["progress"] = {}
            uc[ch_id]["completed"] = False
            uc[ch_id]["last_reset"] = key
    return uc[ch_id]

def join_challenge(user_id: str, ch_id: str):
    uc = _ensure_user_challenge(user_id, ch_id)
    uc["joined"] = True
    st.success("Joined challenge!")

def complete_challenge_if_eligible(user_id: str, ch: Dict[str, Any]):
    uc = _ensure_user_challenge(user_id, ch["id"])
    if uc["completed"] or not uc["joined"]:
        return False

    u = ensure_user(user_id, user_id)
    p = uc["progress"]

    if ch["id"] == "daily_5000":
        today_iso = date.today().isoformat()
        steps_today = int(u["steps_log"].get(today_iso, 0))
        if steps_today >= int(ch["target"]):
            uc["completed"] = True
            add_points(user_id, ch["reward_points"], "Daily Step Goal")
            return True

    elif ch["id"] == "weekend_walkathon":
        # Accumulate distance Sat–Sun
        now = date.today()
        weekday = now.weekday()
        # get Saturday/Sunday dates of current weekend
        saturday = now + timedelta(days=(5 - weekday)) if weekday <= 5 else now - timedelta(days=(weekday - 5))
        sunday = saturday + timedelta(days=1)
        total = 0.0
        for d in [saturday.isoformat(), sunday.isoformat()]:
            total += float(u["distance_miles_log"].get(d, 0.0))
        if total >= float(ch["target_miles"]):
            uc["completed"] = True
            add_points(user_id, ch["reward_points"], "Weekend Walkathon")
            return True

    elif ch["id"] == "photo_share":
        if int(u["photos_this_week"]) >= 1:
            uc["completed"] = True
            add_points(user_id, ch["reward_points"], "Photo Challenge")
            return True

    elif ch["id"] == "invite_3":
        if int(u["invites_this_month"]) >= int(ch["target"]):
            uc["completed"] = True
            add_points(user_id, ch["reward_points"], "Invite Challenge")
            return True

    elif ch["id"] == "team_100_miles":
        # Sum team members' weekly miles
        tname = u.get("team")
        if tname and tname in st.session_state.teams:
            members = st.session_state.teams[tname]["members"]
            total = 0.0
            # weekly = ISO week
            y, w, _ = date.today().isocalendar()
            # naive weekly sum (Mon-Sun): iterate this week's dates
            monday = date.fromisocalendar(y, w, 1)
            for i in range(7):
                di = (monday + timedelta(days=i)).isoformat()
                for member in members:
                    um = ensure_user(member, member)
                    total += float(um["distance_miles_log"].get(di, 0.0))
            if total >= float(ch["target_miles"]):
                uc["completed"] = True
                add_points(user_id, ch["reward_points"], "Team Mileage Goal (per member reward)")
                return True

    elif ch["id"] == "relay_pass_baton":
        tname = u.get("team")
        if tname and tname in st.session_state.teams:
            members = st.session_state.teams[tname]["members"]
            y, w, _ = date.today().isocalendar()
            monday = date.fromisocalendar(y, w, 1)
            ok_for_all = True
            for member in members:
                um = ensure_user(member, member)
                miles = 0.0
                for i in range(7):
                    di = (monday + timedelta(days=i)).isoformat()
                    miles += float(um["distance_miles_log"].get(di, 0.0))
                if miles < float(ch["target_miles"]):
                    ok_for_all = False
                    break
            if ok_for_all:
                uc["completed"] = True
                add_points(user_id, ch["reward_points"], "Relay Challenge (per member reward)")
                return True

    elif ch["id"] == "city_explorer":
        # Count distinct routes completed this month
        if int(len(u["routes_completed_month"])) >= int(ch["target_count"]):
            uc["completed"] = True
            add_points(user_id, ch["reward_points"], "City Explorer")
            return True

    return False

def update_challenges_progress_after_walk(user_id: str, steps: int, miles: float, shared_photo: bool):
    # Attempt completion checks for any joined challenges
    for ch in st.session_state.challenge_catalog:
        _ensure_user_challenge(user_id, ch["id"])
        complete_challenge_if_eligible(user_id, ch)

def update_challenges_progress_after_invite(user_id: str):
    for ch in st.session_state.challenge_catalog:
        _ensure_user_challenge(user_id, ch["id"])
        complete_challenge_if_eligible(user_id, ch)

def join_or_leave_ui(user_id: str, ch: Dict[str, Any]):
    uc = _ensure_user_challenge(user_id, ch["id"])
    joined = uc["joined"]
    if joined:
        if st.button(f"Leave '{ch['name']}'", key=f"leave_{ch['id']}"):
            uc["joined"] = False
            st.info("Left challenge.")
    else:
        if st.button(f"Join '{ch['name']}'", key=f"join_{ch['id']}"):
            join_challenge(user_id, ch["id"])

def show_progress_ui(user_id: str, ch: Dict[str, Any]):
    uc = _ensure_user_challenge(user_id, ch["id"])
    u = ensure_user(user_id, user_id)

    if ch["id"] == "daily_5000":
        today_iso = date.today().isoformat()
        steps_today = int(u["steps_log"].get(today_iso, 0))
        st.progress(min(steps_today / ch["target"], 1.0))
        st.caption(f"{steps_today:,} / {ch['target']:,} steps today")

    elif ch["id"] == "weekend_walkathon":
        now = date.today()
        weekday = now.weekday()
        saturday = now + timedelta(days=(5 - weekday)) if weekday <= 5 else now - timedelta(days=(weekday - 5))
        sunday = saturday + timedelta(days=1)
        total = 0.0
        for d in [saturday.isoformat(), sunday.isoformat()]:
            total += float(u["distance_miles_log"].get(d, 0.0))
        target = ch["target_miles"]
        st.progress(min(total / target, 1.0))
        st.caption(f"{total:.2f} / {target:.2f} miles this weekend")

    elif ch["id"] == "photo_share":
        count = int(u["photos_this_week"])
        st.progress(1.0 if count >= 1 else 0.0)
        st.caption("Photo shared this week" if count >= 1 else "No photo shared yet")

    elif ch["id"] == "invite_3":
        n = int(u["invites_this_month"])
        target = int(ch["target"])
        st.progress(min(n / target, 1.0))
        st.caption(f"{n} / {target} invites this month")

    elif ch["id"] == "team_100_miles":
        tname = u.get("team")
        total = 0.0
        if tname and tname in st.session_state.teams:
            members = st.session_state.teams[tname]["members"]
            y, w, _ = date.today().isocalendar()
            monday = date.fromisocalendar(y, w, 1)
            for i in range(7):
                di = (monday + timedelta(days=i)).isoformat()
                for member in members:
                    um = ensure_user(member, member)
                    total += float(um["distance_miles_log"].get(di, 0.0))
        target = float(ch["target_miles"])
        st.progress(min(total / target, 1.0))
        st.caption(f"Team total {total:.2f} / {target:.2f} miles this week")

    elif ch["id"] == "relay_pass_baton":
        tname = u.get("team")
        if tname and tname in st.session_state.teams:
            members = list(st.session_state.teams[tname]["members"])
            y, w, _ = date.today().isocalendar()
            monday = date.fromisocalendar(y, w, 1)
            completed_members = 0
            for member in members:
                um = ensure_user(member, member)
                miles = 0.0
                for i in range(7):
                    di = (monday + timedelta(days=i)).isoformat()
                    miles += float(um["distance_miles_log"].get(di, 0.0))
                if miles >= float(ch["target_miles"]):
                    completed_members += 1
            total_members = max(len(members), 1)
            st.progress(completed_members / total_members)
            st.caption(f"{completed_members} / {total_members} members reached {ch['target_miles']} miles this week")
        else:
            st.info("Join a team to participate in this challenge.")

    elif ch["id"] == "city_explorer":
        cnt = len(u["routes_completed_month"])
        target = int(ch["target_count"])
        st.progress(min(cnt / target, 1.0))
        st.caption(f"{cnt} / {target} distinct neighborhoods this month")

    # Completion button
    if uc["joined"] and not uc["completed"]:
        if st.button(f"Check & Complete '{ch['name']}'", key=f"complete_{ch['id']}"):
            completed = complete_challenge_if_eligible(user_id, ch)
            if completed:
                st.success(f"✅ Completed! +{ch['reward_points']} pts")
            else:
                st.warning("Not eligible yet—keep going!")
    elif uc["completed"]:
        st.success("✅ Challenge completed for this period")

# =====================================
# Routes (offline CRUD)
# =====================================
def add_route(user_id: str, name: str, distance_km: float, notes: str):
    st.session_state.routes.append({
        "user_id": user_id,
        "name": name,
        "distance_km": float(distance_km),
        "notes": notes,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    # For City Explorer: mark this route name in this month
    u = ensure_user(user_id, user_id)
    u["routes_completed_month"].add(name)

def list_routes(user_id: str):
    return [r for r in st.session_state.routes if r["user_id"] == user_id]

def delete_route(user_id: str, name: str):
    st.session_state.routes = [r for r in st.session_state.routes if not (r["user_id"] == user_id and r["name"] == name)]

# =====================================
# Sidebar: Profile, Team, Reminders
# =====================================
st.sidebar.title("👤 Profile")
user_id = st.sidebar.text_input("Your username", value="martha").strip() or "guest"
display_name = st.sidebar.text_input("Display name", value="Martha").strip() or user_id
if st.sidebar.button("Save Profile"):
    u = ensure_user(user_id, display_name)
    u["name"] = display_name
    st.success("Profile saved!")

st.sidebar.markdown("---")
st.sidebar.title("👥 Team")
team_name = st.sidebar.text_input("Create/Join team", value="Comeback Kids").strip()
if st.sidebar.button("Join Team"):
    u = ensure_user(user_id, display_name)
    u["team"] = team_name
    team = st.session_state.teams.setdefault(team_name, {"captain": user_id, "members": set()})
    team["members"].add(user_id)
    st.success(f"You joined team: {team_name}")

st.sidebar.markdown("---")
st.sidebar.title("🔔 Reminders")
init_reminders()
r = st.session_state.reminders
c1, c2 = st.sidebar.columns(2)
with c1:
    r["walk_enabled"] = st.checkbox("Walk reminders", value=r["walk_enabled"])
with c2:
    r["stand_enabled"] = st.checkbox("Stand/stretch", value=r["stand_enabled"])

r["walk_every_min"] = st.sidebar.number_input("Walk every (min)", min_value=15, max_value=360, value=int(r["walk_every_min"]))
r["stand_every_min"] = st.sidebar.number_input("Stand every (min)", min_value=5, max_value=120, value=int(r["stand_every_min"]))
r["snooze_minutes"] = st.sidebar.number_input("Snooze (min)", min_value=5, max_value=60, value=int(r["snooze_minutes"]))
if st.sidebar.button("Apply & Reset Timers"):
    now = datetime.now()
    if r["walk_enabled"]:
        r["next_walk_at"] = now + timedelta(minutes=int(r["walk_every_min"]))
    if r["stand_enabled"]:
        r["next_stand_at"] = now + timedelta(minutes=int(r["stand_every_min"]))
    st.sidebar.success("Reminder timers reset.")

st.sidebar.caption("Reminders run locally in-app using auto-refresh.")

# autorefresh: keep modest interval
st_autorefresh = st.sidebar.empty()
st_autorefresh.write(f"🔄 Auto-refresh every {st.session_state.ui_refresh_secs}s for reminders.")
st.experimental_singleton.clear() if False else None  # placeholder to avoid lint

# =====================================
# Main UI
# =====================================
st.title("👟 Walking Buddies — Social Walking for Healthier Lifestyles")

tab_home, tab_log, tab_leader, tab_challenges, tab_rewards, tab_routes = st.tabs(
    ["Home", "Log Walk", "Leaderboards", "Challenges", "Rewards", "Routes"]
)

with tab_home:
    st.subheader("Daily Motivation")
    st.write("“Every step is a step forward.”")
    st.metric("Total Users", len(st.session_state.users))
    st.metric("Total Teams", len(st.session_state.teams))
    users_df, teams_df = get_leaderboards()
    st.write("### Top Walkers")
    if users_df.empty:
        st.info("No walkers yet — log a walk to see the leaderboard!")
    else:
        st.dataframe(users_df.head(10), use_container_width=True)
    st.write("### Top Teams")
    if teams_df.empty:
        st.info("No teams yet — join or create a team to get started!")
    else:
        st.dataframe(teams_df.head(10), use_container_width=True)

    st.divider()
    st.subheader("⏰ In-App Reminders")
    check_and_display_reminders()
    # Gentle info about refresh
    st.caption("This app auto-checks reminders periodically while it's open.")

with tab_log:
    st.subheader("Log a Walk (no external APIs)")
    colA, colB, colC = st.columns(3)
    with colA:
        minutes = st.number_input("Minutes", min_value=1, max_value=300, value=30)
    with colB:
        steps = st.number_input("Steps", min_value=0, max_value=100000, value=3500, help="Enter steps taken for this walk")
    with colC:
        miles = st.number_input("Miles", min_value=0.0, max_value=100.0, value=1.5, format="%.2f")

    is_group = st.checkbox("Group walk")
    shared_photo = st.checkbox("Shared a scenic photo")

    if st.button("Submit Walk"):
        gained, total, streak = award_walk(user_id, minutes, steps, miles, is_group, shared_photo)
        st.success(f"+{gained} points! New total: {total} | Current streak: {streak} day(s).")

    st.divider()
    st.subheader("Invite a Friend")
    email = st.text_input("Friend's email")
    if st.button("Send Invite"):
        total = invite_friend(user_id, email)
        st.success(f"Invite sent! +{POINT_RULES['invite_bonus']} points. New total: {total}.")

with tab_leader:
    st.subheader("Leaderboards")
    users_df, teams_df = get_leaderboards()
    st.write("#### Individuals")
    if users_df.empty:
        st.info("No walkers yet — log a walk to see the leaderboard!")
    else:
        st.dataframe(users_df, use_container_width=True)
    st.write("#### Teams")
    if teams_df.empty:
        st.info("No teams yet — join or create a team to get started!")
    else:
        st.dataframe(teams_df, use_container_width=True)

with tab_challenges:
    st.subheader("Challenges (join, track, complete — no APIs)")
    st.caption("Join a challenge to track progress and claim points when you meet the target.")
    for ch in st.session_state.challenge_catalog:
        st.markdown(f"### {ch['name']}")
        st.write(ch["desc"])
        join_or_leave_ui(user_id, ch)
        show_progress_ui(user_id, ch)
        st.divider()

with tab_rewards:
    st.subheader("Rewards & Tiers")
    u = ensure_user(user_id, display_name)
    current_tier = tier_for_points(int(u.get("points", 0)))
    st.metric("Your Points", int(u.get("points", 0)))
    st.metric("Your Tier", current_tier)
    st.write("**Rewards Examples**")
    st.write("- Digital Badges (milestones)")
    st.write("- Discount Codes (sneakers/wellness)")
    st.write("- Gift Cards (top monthly walkers)")
    st.write("- Exclusive Challenges (higher tiers)")

with tab_routes:
    st.subheader("Training Log & Routes (offline)")
    st.caption("Create simple routes without any map API; use name as neighborhood tag for 'City Explorer'.")
    rc1, rc2 = st.columns([2,1])
    with rc1:
        route_name = st.text_input("Route name (e.g., 'BeltLine Eastside', 'Riverside Park')")
        route_km = st.number_input("Distance (km)", min_value=0.1, max_value=200.0, value=3.0, format="%.2f")
        route_notes = st.text_area("Notes (optional)", height=80)
    with rc2:
        if st.button("Add Route"):
            if route_name.strip():
                add_route(user_id, route_name.strip(), route_km, route_notes.strip())
                st.success(f"Route '{route_name}' added.")
            else:
                st.error("Please provide a route name.")

    user_routes = list_routes(user_id)
    if user_routes:
        st.write("### My Routes")
        df = pd.DataFrame(user_routes)
        st.dataframe(df[["name", "distance_km", "notes", "created_at"]], use_container_width=True)
        del_name = st.selectbox("Delete a route", [""] + [r["name"] for r in user_routes])
        if st.button("Delete Selected Route"):
            if del_name:
                delete_route(user_id, del_name)
                st.success(f"Deleted route '{del_name}'.")
    else:
        st.info("No routes yet — add your first route above.")

st.caption("Prototype uses local in-memory storage. For production, switch to a database.")
