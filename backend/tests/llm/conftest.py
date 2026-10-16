import os

# Must be set before litellm is imported: avoids fetching the model-cost map over the network.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
