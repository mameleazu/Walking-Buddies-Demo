import os
import time
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

# -----------------------
# App Metadata
# -----------------------
APP_NAME = "Walking Buddies"
st.set_page_config(page_title=APP_NAME, page_icon="👟", layout="wide")

# -----------------------
# Simple in-memory store (replace with DB for production)
# -----------------------
if "users" not in st.session_state:
    st.session_state.users = {}  # user_id -> dict
if "teams" not in st.session_state:
    st.session_state.teams = {}  # team_name -> dict
if "activities" not in st.session_state:
    st.session_state.activities = []  # list of dicts
if "invites" not in st.session_state:
    st.session_state.invites = []

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

# -----------------------
# Helpers
# -----------------------
def calc_streak(dates: list[datetime]) -> int:
    """Return the current daily streak length given a list of walk dates"""
    if not dates:
        return 0
    dates_sorted = sorted(set([d.date() for d in dates]), reverse=True)
    streak = 0
    day = datetime.now().date()
    for d in dates_sorted:
        if d == day - timedelta(days=streak):
            streak += 1
        elif d < day - timedelta(days=streak):
            break
    return streak

def tier_for_points(points: int) -> str:
    for name, threshold in TIERS:
        if points >= threshold:
            return name
    return "Bronze"

def award_points(user_id: str, minutes: int, is_group: bool, shared_photo: bool):
    user = st.session_state.users.setdefault(user_id, {"points": 0, "walk_dates": [], "team": None, "name": user_id})
    # Base points
    gained = minutes * POINT_RULES["base_per_minute"]
    # Group walk bonus
    if is_group:
        gained += POINT_RULES["group_walk_bonus"]
    # Photo share
    if shared_photo:
        gained += POINT_RULES["photo_share"]
    # Streaks
    streak = calc_streak(user["walk_dates"] + [datetime.now()])
    if streak >= 30:
        gained += POINT_RULES["streak_30"]
    elif streak >= 7:
        gained += POINT_RULES["streak_7"]
    # Update
    user["points"] += gained
    user["walk_dates"].append(datetime.now())
    return gained, user["points"], streak

def invite_friend(inviter_id: str, friend_email: str):
    st.session_state.invites.append({"inviter": inviter_id, "friend": friend_email, "ts": time.time()})
    user = st.session_state.users.setdefault(inviter_id, {"points": 0, "walk_dates": [], "team": None, "name": inviter_id})
    user["points"] += POINT_RULES["invite_bonus"]
    return user["points"]

def get_leaderboards():
    users_df = pd.DataFrame([
        {"user": u.get("name", uid), "points": u.get("points", 0), "team": (u.get("team") or "")}
        for uid, u in st.session_state.users.items()
    ])
    team_points = {}
    for uid, u in st.session_state.users.items():
        t = u.get("team")
        if t:
            team_points[t] = team_points.get(t, 0) + u.get("points", 0)
    teams_df = pd.DataFrame([{"team": k, "points": v} for k, v in team_points.items()])
    users_df = users_df.sort_values("points", ascending=False).reset_index(drop=True)
    teams_df = teams_df.sort_values("points", ascending=False).reset_index(drop=True)
    return users_df, teams_df

# -----------------------
# Sidebar: Profile & Team
# -----------------------
st.sidebar.title("👤 Profile")
user_id = st.sidebar.text_input("Your username", value="martha")
display_name = st.sidebar.text_input("Display name", value="Martha")
if st.sidebar.button("Save Profile"):
    st.session_state.users.setdefault(user_id, {"points": 0, "walk_dates": [], "team": None, "name": display_name})
    st.session_state.users[user_id]["name"] = display_name
    st.success("Profile saved!")

st.sidebar.markdown("---")
st.sidebar.title("👥 Team")
team_name = st.sidebar.text_input("Create/Join team", value="Comeback Kids")
if st.sidebar.button("Join Team"):
    u = st.session_state.users.setdefault(user_id, {"points": 0, "walk_dates": [], "team": None, "name": display_name})
    u["team"] = team_name
    st.session_state.teams.setdefault(team_name, {"captain": user_id, "members": set()})
    st.session_state.teams[team_name]["members"].add(user_id)
    st.success(f"You joined team: {team_name}")

st.sidebar.markdown("---")
st.sidebar.title("🔔 Reminders")
col1, col2 = st.sidebar.columns(2)
with col1:
    st.checkbox("Walk reminders", value=True)
with col2:
    st.checkbox("Stand/stretch", value=True)
st.sidebar.info("Reminders are simulated here; wire to FCM/APNs in production.")

# -----------------------
# Main Tabs
# -----------------------
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
    st.dataframe(users_df.head(10), use_container_width=True)
    st.write("### Top Teams")
    st.dataframe(teams_df.head(10), use_container_width=True)

with tab_log:
    st.subheader("Log a Walk")
    minutes = st.number_input("Minutes walked", min_value=1, max_value=300, value=30)
    is_group = st.checkbox("Group walk")
    shared_photo = st.checkbox("Shared a photo")
    if st.button("Submit Walk"):
        gained, total, streak = award_points(user_id, minutes, is_group, shared_photo)
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
    st.dataframe(users_df, use_container_width=True)
    st.write("#### Teams")
    st.dataframe(teams_df, use_container_width=True)

with tab_challenges:
    st.subheader("Challenges")
    st.write("- **Daily Step Goal**: Hit 5,000 steps for bonus points")
    st.write("- **Weekend Walkathon**: Walk 10 miles over the weekend")
    st.write("- **Photo Challenge**: Share a scenic walk photo")
    st.write("- **Invite Challenge**: Invite 3 friends this month")
    st.info("Logic is demoed via 'Log Walk' and 'Invite' above. Connect real step data via Apple Health/Google Fit APIs.")

with tab_rewards:
    st.subheader("Rewards & Tiers")
    user = st.session_state.users.get(user_id, {"points": 0, "walk_dates": [], "team": None, "name": display_name})
    current_tier = tier_for_points(user["points"])
    st.metric("Your Points", user["points"])
    st.metric("Your Tier", current_tier)
    st.write("**Rewards Examples**")
    st.write("- Digital Badges (milestones)")
    st.write("- Discount Codes (sneakers/wellness)")
    st.write("- Gift Cards (top monthly walkers)")
    st.write("- Exclusive Challenges (higher tiers)")

with tab_routes:
    st.subheader("Training Log & Routes (Demo)")
    st.write("Save past routes & share with friends. Use Mapbox/Google Maps SDK for GPS tracking in production.")
    st.code("POST /api/route  -> Save a route\nGET  /api/route  -> List routes")

st.caption("Prototype: Local-memory only. Replace with a database and auth for production.")
