# JobHunt AI — AI-powered job discovery & resume matching

Upload a resume, press **RUN**, and the platform:

1. analyses the resume (PDF/DOCX) into a verified, editable profile;
2. generates search keywords;
3. searches job boards and aggregators;
4. discovers IT companies (small, medium and large) and finds their **official career pages / ATS boards**;
5. collects, normalises and de-duplicates postings;
6. scores every job 0–100 against the resume with a transparent breakdown;
7. shows everything in a dashboard. RUN again any time to find newly posted jobs (marked **NEW**).

No job data is ever fabricated. Missing fields are shown as *Not specified*; unknown company size is shown as *Size not verified*.

---

## Architecture

```
frontend/  Next.js 15 · TypeScript · Tailwind · shadcn-style UI (Radix) · React Query
   └── /api/*  ──proxy──▶  backend/  FastAPI · SQLAlchemy 2 (async) · Pydantic · Alembic
                             ├── services/
                             │   resume_parser       ResumeParserService (magic-byte validation, PDF/DOCX text)
                             │   resume_analysis     ResumeAnalysisService (rules + optional LLM, every claim verified)
                             │   keyword_generator   JobKeywordGenerator
                             │   company_discovery   CompanyDiscoveryService (+ company DB, size classification)
                             │   normalization       JobNormalizationService / JobExtractionService
                             │   dedup               JobDeduplicationService
                             │   matching            JobMatchingService (deterministic score + LLM narrative)
                             │   orchestrator        SearchOrchestrator  ← the RUN button pipeline
                             │   search_service      SearchHistoryService, concurrency guard
                             │   http                PoliteHttp (robots.txt, per-host rate limits, retries)
                             ├── connectors/         one independent connector per source (common interface)
                             │   base.py             JobSourceConnector / CompanyCareerConnector
                             │   job_boards.py       Remotive, Arbeitnow, RemoteOK, Himalayas, Jobicy, HN Who-is-hiring,
                             │                       Adzuna, Jooble, JSearch, SerpAPI Google Jobs, Apify actors
                             │   ats.py              Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio
                             │   career_page.py      GenericCareerPageConnector (schema.org JobPosting, ATS hand-off, optional Playwright)
                             │   registry.py         connector registry + portal coverage catalogue
                             └── worker/             in-process thread runner or Celery (+ beat schedule)
PostgreSQL (SQLite for zero-setup local dev) · Redis (Celery broker)
```

**Database tables:** `users, resumes, candidate_profiles, candidate_skills, companies, company_career_pages, job_sources, jobs, job_skills, job_matches, saved_jobs, search_sessions, search_logs`, plus `job_source_links` (one job → many sources). The schema is in `backend/app/models.py`; the migration is `backend/alembic/versions/`.

### The RUN pipeline
`POST /api/search/run` creates a `search_session`, guarded so a user can't run two searches at once. It then dispatches `SearchOrchestrator`, which runs these steps:

1. Load the profile.
2. Generate keywords.
3. Query all enabled sources concurrently. Each source is isolated with a timeout, so **a failed source never stops the run**.
4. Register every company seen and bootstrap the company DB.
5. Detect official boards and career pages.
6. Crawl company boards, small/medium/unknown-size companies first.
7. Normalise postings.
8. De-duplicate and upsert, using source id → fingerprint (title|company|location) → canonical apply URL → same company with a similar title and description (shingle Jaccard).
9. Mark postings that vanished from a complete official listing as **unavailable**.
10. Score matches and mark first-seen jobs **NEW**.
11. Save the stats.

Progress, the current step and a live log are polled by the UI. **Stop** sets a flag; the pipeline stops collecting, but still saves and matches what it already has.

### Match score (deterministic, weights configurable in *Find Jobs → advanced*)
| Component | Default weight | How |
|---|---|---|
| Technical skills | 35 | Taxonomy skills in the JD vs. the profile, weighted (title skills ×1.5). Jobs listing very few skills are pulled toward neutral. |
| Relevant experience | 25 | JD requirement (e.g. "3-5 years", "5+ yrs", seniority in the title) vs. professional months + 50% of internship months. Big gaps cap the total at 45. |
| Role compatibility | 20 | Fuzzy title similarity + role families (backend/AI/data/…). Support and manager titles are penalised unless targeted. |
| Education | 10 | Only when the JD explicitly asks for a degree. |
| Location & work mode | 10 | Remote/hybrid/onsite preference, preferred locations, region-restricted remote roles. |

Each job shows matched/missing skills, experience fit, "why it matches" and eligibility gaps. An optional **AI assessment** (LLM) can be generated per job.

### Safety & compliance
- Only official APIs, public job feeds, licensed providers and **robots.txt-permitted** pages are used. 401/403 and robots disallows are reported as "not permitted"; there is no CAPTCHA, login or anti-bot bypassing.
- Every host is rate-limited (crawl-delay honoured), with retries and backoff, timeouts and response-size caps.
- Resume and scraped text are **untrusted**:
  - They are wrapped in random-delimited data blocks, and the system prompt forbids following embedded instructions.
  - Output is JSON-validated by Pydantic.
  - Every LLM-extracted skill or company is **re-verified against the resume text**. Companies must appear near their claimed start year, so injected text can't fabricate jobs.
- Auth uses JWT and bcrypt. There's API rate limiting, input validation, upload magic-byte checks (no macros, zip-bomb guard), random storage names outside the web root, optional Fernet encryption at rest, and secrets only in env vars.

---

## Job application emails (Gmail)

Open **Applications** in the sidebar. From there you can connect one or more Gmail accounts, manage templates, review and send drafted emails, and see the full send history.

**How it works**
- At the end of every RUN, step 10 scans the matching jobs' postings for a recruiter address. It creates a **Ready to send** draft for each one it finds, using your default template and Gmail account. Addresses are only ever taken from the posting text, including `mailto:` links and "name [at] domain [dot] com". Nothing is guessed, and placeholder or no-reply addresses are ignored.
- From any job's detail panel, **Email HR** opens a draft. If the posting has no address, the draft stays **Pending** until you type the recipient.
- **Manual mode (default):** review or edit the recipient, sender, template, subject and message, preview the attached PDF, then click **Send**.
- **Automatic mode (opt-in):** after each RUN, and right after you switch it on, approved drafts are sent one at a time, highest match first. Every rule below must hold:
  - match ≥ the configured minimum score;
  - the recipient came from the posting or from you, and its domain passes a DNS check;
  - the posting is still active;
  - you're under your daily limit (max `EMAIL_DAILY_LIMIT_MAX`);
  - the recruiter hasn't been emailed in the last 7 days.

  Sends are spaced `EMAIL_SEND_INTERVAL_SECONDS` apart. Switching auto-send off pauses the queue before the next message.
- **Duplicate protection:** a database unique constraint on (user, job, recipient), plus an atomic `ready/failed → sending` status transition, means a double click, a retry and the auto-queue can never send the same email twice.
- **History:** every email records the sender, template, Gmail message ID, timestamp and any error. Failed emails can be retried.

**API**
- `POST /api/gmail/connect`, `GET /api/gmail/callback`, `GET /api/gmail/accounts`, `DELETE /api/gmail/disconnect/{id}`
- `GET|POST /api/email-templates`, `PUT|DELETE /api/email-templates/{id}`, `POST /api/email-templates/{id}/default`, `POST /api/email-templates/preview`, `GET /api/email-templates/variables`
- `GET /api/job-emails` (history and filters), `GET /api/job-emails/stats`, `GET|PUT /api/job-emails/settings`, `POST /api/job-emails/preview`, `POST /api/job-emails/drafts`
- `GET|PUT|DELETE /api/job-emails/{id}`, `POST /api/job-emails/{id}/send`, `POST /api/job-emails/{id}/retry`, `POST /api/job-emails/{id}/skip`, `GET /api/job-emails/{id}/attachment`, `POST /api/job-emails/auto-send`

Template variables: `{{hr_name}} {{company_name}} {{job_title}} {{candidate_name}} {{candidate_email}} {{candidate_phone}} {{experience}} {{skills}} {{resume_link}} {{job_link}}`

### Gmail setup (Google Cloud Console, one time)
1. Go to <https://console.cloud.google.com/> and create (or pick) a project.
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **APIs & Services → OAuth consent screen** (Google Auth Platform → Branding / Audience / Data access):
   - User type **External**. Fill in the app name and your support email.
   - Under **Data access**, add these scopes:
     - `openid`
     - `.../auth/userinfo.email`
     - `.../auth/gmail.send`
   - Under **Audience**, leave the app in **Testing** and add every Gmail address you'll connect as a **Test user**.

   `gmail.send` is a *sensitive* scope. In Testing mode it works for listed test users without Google verification, but refresh tokens expire after 7 days, so you'll need to reconnect weekly. Submitting the app for verification removes that limit.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type **Web application**.
   - Authorized redirect URI: `http://localhost:3000/api/gmail/callback`. Use your real domain in production; it must match `GOOGLE_OAUTH_REDIRECT_URI` exactly.
5. Put the client ID and secret in `.env`:
   ```
   GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-xxxx
   TOKEN_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
   ```
6. Restart the backend, open **Applications → Settings → Connect Gmail**, and approve the consent screen. Make sure the "Send email on your behalf" box is ticked.

**Security notes**
- Only `gmail.send` is requested, so the app cannot read your mailbox.
- Access and refresh tokens are Fernet-encrypted in the database and never sent to the browser.
- OAuth uses a one-time signed `state` plus PKCE.
- Tokens refresh automatically. An account whose access was revoked is marked "Reconnect needed".
- Disconnecting revokes the grant at Google and deletes the tokens.
- Logs never contain tokens or message content.

## Running locally (no Docker, zero external services)

Requirements: Python 3.11+, Node 20+.

```bash
cp .env.example .env              # optional – defaults work out of the box (SQLite, no LLM)

# backend
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows   (source .venv/bin/activate on macOS/Linux)
pip install -r requirements-dev.txt
alembic upgrade head              # or let dev mode auto-create the SQLite schema
uvicorn app.main:app --port 8000  # API docs: http://localhost:8000/docs

# frontend (new terminal)
cd frontend
npm install
npm run dev                       # http://localhost:3000  (proxies /api to BACKEND_URL, default http://localhost:8000)
```

Create an account, upload a resume, review **Resume Analysis**, then press **RUN** on *Find Jobs*. A full run checks around 120 companies plus all enabled sources and typically takes several minutes; progress is live.

## Running with Docker (PostgreSQL + Redis + Celery)

```bash
cp .env.example .env   # set SECRET_KEY, optional API keys
docker compose up --build                       # frontend :3000, API :8000
docker compose --profile scheduled up -d beat   # optional periodic RUNs (SCHEDULED_SEARCH_CRON_HOURS)
```
The backend container runs `alembic upgrade head` on start. For cloud deployment (e.g. AWS ECS/RDS/ElastiCache), use the same images with a managed Postgres and Redis.

## Tests

```bash
cd backend && pytest -q          # 32 tests
cd frontend && npm run typecheck && npm run build
```
Unit tests cover:
- parsing, experience math (internships vs. full-time, overlapping roles) and salary/experience extraction;
- skill extraction false positives;
- LLM hallucination and prompt-injection rejection;
- scoring;
- JSON-LD extraction.

Integration tests use mocked HTTP shaped like the real APIs and drive the full flow: upload → profile edit → RUN → dedup across sources → filters → save/hide → second RUN (NEW flags, unavailable postings, no duplicates) → failing sources → concurrent-run guard → Stop.

---

## Integration status (verified live on 2026-11-07)

| Source | Type | Status |
|---|---|---|
| Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee | Official company ATS APIs | ✅ **Working**, no key needed. Live run: 123 company boards checked |
| Personio | Official ATS XML feed | ✅ Implemented (tested companies had no public feed) |
| Company career pages | schema.org `JobPosting` + ATS detection | ✅ Working (robots.txt respected). Playwright for JS-only pages is optional (`PLAYWRIGHT_ENABLED`) |
| Remotive, Arbeitnow, RemoteOK, Himalayas, Jobicy | Public job-board APIs | ✅ **Working**, no key |
| Hacker News "Who is hiring" | Public Algolia API | ✅ **Working**; a major source of small companies |
| Adzuna | Free developer API | 🔑 Needs `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` (implemented, not live-tested) |
| Jooble | Free partner API | 🔑 Needs `JOOBLE_API_KEY` (implemented, not live-tested) |
| JSearch (RapidAPI) | Licensed Google-for-Jobs data | 🔑💲 Needs `RAPIDAPI_KEY`; covers LinkedIn / Indeed / Glassdoor / Naukri listings |
| SerpAPI Google Jobs | Licensed | 🔑💲 Needs `SERPAPI_KEY` (also enables search-engine company discovery) |
| Brave Search | Company discovery | 🔑 Needs `BRAVE_SEARCH_API_KEY` |
| Apify actors (LinkedIn / Naukri / Indeed) | Third-party data provider | 🔑💲 Needs `APIFY_TOKEN` + actor id. Check the actor's terms first |
| LinkedIn, Naukri, Indeed, Glassdoor, Foundit, Instahyre, Wellfound, Cutshort, Hirist, iimjobs, TimesJobs, Shine | Portals | ⛔ No public job-search API, and the terms prohibit scraping, so they are **never scraped directly**. They are covered through the licensed providers above (shown on the Settings page) |
| Gmail API (application emails) | Google OAuth 2.0, `gmail.send` | 🔑 Needs `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (implemented and tested against mocked Google endpoints; not yet live-tested) |
| LLM (Anthropic / OpenAI) | Optional | 🔑 `LLM_PROVIDER` + key. Without it, rule-based extraction is used and scoring is unchanged |

Keyed connectors are written against each provider's documented API, but could not be exercised without credentials.

## Known limitations
- Company size is often *Size not verified*. Sizes come only from explicit statements in postings ("team of 25 people") or from values you enter on the Companies page. Nothing is guessed.
- Free public boards skew toward remote/global roles. For India-focused coverage, add the Adzuna (`ADZUNA_COUNTRY=in`), Jooble or JSearch keys.
- The in-memory API rate limiter is per process. Use a Redis-backed limiter behind multiple replicas.
- The JWT is kept in `localStorage` for simplicity. Switch to httpOnly cookies for a hardened multi-user deployment.
