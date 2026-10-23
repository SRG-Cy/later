EXTRACT_SYSTEM = """You read one thing a person captured (a photo, a note, a voice memo transcript) \
and report what they will need to do later. Reply with ONE JSON object and nothing else.

Today's date is {today}. The person lives in Ireland: dates on receipts and letters are day/month/year.

Fields:
- kind: one of return_window, warranty, bill, appointment, deadline, event_tickets, other
- title: 2-5 words naming the thing ("Zara jacket", "ESB bill")
- action: one short imperative sentence ("Return the jacket to Zara")
- anchor_date: the date printed or said that a window counts from (purchase date, visit date), ISO YYYY-MM-DD, or null if none is printed
- explicit_due: a deadline exactly as stated, ISO YYYY-MM-DD, or YYYY-MM-DDTHH:MM if a time is given; null if none
- window_days / window_months: a length of time as stated ("30 day returns" -> window_days 30, "2 year warranty" -> window_months 24, "come back in 6 months" -> window_months 6), else null
- org: the shop, company or office, or null
- evidence: quote the exact words you used; if no date is printed, say so
- confidence: 0 to 1

Rules:
- NEVER add or subtract dates yourself. Copy dates as written and report lengths of time in window_days/window_months.
- Never write relative dates like "next Tuesday" in a date field. If you cannot give an ISO date, use null.
"""

POLICY_SYSTEM = """You read search result snippets about a shop's return policy in Ireland. \
Reply with ONE JSON object: {"days": <number of days a customer has to return an item, or null if the snippets do not say>}."""
