# Later — design

Hacktoberfest Open-Source AI Challenge Week 3 ("Slow and Steady") entry.
Publish on DEV with tag `#hf26challenge` by **Saturday Oct 24, 23:00 Irish time**
(safe side of the API end time, Oct 25 06:59 UTC).

## One line

Snap it, say it, or paste it — Later works out what you'll need to do and the
last sensible moment to do it, then stays silent until then.

## Who it's for

Everyday people. Things people lose track of: return windows on receipts,
warranty end dates, "come back in 6 months", ticket on-sale times, bill due
dates, form deadlines.

## How it works

1. **Capture** (web page, phone-friendly): a photo, typed/pasted text, or a voice note.
2. **Understand**: Gemma (open weights) reads it and returns *facts* only —
   kind, title, action, dates and windows it saw, the shop/org, a quote of the
   evidence. **The model never does date arithmetic.**
3. **Resolve**: plain code turns facts into `due_at` (last day) and `remind_at`.
4. **Fill gaps**: a receipt with a shop but no return window → SerpApi search
   for that shop's Irish return policy → Gemma reads the snippets → window days.
5. **Wait**: one Temporal workflow per item sleeps until `remind_at`. Survives
   restarts. Accepts `done`, `snooze(days)`, `cancel`.
6. **Nudge**: one push notification via ntfy (open-source push) with
   Done / Snooze 3 days buttons. That's the only time the user hears from it.

## Reminder rules (exact)

Timezone: `Europe/Dublin`. Default reminder time of day: 09:00 local.

| kind | lead before `due_at` |
|---|---|
| `return_window` | 3 days |
| `warranty` | 30 days |
| `bill` | 3 days |
| `appointment` (book a follow-up) | 14 days |
| `deadline` | 2 days |
| `event_tickets` | 30 minutes, at exact time (not 09:00) |
| `other` | 1 day |

- `due_at` = `explicit_due` if present, else `anchor_date` (or capture date if
  none) + `window_days` / `window_months` (month math clamps to month end).
- Date-only due → due at 23:59 local that day.
- If `remind_at` is already past at capture → remind immediately, flag `late`.
- If nothing resolves → status `needs_info` (shown on the page, no workflow).

## Partners (one job each)

| Partner | Job |
|---|---|
| Gemma | extraction (text + vision), policy reading |
| Google AI Studio | hosts Gemma 4 31B (OpenAI-compatible endpoint) — the only place the model runs; read in the background because the free tier is slow and fails ~1 call in 3 |
| Temporal | durable sleep per item, retries, signals |
| SerpApi | return-policy lookup |
| ElevenLabs | voice note → text (speech-to-text) |
| MongoDB Atlas | item store |
| Sentry Agent Tracing | trace every model call: latency, tokens, cost |
| Render | hosts web + worker + Temporal dev server, public URL on onrender.com |
| Entire / DevRelay | build session embedded in the post |
| Auth0 for AI Agents | **stretch**: approve before adding to Google Calendar |

## Post must show

- Real lazy payoff: items captured this week, reminders that fired on time.
- Eval numbers: 30 hand-labelled captures; kind accuracy, due date exact /
  within 1 day, latency, cost — Gemma 4 31B vs Gemma 4 26B-A4B on Google AI Studio.
- No AI runs on the builder's PC: the model is hosted only. Code points at any
  OpenAI-compatible endpoint via `LLM_BASE_URL`.
- Why open: open weights mean anyone can self-host the exact same model
  (privacy), no lock-in to one vendor's API or pricing, and swapping
  provider or model is one env var.
- What went wrong section. Screenshots: Temporal timeline, Sentry trace,
  Render logs, Google AI Studio usage.
