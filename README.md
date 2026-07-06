# SpecBot AI Technical Designer — Demo

A Streamlit demo that turns a sketch + a few fields of metadata into a
draft tech pack, applies fitting notes, exports an Excel workbook, and
emails it to a factory contact (test-mode only).

This is a **customer demo, not a production system**. See "Known limitations"
below.

## Demo flow

> **No API key? No problem.** Click **Load Demo Tech Pack** in Style Setup to
> populate every tab with an offline draft built from the category-standard
> spec block. Generating without an `OPENAI_API_KEY` also falls back to the
> same offline draft (with a clear warning that the sketch was not analyzed).

1. **Style setup** — upload a sketch (PDF/JPG/PNG) and enter style metadata.
2. **Tech pack preview** — review the AI-drafted garment summary,
   editable measurement table, construction notes, BOM, and any flagged
   assumptions / missing information.
3. **Export Excel** — produces a multi-sheet workbook (`Cover`,
   `Measurements`, `BOM`, `Construction`, `Change Log`, `Assumptions and
   Missing`).
4. **Fitting notes** — paste freeform fit-session notes (e.g.
   _"Raise armhole by 0.5"_). The app applies them to the measurement
   table and writes change-log entries.
5. **Send to factory** — pick a factory + contact, edit the email
   subject/body, and send a test email. **Outbound mail is always
   redirected to `TEST_EMAIL_RECIPIENT`**; the intended recipient is
   recorded in the email body.
6. **WIP dashboard** — the local dashboard updates to "Sent to Factory".

## Setup

```bash
cd specbot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# then fill in OPENAI_API_KEY and email vars (see below)
```

### Environment variables

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for sketch analysis and GPT-based fitting-note interpretation. |
| `TEST_EMAIL_RECIPIENT` | Required to send. **Every email is redirected here** for safety. |
| `EMAIL_FROM` | Sender address shown on the outgoing email. |
| `RESEND_API_KEY` | Use Resend as the transport (preferred if set). |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP transport, used if Resend isn't configured. |

If neither Resend nor SMTP is configured, the app will still let you
generate, export, and apply fitting notes — only the send step is
disabled.

## Run locally

```bash
streamlit run app.py
```

The app reads `factory_contacts.json` for the factory dropdown and
persists the WIP dashboard to `wip_records.json`. Both files live next
to `app.py` and are pure-JSON for easy editing during a demo.

## Deploy to Railway

SpecBot is a standalone repo; Railway builds it from the repo root using
the included `Dockerfile` and `railway.json`.

One-time setup in your own Railway project:

1. **New → Deploy from GitHub repo** → pick `bbgraz/specbot`.
2. **Settings → Source → Branch** → set to `main`. Leave **Root
   Directory** unset (the Dockerfile is at the repo root).
3. **Variables** → add:
   - `OPENAI_API_KEY` (your own key)
   - `TEST_EMAIL_RECIPIENT`
   - `EMAIL_FROM`
   - Either `RESEND_API_KEY`, or `SMTP_HOST` / `SMTP_PORT` /
     `SMTP_USERNAME` / `SMTP_PASSWORD`
4. **Settings → Networking → Generate Domain** → Railway gives you the
   public URL (`<service>.up.railway.app`). Streamlit binds to `$PORT`
   automatically.

Health check is `/_stcore/health` (Streamlit's built-in endpoint).

### What's in the repo for Railway

- `Dockerfile` — Python 3.13 slim, installs `requirements.txt`, runs Streamlit on `$PORT`.
- `railway.json` — tells Railway to use the Dockerfile and sets the start command + healthcheck.
- `.streamlit/config.toml` — headless mode, CORS/XSRF off (Railway sits in front of the app as a proxy).

### Notes / limits

- **State is in-process.** A redeploy or autoscale will reset session
  state and clear `wip_records.json` (since it's baked into the image).
  Fine for a demo; not for shared-state production use.
- **Single replica.** Don't scale > 1 — sessions are sticky to a process.
- **WIP persistence is ephemeral on Railway.** If you need it to survive
  redeploys, attach a Railway Volume and mount it at
  `/app/wip_records.json` (or set `SPECBOT_WIP_PATH` to a volume path).

## Project layout

```
specbot/
  app.py                 Streamlit UI (single page)
  gpt_service.py         OpenAI GPT-4o calls (sketch + fitting notes)
  spec_blocks.py         Category-standard POM spec blocks + AI grounding + offline drafts
  brand_library.py       Mock brand library (fabrics, trims, standards) grounding for GPT
  tech_pack_store.py     JSON-backed per-style persistence (saved styles picker)
  excel_exporter.py      Multi-sheet Excel export (xlsxwriter)
  fit_update_service.py  Apply fitting notes -> updated tech pack + change log
  email_sender.py        Resend or SMTP transport, test-mode redirect
  wip_store.py           JSON-backed WIP dashboard
  factory_contacts.json  5 demo factories with 2 contacts each
  wip_records.json       Created on first send
  tests/test_specbot.py  Offline functional test suite (python tests/test_specbot.py)
  requirements.txt
  .env.example
  Dockerfile             Railway / docker build
  railway.json           Railway service config (separate from root API service)
  .streamlit/config.toml Streamlit headless / proxy settings
```

## Known limitations

- **Not production-ready.** No auth, no validation, no audit trail beyond the
  in-memory change log.
- **RAG is mocked / not implemented.** The model relies on its own training data
  plus the metadata you provide; there is no retrieval over a real spec library.
- **Factory CRM is local JSON.** No CRUD UI, no sync with anything else.
- **WIP is local JSON.** Cleared by deleting `wip_records.json`.
- **Email is test-mode only.** Every send is redirected to
  `TEST_EMAIL_RECIPIENT` — real factories are never contacted.
- **Measurements are grounded, not vision-guessed.** Every garment category has
  a standard POM spec block (`spec_blocks.py`); the AI can only adjust those
  baselines, and adjustments outside a ±35% plausibility window are rejected
  back to the standard value and flagged for review. Standard targets are
  generic industry baselines — replace them with your brand's blocks.
- **Generated measurements are draft suggestions.** Every value is labeled
  `derived_from_input`, `inferred_from_standard_practice`, or
  `placeholder_for_review`. **A technical designer must review** before any
  document is used in real production.
- **Human review is required** before sending real factory documents — the
  test-mode redirect exists precisely to enforce this.
