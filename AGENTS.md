# CuratedBytes (`curatedbytes.dev`)

Aggregates tech news and screens job postings against a CV, served as a static dashboard. An hourly GitHub Actions job produces JSON; the React frontend only reads it.

## Stack & Constraints
- **Cost: strictly £0/month.** No always-on compute or containers (no ECS/Fargate), no database.
- **Pipeline** (`scraper/`): Python 3.11 (`feedparser`, `requests`, `google-genai`, Pydantic) run by a GitHub Actions hourly cron.
- **AI:** Gemini Flash via Google AI Studio free tier. Verify the current RPM limit (was 15 RPM for 2.5 Flash) before relying on it.
- **Storage:** flat static JSON (`news.json`, `jobs.json`) in `web-dashboard/public/`.
- **Frontend** (`web-dashboard/`): React 19, TypeScript, Vite, Tailwind CSS. Dense, responsive, tabbed layout.
- **Hosting:** GitHub Pages behind Cloudflare DNS/proxy, HTTPS + HSTS enforced.
- **Alerts:** Slack incoming webhook (Block Kit) for job matches with score >= 85.

## Data Flow
`RSS + Greenhouse/Lever APIs → dedupe (MD5 of URL) → Gemini (cluster/summarise news, score jobs vs CV) → news.json / jobs.json → npm run build → GitHub Pages`, with a Slack alert on high-match jobs.

## Commands
- News sources live in `scraper/config/news_sources.json` (`id`, `name`, `url`, `category`, optional `enabled`).
- `docker compose run --rm tests`: scraper test suite.
- `docker compose run --rm scraper`: fetch feeds into `web-dashboard/public/news.json`.
- Without Docker (from `scraper/`): `pip install -e ".[dev]"`, then `pytest` and `python -m scraper`.

## Rules
1. **Keep it decoupled.** `scraper/` and `web-dashboard/` share no runtime code. The only contract is the JSON files.
2. **Schema parity.** Pydantic output models in `scraper/` must match the `NewsItem` and `JobItem` TypeScript interfaces in `web-dashboard/src/App.tsx`. Change both together.
3. **Free-tier discipline.** Batch Gemini calls and throttle to stay under the RPM limit. Prefer the stdlib; justify any new dependency (bundle size and Actions memory both matter).
4. **No backend.** The frontend is 100% static and only `fetch()`es the generated JSON.
5. **Secrets.** `GEMINI_API_KEY` and `SLACK_WEBHOOK_URL` come from environment variables (GitHub Actions secrets). Never commit them or the CV.
