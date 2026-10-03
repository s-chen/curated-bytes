# CuratedBytes (`curatedbytes.dev`)

Aggregates tech news and screens job postings against a CV, served as a static dashboard. An hourly GitHub Actions job produces JSON; the React frontend only reads it.

## Stack & Constraints
- **Cost: strictly £0/month.** No always-on compute or containers (no ECS/Fargate), no database.
- **Pipeline:** Python 3.11 (`feedparser`, `requests`, `google-genai`, Pydantic) run by a GitHub Actions hourly cron.
- **AI:** Gemini Flash via Google AI Studio free tier. Verify the current RPM limit (was 15 RPM for 2.5 Flash) before relying on it.
- **Storage:** flat static JSON (`news.json`, `jobs.json`) in `web-dashboard/public/`.
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS. Dense, responsive, tabbed layout.
- **Hosting:** GitHub Pages behind Cloudflare DNS/proxy, HTTPS + HSTS enforced.
- **Alerts:** Slack incoming webhook (Block Kit) for job matches with score >= 85.

## Data Flow
`RSS + Greenhouse/Lever APIs → dedupe (MD5 of URL) → Gemini (cluster/summarise news, score jobs vs CV) → news.json / jobs.json → npm run build → GitHub Pages`, with a Slack alert on high-match jobs.

## Layout
```
scraper/                       Python pipeline (entry: scraper/main.py)
web-dashboard/                 Vite + React app
web-dashboard/public/*.json    Generated data consumed by the UI
.github/workflows/             Cron + build/deploy
```
(Directories are created as the code lands; update this tree when they do.)

## Commands
<!-- Fill in once the code exists; keep this section accurate. -->
- Scraper: `TODO`
- Frontend dev / build: `TODO` (`npm run build` in `web-dashboard/`)
- Lint / test: `TODO`

## Rules
1. **Keep it decoupled.** `scraper/` and `web-dashboard/` share no runtime code. The only contract is the JSON files.
2. **Schema parity.** Pydantic output models in `scraper/` must match the `NewsItem` and `JobItem` TypeScript interfaces in `web-dashboard/src/App.tsx`. Change both together.
3. **Free-tier discipline.** Batch Gemini calls and throttle to stay under the RPM limit. Prefer the stdlib; justify any new dependency (bundle size and Actions memory both matter).
4. **No backend.** The frontend is 100% static and only `fetch()`es the generated JSON.
5. **Secrets.** `GEMINI_API_KEY` and `SLACK_WEBHOOK_URL` come from environment variables (GitHub Actions secrets). Never commit them or the CV.

## Open Design Questions
- **Dedupe state:** seen-URL hashes must persist between runs (committed state file or Actions cache). Not yet decided.
- **Privacy:** `jobs.json` is published on a public site. Decide whether job scores/analysis go there or stay Slack-only.
