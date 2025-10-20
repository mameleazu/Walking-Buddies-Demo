# Walking Buddies — Health Universe Starter (Fixed)

Fixes the `KeyError: 'points'` by hardening the leaderboards and empty-state handling.

## Files
- `app/app.py` — Streamlit UI (recommended entrypoint)
- `main.py` — same as app/app.py for platforms that expect main.py
- `api/fastapi.py` — optional REST microservice for routes
- `requirements.txt`
- `README.md`

## Deploy (Health Universe / Streamlit)
- Entrypoint: `streamlit run app/app.py`  *(or `streamlit run main.py`)*
- Add secrets (DB_URL, STRAVA_CLIENT_ID, MAPBOX_TOKEN) via platform secrets.
- Deploy.

## Local Run
```bash
pip install -r requirements.txt
streamlit run app/app.py
# Optional API: uvicorn api.fastapi:app --reload
```
