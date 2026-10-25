*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 3: Slow and Steady](https://dev.to/challenges/hacktoberfest-week3-2026-10-19)*

Return windows, warranty end dates, "come back in six months", the morning tickets go on sale, the bill that's due on the 5th. None of these are hard. They're just things I'm supposed to *remember*, and I don't.

So I built **Later**: you throw something at it, it works out the last sensible day to act, and then it does the most sloth thing possible. It waits. Quietly. For weeks or months. Then it nudges you once.

![Later on a phone: a timeline of held items grouped into Needs a look, Reading, Today, This week, This month and Later on, with a big Throw something in button at the bottom](https://raw.githubusercontent.com/SRG-Cy/later/main/docs/post/app-light.png)

## What I Built

Later is a phone-friendly web app with one big button, **Throw something in**. It opens a sheet with three ways in: **Snap** (a photo of a receipt, letter or poster), **Say** (a voice note, transcribed by ElevenLabs) and **Type**.

- You capture something and it answers instantly: *"Got it. I'm reading it now, so you can close this page."*
- In the background, an open-weight model (**Gemma 4 31B**) reads it and reports the facts: what kind of thing it is, the dates it saw, any window like "refunds within 28 days".
- Plain code turns those facts into a deadline and a nudge time in Irish time: 3 days before a return window closes, 30 days before a warranty ends, 2 weeks before you should book that check-up.
- A **Temporal** workflow sleeps until then. It survives restarts and deploys.
- You get **one** push on your phone, with **Done** and **Snooze 3 days** buttons. That's the only time Later ever talks to you.

Everything Later is holding sits on one timeline, grouped by when you'll hear about it: *Today*, *This week*, *This month*, *Later on*. Anything that needs you (no date found) floats to the top. Tap an item to see the due date and Done / Snooze / Forget.

The lazy part is the whole point: you don't type a calendar entry, you don't work out what "28 days from the 20th" is, and you don't check an app to see what's coming. You throw it in and forget it.

## Demo

**Try it:** https://later-h5nw.onrender.com (no sign-up). Tap **Throw something in**, then **Type**, paste something like *"Penneys receipt 20/10/2026. Refunds within 28 days"*, and watch it move from *Reading* to *This month*. Tap the 🔔 to subscribe to your private push topic in the free [ntfy](https://ntfy.sh) app.

<!-- DEMO VIDEO: add a 60-90 s screen recording here (capture -> Reading -> moves into the timeline -> push on phone -> tap Done). -->

## Code

{% embed https://github.com/SRG-Cy/later %}

MIT licensed, with 113 tests. Temporal workflows are tested with Temporal's time-skipping test server, so "wait 30 days" runs in a second.

## How I Built It

```plaintext
phone ──capture──▶ FastAPI ──store──▶ MongoDB Atlas
                      │
                      └─start──▶ Temporal workflow (one per item)
                                   1. read_item       Gemma 4 31B reads the text or photo
                                   2. resolve         plain code computes the deadline
                                   3. sleep until the last sensible moment
                                   4. send_reminder   one ntfy push, signed Done / Snooze links
```

### The model reports facts. Code does the maths.

LLMs are not reliable at date arithmetic ([there's data on this](https://dev.to/maverickyadav/-llms-cant-reliably-do-date-math-and-now-theres-data-4hm2)), and a reminder app that's a day out is worse than none. So Gemma is told to **copy** dates exactly as written and report lengths of time separately:

```json
{"kind": "return_window", "org": "Penneys", "anchor_date": "2026-10-20",
 "window_days": 28, "evidence": "Refunds within 28 days with receipt"}
```

Then `resolve()` does the rest in plain Python: month ends (31 Aug + 6 months = 28 Feb), Irish dates (day/month), and the clock change. Ireland's clocks went back on Sunday 25 October, the last day of this challenge, and 09:00 nudges stay at 09:00 local.

### Reading slowly on purpose

I first ran Gemma 4 on Google AI Studio's free tier as a normal request: you capture, you wait for the answer. It was **right every time it answered**, but it failed a lot and was slow. In a 24-call comparison, Gemma 4 31B succeeded 4 times out of 6, with each answer taking ~30 seconds. OpenRouter's free Gemma was rate-limited on all 12 calls.

Nobody should stare at a spinner for a minute, so reading moved into the background:

- `/capture` stores the raw item as **reading** and starts its workflow. It returns in milliseconds.
- The workflow's first step is a `read_item` activity with a patient retry policy: 5 s, then doubling up to every 2 minutes, for up to 2 hours.
- A model error raises, so Temporal retries it. A reply that's understood but has no date becomes **no date found**, with no endless retries.
- If the model is down for 2 hours, the item is marked **failed** instead of quietly vanishing.

That's this week's theme taken literally: the sloth takes its time so you don't have to.

### No accounts, still private

The public demo has no sign-up, so each visitor gets an anonymous cookie and only sees their own items. Each visitor gets a private ntfy topic derived with an HMAC. The push buttons carry a signed per-item token, because the ntfy app has no cookie, and a forged token gets a 404. Daily capture limits protect the free model quota.

### Deploying

One Docker container on Render runs the Temporal dev server (state on a 1 GB persistent disk), a self-restarting worker and the web app. MongoDB Atlas holds the items and photos.

## Results

I ran 35 captures through the real pipeline (Gemma extraction, then the resolver), with Temporal-style retries:

| | 30 hand-written captures | 5 real Galway event listings |
|---|---|---|
| | 27 typed, 3 drawn images | 3 typed, 2 screenshots of the live listing pages |
| Due date exactly right | **30/30** | **5/5** |
| Kind of item right | 28/30 | 5/5 |
| Model calls that failed | **16 of 46 (35%)** | 1 of 6 |
| Captures lost | **0** | **0** |
| Time to read, median | 60 s | 55 s |

The hand-written set includes an Irish mix: Penneys and Zalando returns, an ESB bill, motor tax, the NCT, a Revenue Form 11 deadline, a Panda bin top-up, a passport expiry. One gig poster has a decoy date: the gig is in March 2027, but tickets go on sale 13 Nov 2026, and that's the date that matters. The Galway set uses real listings: Paul Brady at Leisureland, The Frank And Walters and Pa Sheehy at Róisín Dubh, and the Eyre Square Christmas Market.

![A real Songkick listing screenshot used as a test capture: Paul Brady, Saturday 28 November 2026, Leisureland, Galway](https://raw.githubusercontent.com/SRG-Cy/later/main/eval/images/galway-paul-brady.png)

**The number I care about is the third row.** Google's free Gemma endpoint failed **35%** of calls. The worst capture, an ESB bill, failed 4 times and was read on the 5th try, 8½ minutes later. Without the retries, a third of everything you threw at Later would simply be gone. With them, nothing was lost. (The standard advice on [retrying LLM calls with backoff](https://dev.to/draganristicrsjpg/retry-backoff-and-circuit-breakers-for-llm-api-calls-h3k) applies; Temporal just makes it durable.)

### What went wrong

- **Gigs were nudged after the gig.** The real Galway listings caught this one. Gemma labels gigs as "ticket" events, which nudge 30 minutes before a known time. With only a date, that came out as **23:29 on the night**. Now a date-only event nudges at 09:00 that morning.
- **Gemma 4 thinks out loud.** On Google AI Studio it always writes a `<thought>` block before its answer, sometimes wraps the JSON in code fences, and JSON mode returned 500 errors. The parser now skips the thinking and takes the last complete JSON object.
- **Date-only dates became midnight.** Pydantic happily parses `"2026-11-05"` into a *datetime* at 00:00, which would have fired reminders a day early. Dates without a time now stay dates.
- **Two kind mix-ups** in the test, both with the right date: a Hozier ticket sale labelled a *deadline* (nudges 2 days early instead of 30 minutes before), and a flight labelled a *ticket event*.

## Why Does Open Innovation Matter?

- **The weights are open, so the exact same model can run anywhere.** I used Google AI Studio's hosted Gemma for the demo, but Gemma is open-weight: anyone who doesn't want their receipts and letters leaving their machine can point `LLM_BASE_URL` at their own server and run the identical model. The code only needs an OpenAI-compatible endpoint.
- **No lock-in.** Switching provider or model is one environment variable. I did exactly that mid-build: I benchmarked two providers and two Gemma sizes, then moved, without touching the code.
- **The free tier made it possible, and open tools made it reliable.** A free, flaky endpoint was fine because open-source Temporal absorbs the flakiness. The whole stack is open source or has a free tier: Gemma, Temporal, ntfy, FastAPI.

## The Lazy Payoff

Here's what one capture saves you:

| By hand | With Later |
|---|---|
| Work out "28 days from the 20th" | Snap the receipt |
| Open the calendar, make an event, pick a reminder time | |
| Remember to check it | |
| Notice when you've missed it | One push, the morning it matters |

Capturing takes one tap and a photo, a few seconds. After that the effort is zero. Across the 35 test captures, Later worked out every deadline correctly, and the person capturing never had to look at a date.

## Prize Categories

- **Best Use of Gemma:** Gemma 4 31B reads every capture, text and photos, and returns structured facts. It's evaluated on 35 captures, with 35/35 due dates correct.
- **Best Use of Temporal:** one durable workflow per item. It reads in the background with patient retries (recovering from a 35% failure rate with 0 lost captures), sleeps for days or months until the nudge, and handles Done/Snooze signals. Tested with the time-skipping test server.
- **Best Use of ElevenLabs:** the **Say** button. ElevenLabs speech-to-text (`scribe_v2`) turns a voice note into text in about 2 seconds, and Gemma reads the transcript like anything typed. Live test: *"Dentist said come back for a checkup in six months"* was transcribed word for word and scheduled for 25 April 2027. If transcription fails, the person gets a clear message instead of a lost capture.
- **Best Use of MongoDB Atlas:** stores every item and photo, with per-visitor queries and daily limit counts.
- **Best Use of Render:** one Docker web service from a `render.yaml` Blueprint runs Temporal, the worker and the app, with a persistent disk for Temporal's state. Push links fall back to Render's own `RENDER_EXTERNAL_URL`, so they work without extra setup.

---

*This project and post were built with the help of AI (Claude Code). I reviewed and tested everything here, and every number comes from runs in the repo's `eval/results`.*
