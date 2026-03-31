#!/usr/bin/env python3
import json, subprocess, os

os.chdir("/home/ubuntu/jpme")

# Check if draft exists
try:
    with open("sermon-draft.json") as f:
        draft = json.load(f)
except:
    print("No draft waiting for approval.")
    exit(0)

# Copy draft to live
with open("sermon.json", "w") as f:
    json.dump(draft, f, indent=2)

# Push to GitHub
subprocess.run(["git", "add", "sermon.json"], check=True)
result = subprocess.run(["git", "commit", "-m", f"Publish sermon: {draft['title']}"], capture_output=True, text=True)
if result.returncode == 0:
    subprocess.run(["git", "push"], check=True)
    print(f"PUBLISHED - {draft['title']} is now live on myjesus.co.za")
else:
    print("Already live - no changes needed")

# Remove draft
os.remove("sermon-draft.json")
