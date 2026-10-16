"""Session-wide test environment, applied before any `app` import in every suite."""

import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # litellm must not fetch its cost map
os.environ.setdefault("FINALLY_SKIP_DOTENV", "1")  # never load the developer's .env
