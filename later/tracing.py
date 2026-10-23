import os

import sentry_sdk
from sentry_sdk.integrations.openai import OpenAIIntegration


def init_tracing() -> bool:
    """Trace every model call (latency, tokens) in Sentry. Prompts and images are never sent."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=1.0,
        send_default_pii=False,
        integrations=[OpenAIIntegration(include_prompts=False)],
    )
    return True
