import json
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "data" / "pods.json"


def get_all_pods():
    with open(DATA_FILE, "r") as f:
        return json.load(f)
