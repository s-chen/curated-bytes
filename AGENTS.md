# CuratedBytes (`curatedbytes.dev`)

Aggregates tech news and screens job postings against a CV, served as a static dashboard. An hourly GitHub Actions job produces JSON; the React frontend only reads it.

## Stack & Constraints
- **Cost: strictly £0/month.** No always-on compute or containers (no ECS/Fargate), no database.
- **Pipeline** (`scraper/`): Python 3.11 (`feedparser`, `requests`, Pydantic) run by a GitHub Actions hourly cron.
- **AI:** Gemini Flash via Google AI Studio free tier, called over REST with `requests` (no SDK). Model from `GEMINI_MODEL` (default `gemini-3.8-flash`); overload/rate-limit errors are retried, then `GEMINI_FALLBACK_MODEL` (default `gemini-3.7-flash`, empty to disable) is tried. Free-tier limits are only shown in AI Studio; check them before adding calls. One request per run reviews new stories and picks top stories.
- **Storage:** flat static JSON (`news.json`, `jobs.json`) in `web-dashboard/public/`.
- **Frontend** (`web-dashboard/`): React 19, TypeScript, Vite, Tailwind CSS. Dense, responsive, tabbed layout.
- **Hosting:** GitHub Pages behind Cloudflare DNS/proxy, HTTPS + HSTS enforced.
- **Alerts:** Slack incoming webhook (Block Kit) for job matches with score >= 85.

## Data Flow
`RSS + Greenhouse/Lever APIs → dedupe (MD5 of URL) → rule filters (code-hosting links, promotions) → Gemini (review every new story, cluster/summarise top stories, score jobs vs CV) → follow top-story article links to find primary sources → keep top stories on a rolling 24h window (3h sticky, 48h "earlier" list) → news.json / jobs.json → npm run build → GitHub Pages`, with a Slack alert on high-match jobs.

## Commands
- News sources live in `scraper/config/news_sources.json` (`id`, `name`, `url`, `category`, optional `enabled`, `weight` 1–3 for how much its coverage counts towards top stories: 3 major outlet, 1 small site, `aggregator: true` for link aggregators like Hacker News, and `engineering: true` for company engineering blogs, whose posts are listed first).
- `docker compose run --rm tests`: scraper test suite.
- `docker compose run --rm scraper`: fetch feeds into `web-dashboard/public/news.json`.
- `docker compose run --rm scraper --sites`: site report, listing sites that aggregators keep linking to but we don't follow (candidates for `news_sources.json`). Reads `news.json` only; `--min-links N` sets the threshold.
- Locally, each run saves Gemini's last request and reply (or error) to `scraper/.debug/gemini-last.json` (git-ignored).
- Without Docker (from `scraper/`): `pip install -e ".[dev]"`, then `pytest` and `python -m scraper`.
- Run the dashboard locally:
  1. `docker compose run --rm scraper` to generate `web-dashboard/public/news.json` (re-run for fresh news, then refresh the page). Export `GEMINI_API_KEY` first: the dashboard only shows stories Gemini has reviewed (`review: "kept"`, newest 100), so without a key new stories stay pending and hidden.
  2. `docker compose up -d dashboard` (add `--build` after changing dependencies), then open http://localhost:5173. Edits to `web-dashboard/src` reload live.
  3. `docker compose logs -f dashboard` for logs; `docker compose down` to stop.
- `docker compose run --rm dashboard npm test` (or `npm run lint`, `npm run build`): dashboard checks.
- Without Docker (from `web-dashboard/`, Node >= 22.12): `npm ci`, then `npm run dev`, `npm test`, `npm run lint`, `npm run build`.

## Rules
1. **Keep it decoupled.** `scraper/` and `web-dashboard/` share no runtime code. The only contract is the JSON files.
2. **Schema parity.** Pydantic output models in `scraper/` must match the `NewsItem`, `TopStory` and `JobItem` TypeScript interfaces in `web-dashboard/src/App.tsx`. Change both together.
3. **Free-tier discipline.** Batch Gemini calls and throttle to stay under the RPM limit. Prefer the stdlib; justify any new dependency (bundle size and Actions memory both matter).
4. **No backend.** The frontend is 100% static and only `fetch()`es the generated JSON.
5. **Secrets.** `GEMINI_API_KEY` and `SLACK_WEBHOOK_URL` come from environment variables (GitHub Actions secrets). Never commit them or the CV.
