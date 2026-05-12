#!/usr/bin/env python3
import json, subprocess, os, sys

os.chdir("/home/ubuntu/jpme")

# Check if draft exists
try:
    with open("sermon-draft.json") as f:
        draft = json.load(f)
except FileNotFoundError:
    print("No draft waiting for approval.")
    exit(0)

# Ensure git config is set
subprocess.run(["git", "config", "user.email", "cronje.antwan@gmail.com"], capture_output=True)
subprocess.run(["git", "config", "user.name", "JARVIS"], capture_output=True)

# Pull remote FIRST — before touching sermon.json — so there's nothing to conflict with.
# Use --autostash in case something unrelated is dirty.
pull = subprocess.run(
    ["git", "pull", "--rebase", "--autostash"],
    capture_output=True, text=True
)
if pull.returncode != 0:
    print(f"PULL FAILED — refusing to publish: {pull.stderr}")
    exit(1)

# Now write the clean draft to sermon.json — no merge can touch it.
with open("sermon.json", "w") as f:
    json.dump(draft, f, indent=2)

# Validate: re-read and parse. Refuse to push anything that won't parse in the browser.
try:
    with open("sermon.json") as f:
        raw = f.read()
    parsed = json.loads(raw)
    if "<<<<<<<" in raw or "=======" in raw or ">>>>>>>" in raw:
        raise ValueError("Merge conflict markers detected in sermon.json")
    for required in ("title", "speaker", "date", "videoId", "summary", "quotes"):
        if required not in parsed:
            raise ValueError(f"Missing required field: {required}")
    if not isinstance(parsed["quotes"], list) or len(parsed["quotes"]) == 0:
        raise ValueError("quotes must be a non-empty list")
except (ValueError, json.JSONDecodeError) as e:
    print(f"VALIDATION FAILED — refusing to publish: {e}")
    print("Draft kept for retry.")
    exit(1)

# Validation passed. Commit and push.
subprocess.run(["git", "add", "sermon.json"], check=True)
result = subprocess.run(
    ["git", "commit", "-m", f"Publish sermon: {draft['title']}"],
    capture_output=True, text=True
)
if result.returncode == 0:
    push = subprocess.run(["git", "push"], capture_output=True, text=True)
    if push.returncode == 0:
        print(f"PUBLISHED - {draft['title']} is now live on myjesus.co.za")
    else:
        print(f"COMMIT OK but PUSH FAILED: {push.stderr}")
        print("Draft kept for retry.")
        exit(1)
else:
    print(f"COMMIT FAILED: {result.stderr}")
    print("Draft kept for retry.")
    exit(1)

# Only remove draft after successful push
os.remove("sermon-draft.json")
