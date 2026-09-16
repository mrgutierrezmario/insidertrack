# InsiderTrack — Setup Guide

Congressional trade tracker with whale (13F) filings, corporate insider (Form 4) data, composite signal scores, AI summaries, and automated email reports.

---

## What You Need Before Starting

| Requirement | Minimum Version | Check |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |
| PostgreSQL | 14+ | `psql --version` |

**PostgreSQL options:**
- Install it locally (recommended for development)
- Or use Docker — the included `docker-compose.yml` handles it automatically

**Optional API keys** (the app runs without them, but features are limited):

| Key | What it unlocks | Where to get it |
|---|---|---|
| `ALPHA_VANTAGE_KEY` | Intraday stock charts (1min–60min) | [alphavantage.co](https://www.alphavantage.co/support/#api-key) — free tier |
| `ANTHROPIC_API_KEY` | AI research summaries on each ticker | [console.anthropic.com](https://console.anthropic.com/) |
| Gmail App Password | Scheduled email reports | Google Account → Security → App Passwords |

---

## Step 1 — Clone the Repository

```bash
git clone <your-repo-url>
cd stock-tracker
```

---

## Step 2 — Create Your `.env` File

Copy the template and fill in your values:

```bash
cp .env.example .env   # if .env.example exists
# — or create it manually:
```

Create a file called `.env` in the `stock-tracker/` root (same folder as `docker-compose.yml`) with the following contents:

```env
# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql://stockuser:stockpass@localhost:5432/stocktracker
POSTGRES_USER=stockuser
POSTGRES_PASSWORD=stockpass
POSTGRES_DB=stocktracker

# ── App ───────────────────────────────────────────────────────────────────────
BACKEND_PORT=8003
FRONTEND_PORT=5176

# ── Optional: Alpha Vantage (free tier works) ─────────────────────────────────
ALPHA_VANTAGE_KEY=

# ── Optional: Anthropic (for AI summaries) ────────────────────────────────────
ANTHROPIC_API_KEY=

# ── Optional: Gmail SMTP (for email reports) ──────────────────────────────────
# Create an App Password at: myaccount.google.com/apppasswords
MAIL_USERNAME=you@gmail.com
MAIL_PASSWORD=xxxx xxxx xxxx xxxx
MAIL_FROM=you@gmail.com
MAIL_FROM_NAME=InsiderTrack
```

> **Note:** `DATABASE_URL` must match `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` exactly.

---

## Step 3 — Set Up PostgreSQL

### Option A: Local PostgreSQL (already installed)

```bash
# Create the database and user
psql -U postgres -c "CREATE USER stockuser WITH PASSWORD 'stockpass';"
psql -U postgres -c "CREATE DATABASE stocktracker OWNER stockuser;"
```

### Option B: Docker (no local PostgreSQL needed)

```bash
# Start only the database container
docker-compose up -d db

# Confirm it is running
docker-compose ps
```

The database will be available on port **5433** (mapped from the container's 5432).  
Update `DATABASE_URL` in your `.env` to use port 5433:

```env
DATABASE_URL=postgresql://stockuser:stockpass@localhost:5433/stocktracker
```

---

## Step 4 — Start the App

### Easiest: One-command startup

From the `stock-tracker/` directory:

```bash
bash start.sh
```

This script will:
1. Check all prerequisites
2. Start PostgreSQL (local or Docker, whichever is available)
3. Install Python dependencies
4. Install Node dependencies (first run only)
5. Build the frontend
6. Start the backend server

The app will be available at **http://localhost:8003**

Press `Ctrl+C` to stop everything.

---

### Manual startup (step by step)

If you prefer to run each piece yourself:

**1. Install Python packages**
```bash
cd backend
pip install -r requirements.txt
```

**2. Install and build the frontend**
```bash
cd ../frontend
npm install
npm run build
```

**3. Start the backend**
```bash
cd ../backend
uvicorn main:app --host 0.0.0.0 --port 8003 --reload
```

The app and all its pages are served from **http://localhost:8003** — no separate frontend server is needed. The built frontend lives in `frontend/dist/` and FastAPI serves it as static files.

---

## Step 5 — First-Time Configuration

1. Open **http://localhost:8003** in your browser
2. Accept the disclaimer
3. Go to **Config** (gear icon, top right)
4. Paste in any API keys (Alpha Vantage, Anthropic)
5. Configure email settings if you want scheduled reports

> API keys entered in the Config page are saved to the database — you don't need to restart after adding them.

---

## Step 6 — Load Your First Data

From the **Dashboard** page, click **⟳ Sync** to pull congressional trade disclosures from the SEC.

This will:
- Fetch the latest STOCK Act filings
- Run the morning analysis
- Populate the Trade Feed, Signals, and Markets pages

From the **Insiders** page, click **↻ Sync Form 4 Filings** to pull corporate insider (SEC Form 4) trades for all tracked tickers.

From the **Whales** page, click **↻ Sync 13F Filings** to pull institutional holdings.

---

## Daily Schedule (Automatic)

Once running, the scheduler fires automatically:

| Time (ET) | Job |
|---|---|
| 6:30 AM | Corporate insider (Form 4) sync |
| 6:45 AM | Price history warm-up |
| 7:00 AM | Signal outcome snapshot |
| 7:15 AM | Sync Federal Reserve official disclosures |
| 7:30 AM | Outcome price fill |
| 8:00 AM | Morning analysis + email |
| 12:00 PM | Midday analysis + email |
| 6:00 PM | Evening analysis + email |
| 8:15, 12:15, 6:15 PM | Alert evaluation |

---

## Troubleshooting

**"Could not connect to database"**  
Check that PostgreSQL is running and the credentials in `.env` match what you created in Step 3.

**"No trades match these filters" / empty Trade Feed**  
Click **⟳ Sync** on the Dashboard first to pull data.

**Markets shows demo data**  
This is expected until you sync trades — movers are computed from tracked ticker price history. Once you sync, live data appears.

**Intraday charts show "(no key)"**  
Add your `ALPHA_VANTAGE_KEY` in the Config page. The free tier supports 25 requests/day.

**AI summaries don't appear**  
Add your `ANTHROPIC_API_KEY` in the Config page.

**Email reports not sending**  
Ensure `MAIL_USERNAME` and `MAIL_PASSWORD` (Gmail App Password) are set. `MAIL_FROM` is optional — it defaults to `MAIL_USERNAME` if omitted. Regular Gmail passwords won't work — you need an [App Password](https://myaccount.google.com/apppasswords).

**Backend won't start / import errors**  
```bash
cd backend
pip install -r requirements.txt
```

**Frontend changes not showing**  
Rebuild after any frontend edits:
```bash
cd frontend
npm run build
```

---

## Project Structure

```
stock-tracker/
├── .env                  ← Your credentials (never commit this)
├── docker-compose.yml    ← PostgreSQL container
├── start.sh              ← One-command startup
├── backend/
│   ├── main.py           ← FastAPI app entry point
│   ├── config.py         ← Reads .env settings
│   ├── database.py       ← SQLAlchemy setup + table init
│   ├── models/           ← Database models
│   ├── routers/          ← API endpoints
│   └── services/         ← Data fetchers, scheduler, email, AI
└── frontend/
    ├── src/
    │   ├── pages/        ← One file per page
    │   ├── components/   ← Shared UI components
    │   └── lib/api.js    ← All backend API calls
    └── dist/             ← Built output (served by FastAPI)
```

---

## Admin Access

The admin password is `191919` by default. It is required to delete politicians from the tracking list. Change it by setting `ADMIN_PASSWORD=yourpassword` in your `.env` file.

---

*InsiderTrack — M.G. Network & Technology Solutions*
