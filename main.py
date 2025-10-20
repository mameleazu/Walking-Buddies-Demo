import os
import time
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional

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
    ss.setdefault("teams", {})            # team_name -> {"captain":..., "members": set(), "battles": []}
    ss.setdefault("invites", [])          # list of {inviter, friend, ts}
    ss.setdefault("routes", [])           # list of {user_id, name, distance_km, notes, created_at}
    ss.setdefault("messages", [])         # list of {from, to, text, ts}
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
    # Personalized challenge templates created by users
    ss.setdefault("custom_challenges", [])
    # Per-user challenge state
    ss.setdefault("user_challenges", {})
    # Team battles (head-to-head)
    ss.setdefault("team_battles", [])
    # Rewards catalog
    ss.setdefault("reward_catalog", [
        {"id":"badge_10_walks","type":"badge","name":"First 10 Walks","cost":0,"desc":"Milestone badge after 10 walks"},
        {"id":"badge_100_miles","type":"badge","name":"100 Miles Club","cost":0,"desc":"Milestone badge after 100 miles"},
        {"id":"coupon_sneakers","type":"coupon","name":"Sneaker Discount $10","cost":300,"desc":"$10 off partner sneakers"},
        {"id":"coupon_cafe","type":"coupon","name":"Local Cafe $5","cost":150,"desc":"$5 voucher at partner cafe"},
        {"id":"giftcard","type":"gift","name":"Gift Card $20","cost":800,"desc":"Generic gift card"},
        {"id":"premium_challenge","type":"unlock","name":"Exclusive Challenge Pack","cost":400,"desc":"Unlock premium challenge set"},
    ])
    # Badges earned
    ss.setdefault("badges", {})  # user_id -> set([badge_id])
    # Auto-refresh cadence (reminders polling)
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
def ensure_user(user_id: str, display_name: Optional[str] = None) -> Dict[str, Any]:
    u = st.session_state.users.setdefault(
        user_id,
        {
            "name": display_name or user_id,
            "points": 0,
            "team": None,
            "city": "",
            "available_times": "Mornings",
            "buddies": set(),
            "walk_dates": [],
            "steps_log": {},
            "minutes_log": {},
            "distance_miles_log": {},
            "photos_this_week": 0,
            "invites_this_month": 0,
            "routes_completed_month": set(),
        },
    )
    u.setdefault("name", display_name or user_id)
    u.setdefault("points", 0)
    u.setdefault("team", None)
    u.setdefault("city", "")
    u.setdefault("available_times", "Mornings")
    u.setdefault("buddies", set())
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

def total_walk_count(u: Dict[str,Any]) -> int:
    return len(u.get("walk_dates", []))

def total_miles_all_time(u: Dict[str,Any]) -> float:
    return sum(float(v) for v in u.get("distance_miles_log", {}).values())

def add_points(user_id: str, pts: int, reason: str = ""):
    u = ensure_user(user_id, user_id)
    u["points"] = int(u.get("points", 0)) + int(pts)
    if reason:
        st.toast(f"+{pts} pts: {reason}")

def check_and_award_badges(user_id: str):
    u = ensure_user(user_id, user_id)
    badges = st.session_state.badges.setdefault(user_id, set())
    if total_walk_count(u) >= 10:
        badges.add("badge_10_walks")
    if total_miles_all_time(u) >= 100.0:
        badges.add("badge_100_miles")

def award_walk(user_id: str, minutes: int, steps: int, miles: float, is_group: bool, shared_photo: bool):
    u = ensure_user(user_id, user_id)
    today_iso = date.today().isoformat()
    u["walk_dates"].append(datetime.now())
    u["minutes_log"][today_iso] = int(u["minutes_log"].get(today_iso, 0)) + int(minutes)
    u["steps_log"][today_iso] = int(u["steps_log"].get(today_iso, 0)) + int(steps)
    u["distance_miles_log"][today_iso] = float(u["distance_miles_log"].get(today_iso, 0.0)) + float(miles)
    gained = int(minutes) * POINT_RULES["base_per_minute"]
    if is_group:
        gained += POINT_RULES["group_walk_bonus"]
    if shared_photo:
        gained += POINT_RULES["photo_share"]
        u["photos_this_week"] += 1
    streak = calc_streak(u["walk_dates"])
    if streak >= 30:
        gained += POINT_RULES["streak_30"]
    elif streak >= 7:
        gained += POINT_RULES["streak_7"]
    u["points"] = int(u.get("points", 0)) + gained
    st.session_state.reminders["last_walk_logged_at"] = datetime.now()
    update_challenges_progress_after_walk(user_id, steps=steps, miles=miles, shared_photo=shared_photo)
    check_and_award_badges(user_id)
    return gained, u["points"], streak

def invite_friend(inviter_id: str, friend_email: str):
    st.session_state.invites.append({"inviter": inviter_id, "friend": friend_email, "ts": time.time()})
    u = ensure_user(inviter_id, inviter_id)
    u["points"] = int(u.get("points", 0)) + POINT_RULES["invite_bonus"]
    u["invites_this_month"] = int(u.get("invites_this_month", 0)) + 1
    update_challenges_progress_after_invite(inviter_id)
    return u["points"]

def get_leaderboards():
    users_raw = st.session_state.get("users", {})
    user_rows, team_points = [], {}
    for uid, u in users_raw.items():
        user_rows.append({"user": u.get("name") or uid, "points": int(u.get("points", 0)), "team": (u.get("team") or "")})
        t = u.get("team")
        if t:
            team_points[t] = int(team_points.get(t, 0)) + int(u.get("points", 0))
    users_df = pd.DataFrame(user_rows, columns=["user", "points", "team"])
    if not users_df.empty and "points" in users_df.columns:
        users_df = users_df.sort_values("points", ascending=False).reset_index(drop=True)
    teams_df = pd.DataFrame([{"team": k, "points": v} for k, v in team_points.items()], columns=["team","points"])
    if not teams_df.empty and "points" in teams_df.columns:
        teams_df = teams_df.sort_values("points", ascending=False).reset_index(drop=True)
    return users_df, teams_df

# In-App Reminders
def init_reminders():
    r = st.session_state.reminders
    now = datetime.now()
    if r["next_walk_at"] is None and r["walk_enabled"]:
        r["next_walk_at"] = now + timedelta(minutes=int(r["walk_every_min"]))
    if r["next_stand_at"] is None and r["stand_enabled"]:
        r["next_stand_at"] = now + timedelta(minutes=int(r["stand_every_min"]))

def check_and_display_reminders():
    r = st.session_state.reminders
    now = datetime.now()
    if r["walk_enabled"] and r["next_walk_at"] and now >= r["next_walk_at"]:
        st.warning("🚶 Time for a walk reminder!")
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Start Walk Now"):
                r["next_walk_at"] = now + timedelta(minutes=int(r["walk_every_min"]))
                st.success("Great! Log your walk in the 'Log Walk' tab.")
        with col2:
            if st.button("Snooze 10 min"):
                r["next_walk_at"] = now + timedelta(minutes=int(r["snooze_minutes"]))
                st.info("Snoozed.")
        with col3:
            if st.button("Dismiss"):
                r["next_walk_at"] = now + timedelta(minutes=int(r["walk_every_min"]))
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

# Challenges logic
def _period_key(ch):
    p = ch.get("period")
    today = date.today()
    if p == "daily":
        return today.isoformat()
    if p == "weekly":
        y, w, _ = today.isocalendar()
        return f"{y}-W{w:02d}"
    if p == "weekend":
        weekday = today.weekday()
        saturday = today + timedelta(days=(5 - weekday)) if weekday <= 5 else today - timedelta(days=(weekday - 5))
        return f"weekend-{saturday.isoformat()}"
    if p == "monthly":
        return f"{today.year}-{today.month:02d}"
    return "alltime"

def get_challenge_by_id(ch_id: str):
    for c in st.session_state.challenge_catalog:
        if c["id"] == ch_id: return c
    for c in st.session_state.custom_challenges:
        if c["id"] == ch_id: return c
    return None

def _ensure_user_challenge(user_id: str, ch_id: str):
    uc = st.session_state.user_challenges.setdefault(user_id, {})
    if ch_id not in uc:
        uc[ch_id] = {"joined": False, "progress": {}, "completed": False, "last_reset": None}
    ch = get_challenge_by_id(ch_id)
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

def _dates_for_period(period) -> List[str]:
    today = date.today()
    if period == "daily":
        return [today.isoformat()]
    if period == "weekly":
        y, w, _ = today.isocalendar()
        monday = date.fromisocalendar(y, w, 1)
        return [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    if period == "monthly":
        start = date(today.year, today.month, 1)
        days = (date(today.year + (today.month // 12), ((today.month % 12) + 1), 1) - start).days
        return [(start + timedelta(days=i)).isoformat() for i in range(days)]
    if period == "weekend":
        weekday = today.weekday()
        saturday = today + timedelta(days=(5 - weekday)) if weekday <= 5 else today - timedelta(days=(weekday - 5))
        sunday = saturday + timedelta(days=1)
        return [saturday.isoformat(), sunday.isoformat()]
    return [today.isoformat()]

def _sum_steps_for_period(u, period):
    return sum(int(u["steps_log"].get(d, 0)) for d in _dates_for_period(period))

def _sum_minutes_for_period(u, period):
    return sum(int(u["minutes_log"].get(d, 0)) for d in _dates_for_period(period))

def _sum_miles_for_period(u, period):
    return sum(float(u["distance_miles_log"].get(d, 0.0)) for d in _dates_for_period(period))

def _count_walks_for_period(u, period):
    ds = set(_dates_for_period(period))
    return sum(1 for dt in u.get("walk_dates", []) if dt.date().isoformat() in ds)

def complete_challenge_if_eligible(user_id: str, ch: Dict[str, Any]):
    uc = _ensure_user_challenge(user_id, ch["id"])
    if uc["completed"] or not uc["joined"]:
        return False
    u = ensure_user(user_id, user_id)

    # built-ins
    if ch["id"] == "daily_5000":
        if int(u["steps_log"].get(date.today().isoformat(), 0)) >= int(ch["target"]):
            uc["completed"] = True; add_points(user_id, ch["reward_points"], ch["name"]); return True
    elif ch["id"] == "weekend_walkathon":
        now = date.today()
        weekday = now.weekday()
        saturday = now + timedelta(days=(5 - weekday)) if weekday <= 5 else now - timedelta(days=(weekday - 5))
        sunday = saturday + timedelta(days=1)
        total = float(u["distance_miles_log"].get(saturday.isoformat(), 0.0)) + float(u["distance_miles_log"].get(sunday.isoformat(), 0.0))
        if total >= float(ch["target_miles"]):
            uc["completed"] = True; add_points(user_id, ch["reward_points"], ch["name"]); return True
    elif ch["id"] == "photo_share":
        if int(u["photos_this_week"]) >= 1:
            uc["completed"] = True; add_points(user_id, ch["reward_points"], ch["name"]); return True
    elif ch["id"] == "invite_3":
        if int(u["invites_this_month"]) >= int(ch["target"]):
            uc["completed"] = True; add_points(user_id, ch["reward_points"], ch["name"]); return True
    elif ch["id"] == "team_100_miles":
        tname = u.get("team")
        if tname and tname in st.session_state.teams:
            members = st.session_state.teams[tname]["members"]
            y, w, _ = date.today().isocalendar()
            monday = date.fromisocalendar(y, w, 1)
            total = 0.0
            for i in range(7):
                di = (monday + timedelta(days=i)).isoformat()
                for member in members:
                    um = ensure_user(member, member)
                    total += float(um["distance_miles_log"].get(di, 0.0))
            if total >= float(ch["target_miles"]):
                uc["completed"] = True; add_points(user_id, ch["reward_points"], ch["name"]); return True
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
                    ok_for_all = False; break
            if ok_for_all:
                uc["completed"] = True; add_points(user_id, ch["reward_points"], ch["name"]); return True
    elif ch["id"] == "city_explorer":
        if int(len(u["routes_completed_month"])) >= int(ch["target_count"]):
            uc["completed"] = True; add_points(user_id, ch["reward_points"], ch["name"]); return True

    # custom
    if ch.get("custom", False):
        metric = ch.get("metric", "steps")
        period = ch.get("period", "weekly")
        target = float(ch.get("target_value", 0))
        val = 0.0
        if metric == "steps": val = _sum_steps_for_period(u, period)
        elif metric == "minutes": val = _sum_minutes_for_period(u, period)
        elif metric == "miles": val = _sum_miles_for_period(u, period)
        elif metric == "walks": val = _count_walks_for_period(u, period)
        if val >= target:
            uc["completed"] = True; add_points(user_id, int(ch.get("reward_points", 0)), ch["name"]); return True

    return False

def update_challenges_progress_after_walk(user_id: str, steps: int, miles: float, shared_photo: bool):
    for ch in (st.session_state.challenge_catalog + st.session_state.custom_challenges):
        _ensure_user_challenge(user_id, ch["id"])
        complete_challenge_if_eligible(user_id, ch)

def update_challenges_progress_after_invite(user_id: str):
    for ch in (st.session_state.challenge_catalog + st.session_state.custom_challenges):
        _ensure_user_challenge(user_id, ch["id"])
        complete_challenge_if_eligible(user_id, ch)

def join_or_leave_ui(user_id: str, ch: Dict[str, Any]):
    uc = _ensure_user_challenge(user_id, ch["id"])
    if uc["joined"]:
        if st.button(f"Leave '{ch['name']}'", key=f"leave_{ch['id']}"):
            uc["joined"] = False; st.info("Left challenge.")
    else:
        if st.button(f"Join '{ch['name']}'", key=f"join_{ch['id']}"):
            join_challenge(user_id, ch["id"])

def show_progress_ui(user_id: str, ch: Dict[str, Any]):
    uc = _ensure_user_challenge(user_id, ch["id"])
    u = ensure_user(user_id, user_id)
    # visuals for built-ins
    if ch["id"] == "daily_5000":
        today_iso = date.today().isoformat()
        steps_today = int(u["steps_log"].get(today_iso, 0))
        st.progress(min(steps_today / ch["target"], 1.0))
        st.caption(f"{steps_today:,} / {ch['target']:,} steps today")
    elif ch["id"] == "weekend_walkathon":
        now = date.today(); weekday = now.weekday()
        saturday = now + timedelta(days=(5 - weekday)) if weekday <= 5 else now - timedelta(days=(weekday - 5))
        sunday = saturday + timedelta(days=1)
        total = float(u["distance_miles_log"].get(saturday.isoformat(), 0.0)) + float(u["distance_miles_log"].get(sunday.isoformat(), 0.0))
        target = ch["target_miles"]
        st.progress(min(total / target, 1.0)); st.caption(f"{total:.2f} / {target:.2f} miles this weekend")
    elif ch["id"] == "photo_share":
        count = int(u["photos_this_week"]); st.progress(1.0 if count >= 1 else 0.0); st.caption("Photo shared this week" if count >= 1 else "No photo shared yet")
    elif ch["id"] == "invite_3":
        n = int(u["invites_this_month"]); target = int(ch["target"]); st.progress(min(n/target,1.0)); st.caption(f"{n} / {target} invites this month")
    elif ch["id"] == "team_100_miles":
        tname = u.get("team"); total = 0.0
        if tname and tname in st.session_state.teams:
            members = st.session_state.teams[tname]["members"]
            y, w, _ = date.today().isocalendar(); monday = date.fromisocalendar(y, w, 1)
            for i in range(7):
                di = (monday + timedelta(days=i)).isoformat()
                for member in members:
                    um = ensure_user(member, member); total += float(um["distance_miles_log"].get(di, 0.0))
        target = float(ch["target_miles"]); st.progress(min(total/target,1.0)); st.caption(f"Team total {total:.2f} / {target:.2f} miles this week")
    elif ch["id"] == "relay_pass_baton":
        tname = u.get("team")
        if tname and tname in st.session_state.teams:
            members = list(st.session_state.teams[tname]["members"]); y, w, _ = date.today().isocalendar(); monday = date.fromisocalendar(y, w, 1)
            completed_members = 0
            for member in members:
                um = ensure_user(member, member); miles = 0.0
                for i in range(7):
                    di = (monday + timedelta(days=i)).isoformat(); miles += float(um["distance_miles_log"].get(di, 0.0))
                if miles >= float(ch["target_miles"]): completed_members += 1
            total_members = max(len(members), 1); st.progress(completed_members/total_members); st.caption(f"{completed_members} / {total_members} members reached {ch['target_miles']} miles this week")
        else:
            st.info("Join a team to participate in this challenge.")
    elif ch["id"] == "city_explorer":
        cnt = len(u["routes_completed_month"]); target = int(ch["target_count"]); st.progress(min(cnt/target,1.0)); st.caption(f"{cnt} / {target} distinct neighborhoods this month")

    # custom progress
    if ch.get("custom", False):
        metric = ch.get("metric","steps"); period = ch.get("period","weekly"); target = float(ch.get("target_value",0))
        val = 0.0
        if metric == "steps": val = _sum_steps_for_period(u, period)
        elif metric == "minutes": val = _sum_minutes_for_period(u, period)
        elif metric == "miles": val = _sum_miles_for_period(u, period)
        elif metric == "walks": val = _count_walks_for_period(u, period)
        st.progress(min(val/target if target else 0,1.0)); st.caption(f"{val:.2f} / {target:.2f} {metric} this {period}")

    if uc["joined"] and not uc["completed"]:
        if st.button(f"Check & Complete '{ch['name']}'", key=f"complete_{ch['id']}"):
            completed = complete_challenge_if_eligible(user_id, ch)
            if completed: st.success(f"✅ Completed! +{ch.get('reward_points',0)} pts")
            else: st.warning("Not eligible yet—keep going!")
    elif uc["completed"]:
        st.success("✅ Challenge completed for this period")

def create_custom_challenge(creator_id: str, name: str, desc: str, scope: str, metric: str, target_value: float, period: str, reward_points: int, team_name: Optional[str] = None):
    cid = f"custom_{int(time.time()*1000)}"
    ch = {"id": cid, "name": name, "desc": desc, "custom": True, "scope": scope, "metric": metric, "target_value": float(target_value), "period": period, "reward_points": int(reward_points), "creator": creator_id}
    if scope == "team" and team_name: ch["team_name"] = team_name
    st.session_state.custom_challenges.append(ch); st.success("Custom challenge created. Invite members to join from the Challenges tab!")

# Community: buddies, messages, team battles
def find_local_buddies(user_id: str):
    me = ensure_user(user_id, user_id); city = me.get("city","").strip().lower()
    if not city: return []
    res = []
    for uid, u in st.session_state.users.items():
        if uid == user_id: continue
        if (u.get("city","").strip().lower() == city):
            res.append({"user_id": uid, "name": u.get("name", uid), "available_times": u.get("available_times","")})
    return res

def send_message(sender_id: str, recipient_id: str, text: str):
    st.session_state.messages.append({"from": sender_id, "to": recipient_id, "text": text, "ts": datetime.now().isoformat(timespec="seconds")})

def get_conversation(a: str, b: str):
    msgs = [m for m in st.session_state.messages if (m["from"]==a and m["to"]==b) or (m["from"]==b and m["to"]==a)]
    msgs.sort(key=lambda x: x["ts"]); return msgs

def create_team_battle(team_a: str, team_b: str, days: int, reward_points: int):
    start = date.today(); end = start + timedelta(days=int(days))
    st.session_state.team_battles.append({"team_a": team_a, "team_b": team_b, "start_date": start.isoformat(), "end_date": end.isoformat(), "metric": "distance", "reward_points": int(reward_points), "winner": None})
    st.success(f"Battle created: {team_a} vs {team_b} ({start} to {end})")

def compute_team_distance_for_range(team: str, start_iso: str, end_iso: str) -> float:
    start = date.fromisoformat(start_iso); end = date.fromisoformat(end_iso); total = 0.0
    if team not in st.session_state.teams: return 0.0
    members = st.session_state.teams[team]["members"]; cur = start
    while cur <= end:
        di = cur.isoformat()
        for member in members:
            um = ensure_user(member, member); total += float(um["distance_miles_log"].get(di, 0.0))
        cur += timedelta(days=1)
    return total

def settle_battles():
    today_iso = date.today().isoformat()
    for b in st.session_state.team_battles:
        if b["winner"] is None and today_iso > b["end_date"]:
            a, bteam = b["team_a"], b["team_b"]
            a_total = compute_team_distance_for_range(a, b["start_date"], b["end_date"])
            b_total = compute_team_distance_for_range(bteam, b["start_date"], b["end_date"])
            if a_total > b_total: b["winner"] = a
            elif b_total > a_total: b["winner"] = bteam
            else: b["winner"] = "draw"

# Routes
def add_route(user_id: str, name: str, distance_km: float, notes: str):
    st.session_state.routes.append({"user_id": user_id, "name": name, "distance_km": float(distance_km), "notes": notes, "created_at": datetime.now().isoformat(timespec="seconds")})
    u = ensure_user(user_id, user_id); u["routes_completed_month"].add(name)

def list_routes(user_id: str):
    return [r for r in st.session_state.routes if r["user_id"] == user_id]

def delete_route(user_id: str, name: str):
    st.session_state.routes = [r for r in st.session_state.routes if not (r["user_id"] == user_id and r["name"] == name)]

# Sidebar
st.sidebar.title("👤 Profile")
user_id = st.sidebar.text_input("Your username", value="martha").strip() or "guest"
display_name = st.sidebar.text_input("Display name", value="Martha").strip() or user_id
city = st.sidebar.text_input("City (for local buddies)", value="Atlanta").strip()
avail = st.sidebar.selectbox("Usual walk time", ["Mornings", "Lunch", "Evenings", "Weekends"], index=0)
if st.sidebar.button("Save Profile"):
    u = ensure_user(user_id, display_name); u["name"] = display_name; u["city"] = city; u["available_times"] = avail; st.success("Profile saved!")

st.sidebar.markdown("---")
st.sidebar.title("👥 Team")
team_name = st.sidebar.text_input("Create/Join team", value="Comeback Kids").strip()
if st.sidebar.button("Join Team"):
    u = ensure_user(user_id, display_name); u["team"] = team_name
    team = st.session_state.teams.setdefault(team_name, {"captain": user_id, "members": set(), "battles": []}); team["members"].add(user_id)
    st.success(f"You joined team: {team_name}")

st.sidebar.markdown("---")
st.sidebar.title("🔔 Reminders")
init_reminders()
r = st.session_state.reminders
c1, c2 = st.sidebar.columns(2)
with c1: r["walk_enabled"] = st.checkbox("Walk reminders", value=r["walk_enabled"])
with c2: r["stand_enabled"] = st.checkbox("Stand/stretch", value=r["stand_enabled"])
r["walk_every_min"] = st.sidebar.number_input("Walk every (min)", min_value=15, max_value=360, value=int(r["walk_every_min"]))
r["stand_every_min"] = st.sidebar.number_input("Stand every (min)", min_value=5, max_value=120, value=int(r["stand_every_min"]))
r["snooze_minutes"] = st.sidebar.number_input("Snooze (min)", min_value=5, max_value=60, value=int(r["snooze_minutes"]))
if st.sidebar.button("Apply & Reset Timers"):
    now = datetime.now()
    if r["walk_enabled"]: r["next_walk_at"] = now + timedelta(minutes=int(r["walk_every_min"]))
    if r["stand_enabled"]: r["next_stand_at"] = now + timedelta(minutes=int(r["stand_every_min"]))
    st.sidebar.success("Reminder timers reset.")
st.sidebar.caption("Reminders run locally in-app while it's open.")

# Main UI Tabs
st.title("👟 Walking Buddies — Social Walking for Healthier Lifestyles")

tab_dash, tab_log, tab_leader, tab_challenges, tab_community, tab_rewards, tab_routes, tab_messages = st.tabs(
    ["Dashboard", "Log Walk", "Leaderboards", "Challenges", "Community", "Rewards", "Routes", "Messages"]
)

# Dashboard
with tab_dash:
    st.subheader("Personal Dashboard")
    u = ensure_user(user_id, display_name)
    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("Points", int(u.get("points",0)))
    with col2: st.metric("Tier", tier_for_points(int(u.get("points",0))))
    with col3: st.metric("Total Walks", total_walk_count(u))
    with col4: st.metric("Miles (All-Time)", f"{total_miles_all_time(u):.1f}")
    st.write("### Momentum Toward Badges")
    walks = total_walk_count(u); st.progress(min(walks/10, 1.0), text=f"First 10 Walks: {walks}/10")
    miles = total_miles_all_time(u); st.progress(min(miles/100.0, 1.0), text=f"100 Miles Club: {miles:.1f}/100.0")
    st.write("### Team & Rewards")
    tname = u.get("team") or "No team yet"; st.caption(f"Team: **{tname}**")
    st.caption("Check the **Community** tab for team battles & local buddies, and **Rewards** for redemption.")
    st.divider(); st.subheader("⏰ Reminders"); check_and_display_reminders()

# Log Walk
with tab_log:
    st.subheader("Log a Walk")
    colA, colB, colC = st.columns(3)
    with colA: minutes = st.number_input("Minutes", min_value=1, max_value=300, value=30)
    with colB: steps = st.number_input("Steps", min_value=0, max_value=100000, value=3500)
    with colC: miles_in = st.number_input("Miles", min_value=0.0, max_value=100.0, value=1.5, format="%.2f")
    is_group = st.checkbox("Group walk"); shared_photo = st.checkbox("Shared a scenic photo")
    if st.button("Submit Walk"):
        gained, total, streak = award_walk(user_id, minutes, steps, miles_in, is_group, shared_photo)
        st.success(f"+{gained} points! New total: {total} | Current streak: {streak} day(s).")
    st.divider(); st.subheader("Invite a Friend")
    email = st.text_input("Friend's email")
    if st.button("Send Invite"):
        total = invite_friend(user_id, email); st.success(f"Invite sent! +{POINT_RULES['invite_bonus']} points. New total: {total}.")

# Leaderboards
with tab_leader:
    st.subheader("Leaderboards")
    users_df, teams_df = get_leaderboards()
    st.write("#### Individuals")
    if users_df.empty: st.info("No walkers yet — log a walk to see the leaderboard!")
    else: st.dataframe(users_df, use_container_width=True)
    st.write("#### Teams")
    if teams_df.empty: st.info("No teams yet — join or create a team to get started!")
    else: st.dataframe(teams_df, use_container_width=True)

# Challenges
with tab_challenges:
    st.subheader("Challenges")
    st.caption("Join a challenge to track progress and claim points when you meet the target.")
    all_ch = list(st.session_state.challenge_catalog) + list(st.session_state.custom_challenges)
    for ch in all_ch:
        st.markdown(f"### {ch['name']}"); st.write(ch["desc"]); join_or_leave_ui(user_id, ch); show_progress_ui(user_id, ch); st.divider()

    st.markdown("## Create a Personalized Challenge")
    with st.form("create_custom"):
        name = st.text_input("Challenge name")
        desc = st.text_area("Description", height=80)
        scope = st.selectbox("Scope", ["individual", "team"])
        metric = st.selectbox("Metric", ["steps", "minutes", "miles", "walks"])
        target_value = st.number_input("Target value", min_value=1.0, value=10.0)
        period = st.selectbox("Period", ["daily","weekly","monthly","weekend"], index=1)
        reward_points = st.number_input("Reward points", min_value=0, value=100, step=10)
        team_for_ch = None
        if scope == "team":
            team_for_ch = st.text_input("Team name for challenge (optional, defaults to your team)", value=(ensure_user(user_id).get("team") or ""))
        submitted = st.form_submit_button("Create Challenge")
        if submitted:
            if not name.strip(): st.error("Please provide a challenge name.")
            else: create_custom_challenge(user_id, name.strip(), desc.strip(), scope, metric, target_value, period, reward_points, team_for_ch or None)

# Community
with tab_community:
    st.subheader("Community")
    u = ensure_user(user_id, display_name)
    st.write("### Find Local Buddies")
    st.caption("Matches are based on your city and usual walk time in your profile.")
    buddies = find_local_buddies(user_id)
    if buddies:
        for b in buddies:
            col1, col2, col3 = st.columns([3,2,1])
            with col1: st.write(f"**{b['name']}** — {b['available_times']}")
            with col2:
                if st.button(f"Message {b['name']}", key=f"msg_{b['user_id']}"):
                    u["buddies"].add(b["user_id"]); st.session_state["active_chat"] = b["user_id"]; st.success(f"You can now chat with {b['name']} in the Messages tab.")
            with col3:
                if st.button(f"Add Buddy", key=f"add_{b['user_id']}"):
                    u["buddies"].add(b["user_id"]); st.toast(f"Added {b['name']} as a buddy")
    else:
        st.info("No local matches yet. Update your city in the sidebar and invite friends!")

    st.divider(); st.write("### Team Battles (Walk Against Other Teams)")
    settle_battles()
    existing_battles = st.session_state.team_battles
    if existing_battles:
        for b in existing_battles:
            st.write(f"- **{b['team_a']} vs {b['team_b']}** ({b['start_date']} → {b['end_date']})")
            if b["winner"]: st.success(f"Winner: {b['winner']} (+{b['reward_points']} pts per team member)")
    colA, colB = st.columns(2)
    with colA:
        team_a = st.text_input("Team A", value=(u.get("team") or "Comeback Kids"))
        team_b = st.text_input("Team B", value="Challengers")
    with colB:
        battle_days = st.number_input("Battle length (days)", min_value=1, max_value=30, value=7)
        battle_reward = st.number_input("Reward points per member", min_value=0, max_value=1000, value=100, step=10)
        if st.button("Create Battle"):
            if team_a and team_b and team_a != team_b: create_team_battle(team_a.strip(), team_b.strip(), battle_days, battle_reward)
            else: st.error("Pick two different teams.")

# Rewards
with tab_rewards:
    st.subheader("Rewards & Badges")
    u = ensure_user(user_id, display_name); check_and_award_badges(user_id)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Your Status")
        st.metric("Points", int(u.get("points",0))); st.metric("Tier", tier_for_points(int(u.get("points",0))))
        earned = st.session_state.badges.get(user_id, set())
        st.write("**Badges Earned:** " + (", ".join(earned) if earned else "None yet"))
        st.write("**Momentum**")
        st.progress(min(total_walk_count(u)/10,1.0), text=f"First 10 Walks: {total_walk_count(u)}/10")
        st.progress(min(total_miles_all_time(u)/100.0,1.0), text=f"100 Miles: {total_miles_all_time(u):.1f}/100.0")
    with col2:
        st.markdown("### Redeem Rewards")
        catalog = st.session_state.reward_catalog
        for item in catalog:
            c = st.container(border=True)
            with c:
                st.write(f"**{item['name']}** — {item['desc']} ({item['cost']} pts)")
                can_redeem = int(u.get("points",0)) >= int(item["cost"])
                if st.button(f"Redeem '{item['name']}'", disabled=not can_redeem, key=f"redeem_{item['id']}"):
                    u["points"] -= int(item["cost"]); st.success(f"Redeemed {item['name']}!")
    st.divider(); st.write("### Monthly Prizes"); st.caption("Top walkers each month receive gift cards or exclusive challenge unlocks.")

# Routes
with tab_routes:
    st.subheader("Training Log & Routes")
    rc1, rc2 = st.columns([2,1])
    with rc1:
        route_name = st.text_input("Route name")
        route_km = st.number_input("Distance (km)", min_value=0.1, max_value=200.0, value=3.0, format="%.2f")
        route_notes = st.text_area("Notes (optional)", height=80)
    with rc2:
        if st.button("Add Route"):
            if route_name.strip(): add_route(user_id, route_name.strip(), route_km, route_notes.strip()); st.success(f"Route '{route_name}' added.")
            else: st.error("Please provide a route name.")
    user_routes = list_routes(user_id)
    if user_routes:
        st.write("### My Routes")
        df = pd.DataFrame(user_routes); st.dataframe(df[["name","distance_km","notes","created_at"]], use_container_width=True)
        del_name = st.selectbox("Delete a route", [""] + [r["name"] for r in user_routes])
        if st.button("Delete Selected Route"):
            if del_name: delete_route(user_id, del_name); st.success(f"Deleted route '{del_name}'.")
    else:
        st.info("No routes yet — add your first route above.")

# Messages
with tab_messages:
    st.subheader("Messages")
    u = ensure_user(user_id, display_name)
    buddy_choices = sorted(list(u.get("buddies", set())))
    buddy = st.selectbox("Select a buddy", [""] + buddy_choices, index=0)
    if buddy:
        msgs = get_conversation(user_id, buddy)
        for m in msgs:
            who = "You" if m["from"] == user_id else st.session_state.users.get(m["from"],{}).get("name", m["from"])
            st.write(f"**{who}** [{m['ts']}]: {m['text']}")
        new_msg = st.text_input("Write a message")
        if st.button("Send"):
            if new_msg.strip(): send_message(user_id, buddy, new_msg.strip()); st.experimental_rerun()
    else:
        st.info("Add buddies from the Community tab to start messaging.")

st.caption("Prototype uses local in-memory storage. For production, switch to a database + auth.")
