# Walking Buddies — Health Universe Starter

This is a **Health Universe–ready** Streamlit starter for the *Walking Buddies* concept:
social, team-based walking with points, tiers, leaderboards, and challenges.

## Features in this starter
- Streamlit UI with tabs: Home, Log Walk, Leaderboards, Challenges, Rewards, Routes
- Points engine with your rules (1 pt/min, streaks, group/photo/invite bonuses)
- Team join, leaderboards (users & teams)
- Placeholder routes & challenges
- Minimal FastAPI service (optional)

> **Note:** This prototype uses in-memory storage for demo. Replace with a managed DB
(e.g., Postgres/Supabase/Firebase) and enable OAuth for production.

---

## Run Locally
```bash
pip install -r requirements.txt
streamlit run app/app.py
# (Optional API) uvicorn api.fastapi:app --reload
```

---

## Deploy to Health Universe

Follow their quick-start docs for Streamlit/FastAPI deployment.

### 1) Prepare your repo/archive
Include at minimum:
```
/app/app.py
/api/fastapi.py        # optional
requirements.txt
README.md
```

### 2) Create Secrets (if using external services)
Health Universe stores API keys/credentials in its Secrets manager.
Create entries like:
```
DB_URL=...
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
MAPBOX_TOKEN=...
```
Then in code, read via `os.getenv("DB_URL")`, etc.

### 3) Deploy
- Log in and open your workspace
- Choose **Deploy App** → **Streamlit**
- Point to your repo or upload a zip of this folder
- Set the **entrypoint** to: `streamlit run app/app.py`
- Add environment variables/secrets as needed
- Click **Deploy**

Docs:
- Overview: https://docs.healthuniverse.com/overview
- Deploying Streamlit/FastAPI: https://docs.healthuniverse.com/overview/building-apps-in-health-universe/deploying-your-app-to-health-universe

### 4) After Deploy
- Configure **Tasks/Workers** for scheduled jobs (e.g., weekly challenge resets)
- Add **Custom Applications** or **EHR Integration** if required by your plan

---

## Next Steps (Production Hardening)
- Replace in-memory state with a database
- Add authentication (email/password, OAuth)
- Integrate Apple Health/Google Fit/Strava
- Connect push notifications (FCM/APNs)
- Partner rewards catalog + redemption flow
- Anti-cheat & fraud checks for points

© 2025 Walking Buddies
