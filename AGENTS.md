# Project Profile: CuratedBytes (`curatedbytes.dev`)
An intelligent, serverless, high-signal Super App bundling aggregated tech news and personalized job screening into a single unified workspace.

## 1. Architectural Philosophy (The Constraints)
*   **Infrastructure Cost:** Strictly **£0/month**.
*   **Compute Engine:** Serverless, event-driven cron loop via **GitHub Actions**. No 24/7 running compute or containers (AVOID AWS ECS / Fargate).
*   **Storage Layer:** Fully database-free. State and content payloads are stored as flat, sharded static JSON files (`news.json`, `jobs.json`).
*   **Hosting & Delivery:** Client-side static assets are compiled via **Vite** and delivered globally via **GitHub Pages**.
*   **Network Security:** Routed and proxied via **Cloudflare DNS** with strict browser-enforced **HSTS/HTTPS** security enabled.

---

## 2. System Design Map
```mermaid
graph TD
    subgraph Background Automation Pipeline (GitHub Actions - Hourly Cron)
        A[GitHub Actions Runner] --> B[Execute: scraper/main.py]
        B --> C[Fetch RSS Feeds & Greenhouse/Lever ATS APIs]
        C --> D[Filter Out Duplicates via Local MD5 URL Hashing]
        D --> E[Inference Layer: Google AI Studio Gemini API Free Tier]
        E -- 1. Cluster & Summarize News --> F[Output: news.json]
        E -- 2. Match-Score & Analyze Jobs against CV --> G[Output: jobs.json]
        E -- 3. Dispatch High-Match Alerts Score >= 85 --> H[Execute: Slack Webhook]
    end

    subgraph Frontend Compilation & Distribution (GitHub Pages)
        F & G --> I[Inject into web-dashboard/public/]
        I --> J[Execute: npm run build]
        J --> K[Deploy flat dist folder to GitHub Pages]
        K --> L[Serve globally on curatedbytes.dev via Cloudflare Proxy]
    end
```

---

## 3. Tech Stack Matrix
*   **Backend / Automation:** Python 3.11 (`feedparser`, `requests`, `google-genai` SDK)
*   **Frontend Engine:** React 19, TypeScript, Vite
*   **Styling & UI Components:** Tailwind CSS (Responsive Dashboard, High-Density Layout)
*   **AI Processing Layer:** Gemini 2.5 Flash via Google AI Studio Console (Free Tier: 15 RPM limits)
*   **Notification Layer:** Slack Incoming Webhooks (Block Kit layout formatting)

---

## 4. Current State & Immediate Milestones
- [x] Purchase and secure domain `curatedbytes.dev` on Cloudflare with WHOIS Privacy.
- [x] Configure Cloudflare network infrastructure (DNS Records, Always Use HTTPS, HSTS preload compliance).
- [x] Implement deterministic Python ingestion framework with built-in Gemini Pydantic schema constraints.
- [x] Define responsive, high-density React TypeScript tabbed workspace layout.
- [ ] Initialize git repository layout and push boilerplate workspace tracking tables.
- [ ] Connect repository encrypted environment values (`GEMINI_API_KEY`, `SLACK_WEBHOOK_URL`).
- [ ] Trigger first end-to-end automated GitHub Actions build run to verify cross-compilation mapping.

---

## 5. Instructions for AI Agents / Workspace Context
When generating or modifying code for this project, you must adhere to the following rules:
1.  **Keep it Decoupled:** Maintain strict separation between the Python scraper pipeline (`/scraper`) and the React UI frontend (`/web-dashboard`). Do not introduce runtime interdependencies.
2.  **Enforce Schema Integrity:** Ensure any changes to the Python Pydantic output schemas perfectly match the client-side TypeScript interfaces (`NewsItem` and `JobItem` in `App.tsx`) to prevent build-time breakage.
3.  **Optimize for Free Tiers:** Do not introduce heavy libraries that increase compilation sizes or exceed GitHub Actions memory bounds. Keep calls to the Gemini API batched to stay well inside the 15 RPM free-tier throttle caps.
4.  **No Server Actions / Side Effects:** The frontend must remain 100% static. It interacts with data exclusively via native browser client-side `fetch()` hooks hitting the generated local JSON assets.
