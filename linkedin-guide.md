# Putting AI Lecture Notes on LinkedIn

You decided to wait until two projects are done and a third is underway
before linking GitHub from LinkedIn. This is the plan for when you're ready,
in the order that matters. Copy-paste text is in the boxes; edit to your voice.

Repo link everywhere below: `https://github.com/mrgutierrezmario/lecture-note-app`
GitHub profile link: `https://github.com/mrgutierrezmario`

---

## 1. Contact info → Websites (30 seconds, do first)

Profile → **Contact info** (under your name) → pencil → **Websites** → *Add
website* → URL `https://github.com/mrgutierrezmario`, type **Portfolio**.

This is the link recruiters actually click. Use the *profile* URL, not the
repo, so it stays valid as you add projects.

## 2. Featured section (the part with the most eyes)

Profile → **Add profile section** → *Recommended* → **Add featured** → **Add a
link** → paste the repo URL. LinkedIn pulls the title, description and the
social-preview image from GitHub — that's why the preview image matters.
Set it on GitHub first (Settings → General → Social preview).

You can edit the Featured card's title/description after adding it:

```
AI Lecture Notes — self-hosted lecture recorder with live transcription and AI notes
Records lectures in the browser, transcribes live with Whisper, builds structured
notes as the lecture runs, and answers questions afterwards. FastAPI · React ·
PostgreSQL · Docker · Claude/Gemini/Ollama.
```

## 3. Projects section (the detail)

Profile → **Add profile section** → *Additional* → **Add projects**.

| Field | What to put |
|---|---|
| Project name | `AI Lecture Notes` |
| Description | (box below) |
| Skills | Python, FastAPI, React, PostgreSQL, Docker, WebSockets, REST APIs, OAuth 2.0, LLM integration, Speech Recognition, CI/CD, Linux, System Administration |
| Media | *Add link* → the repo URL |
| Start date | **Jan 2026** — End: leave "currently working on this" checked |
| Associated with | your business (M.G. Network and Technology Solutions) if it's listed as Experience; otherwise leave blank |

Description (LinkedIn allows ~2,000 characters; this is ~1,100):

```
Self-hosted lecture-capture platform I built and run for my own graduate coursework — in daily use since March 2026, released as v1.0.0 in September 2026.

What it does: records a lecture from the browser (desktop or phone), transcribes it live with Whisper, turns the transcript into structured notes as the lecture runs, and answers questions about it afterwards from the transcript, notes and uploaded slides. Exports to PDF, Word, Markdown and MP3, or straight into the user's own Google Drive.

What's under it: FastAPI + WebSockets backend, React front end, PostgreSQL, MinIO (S3), Docker Compose on a Mac mini with a fixed public HTTPS URL via Tailscale Funnel. Pluggable AI providers (local Ollama, Claude, Gemini, OpenAI) with automatic fallback. Multi-user accounts with email verification and admin approval, OAuth 2.0 for Google Drive, per-user quotas and retention, nightly encrypted off-site backups with a scripted restore drill, uptime monitoring, tests + CI, Dependabot.

Developed with Claude Code as a pair-programming assistant; every feature came from real classroom use and the problems it surfaced.
```

## 4. Skills section

Profile → **Skills** → add any of these you don't already list, so recruiter
searches match: `FastAPI`, `React.js`, `PostgreSQL`, `Docker`, `WebSockets`,
`OAuth`, `Large Language Models (LLM)`, `Speech Recognition`, `CI/CD`,
`Python`, `JavaScript`. Then on the project (step 3) tick the same skills —
LinkedIn shows "1 project" under each skill.

## 5. About section — one sentence to add

At the end of your existing About text:

```
Outside work I build and operate production software end to end — most recently AI Lecture Notes, a self-hosted lecture transcription and note-taking platform (github.com/mrgutierrezmario).
```

## 6. Headline (optional, only if it's currently generic)

If your headline is just a job title, a second clause helps searches:

```
Network & Systems Engineer · builds self-hosted tools with Python, React and Docker
```

## 7. The post (when you're ready to announce it)

A post gets the project in front of your network once; the profile sections
above keep it there. Post with the repo link so LinkedIn attaches the preview
card. Keep it short and concrete:

```
Over the last eight months I built something for my own grad classes and just released it as open source: AI Lecture Notes.

Hit record in the browser, and it transcribes the lecture live, builds structured notes as the professor talks, and lets you ask questions about the lecture afterwards — from the transcript, the notes and the slides. Everything runs on a Mac mini at home: FastAPI, React, PostgreSQL, Docker, with Whisper for speech and Claude/Gemini/local Ollama for the notes.

The interesting work wasn't the AI part — it was making it dependable: accounts, backups you've actually restored from, monitoring, a fixed HTTPS URL without owning a domain, and surviving phones going to sleep mid-lecture.

Code, screenshots and the full setup guide: https://github.com/mrgutierrezmario/lecture-note-app
```

## Order of operations, when the time comes

1. GitHub: set the social preview image; make sure the profile README exists
   (`design/profile-README.md` draft, still to fill in).
2. LinkedIn: Contact info link → Featured → Projects → Skills → About.
3. Paste the repo URL into a draft post to check the card renders, then post.

---

# Adding InsiderTrack (second project)

Repo link: `https://github.com/mrgutierrezmario/insidertrack` · live site:
`https://mgnts-stock-tracker.tail3659a6.ts.net` · social preview already set.

## Featured card

```
InsiderTrack — who in Congress is buying, and whether their bets pay off
Congressional, corporate-insider (SEC Form 4) and 13F fund trades from the
official filings, scored per ticker and checked against the market.
FastAPI · React · PostgreSQL · Docker · Claude/Gemini vision for scanned filings.
```

## Projects section

| Field | What to put |
|---|---|
| Project name | `InsiderTrack` |
| Skills | Python, FastAPI, React, TypeScript, PostgreSQL, Docker, Data Engineering, Web Scraping, REST APIs, LLM integration, Computer Vision, CI/CD, Linux |
| Media | *Add link* → the repo URL, and a second link → the live site |
| Start date | **May 2026** — End: "currently working on this" |

Description (~1,150 characters):

```
Open-source research tool that collects the stock trades U.S. legislators, company insiders and large funds are legally required to disclose, and turns them into something you can act on: a 0–100 score per ticker built from who is buying, and a track record for every member of Congress — each disclosed purchase measured against the S&P 500 at 30/60/90 days, which then weights that member's trades in the score.

Data comes straight from the House Clerk, the Senate EFD and SEC EDGAR (Form 4 daily index, 13F). About one House filing in eight is a scanned, handwritten form; those are read by a vision model (Claude / Gemini) and flagged as such. Amendments are reconciled, duplicate member records merged, and every scraper reports its own health so a government site changing under the parser gets noticed the same day.

Stack: FastAPI, React + TypeScript, PostgreSQL, Docker Compose with a fixed public HTTPS URL via Tailscale Funnel; encrypted off-site backups with scripted restore; CI on every push; 290+ tests. Released v1.1.0 in September 2026.
```

## The post

```
Second open-source release: InsiderTrack.

Members of Congress, company executives and big funds all have to disclose their stock trades. I built a tool that pulls those filings from the official sources — including the handwritten ones, read by a vision model — scores every ticker on who's buying, and answers the question nobody's site does: does following this person actually beat the market? Every member gets a track record, and it feeds back into the score.

FastAPI, React, PostgreSQL, Docker, running on a Mac at home with a fixed public URL. The hard parts were the same as last time: data that lies to you, sites that change, and making it dependable enough to trust every morning.

Code and a full guide: https://github.com/mrgutierrezmario/insidertrack
Live: https://mgnts-stock-tracker.tail3659a6.ts.net
```
