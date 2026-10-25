# ICAI Batch Monitor (100% free)

Checks the ICAI "Launch Batch Details" page every 15 minutes for
**Central → Indore → Advanced ITT / MCS** and messages you on Telegram when a
batch is new, removed, or its seats/details change.

It runs on **GitHub Actions** (no server, no card, no payment). A real headless
browser (Playwright) picks the Region, POU and Course dropdowns, so the
ASP.NET dropdown/postback problem that breaks normal scrapers does not apply.

## Setup (about 10 minutes)

### 1. Create the Telegram bot
1. In Telegram, open **@BotFather** → send `/newbot` → follow the prompts. Copy the **bot token**.
2. Open your new bot and press **Start** (send it any message). Bots cannot message you first.
3. Get your chat id: open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the number at `"chat":{"id": ...}`.

### 2. Create the GitHub repo
1. Create a new repository and make it **Public** (see "Why public?" below).
2. Upload all files of this folder, keeping the `.github/workflows/icai.yml` path.

### 3. Add secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:
- `TELEGRAM_BOT_TOKEN` = the bot token
- `TELEGRAM_CHAT_ID` = your chat id

### 4. Run it
Repo → **Actions** tab → enable workflows → **ICAI batch monitor → Run workflow**.
The first run sends a "monitor started" message listing the current batches.
After that it runs by itself every ~15 minutes.

## Which courses are watched
Edit `DEFAULT_COURSES` in `monitor.py` (or set a repo variable `ICAI_COURSES`
separated by `|`). The dropdown has these courses:

- Advanced (ICITSS) MCS Course
- Advanced (ICITSS) MCS Course - Weekend
- AICITSS - Advanced Information Technology  *(treated as "Advanced ITT")*
- ICITSS - Information Technology
- ICITSS - Orientation Course

Remove the weekend MCS line if you do not want it.

## Why public?
- Public repos get unlimited free Actions minutes.
- Private repos get 2,000 free minutes/month; a run every 15 min needs roughly
  3,000-4,500, so a private repo would run out mid-month.
- Your Telegram token/chat id stay hidden in Secrets. Only `state.json`
  (batch names and seat counts) is visible, which is public information anyway.

## Things to know
- GitHub's scheduler is best-effort: a "15 min" run can start a few minutes late, occasionally more under load.
- GitHub pauses scheduled workflows in a public repo after 60 days without repo
  activity. Because state.json is committed whenever batches change, this is
  usually not an issue, but if alerts stop, open Actions and re-enable it.
- If the site layout changes or a run fails, the job turns red and GitHub emails you.
  Download the **debug** artifact from that run (screenshot + HTML) to see what the page looked like.

## Free alternatives to Render
Render's free web service sleeps when idle and its cron jobs are paid, so it is a poor fit.
Check each provider's current free terms before relying on them:

| Option | Free? | Fit |
|---|---|---|
| **GitHub Actions** (this project) | Yes, no card | Best: built-in scheduler + browser |
| Hugging Face Spaces (Docker) | Yes, no card | Works, but sleeps when idle; needs an internal loop and a pinger |
| Oracle Cloud Always Free VM | Free but needs a card for verification | Full control, runs 24/7 |
| Google Cloud e2-micro | Free tier, needs a card | Same idea, tiny VM |
| Your own PC / old Android phone (Termux) | Yes | Works while the device is on |
| PythonAnywhere free | Yes | No Playwright and restricted outbound access, not suitable |
