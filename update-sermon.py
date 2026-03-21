#!/usr/bin/env python3
import json, urllib.request, subprocess, os, re

os.chdir("/root/jpme")

# Load env
env = {}
with open("/root/.openclaw/.env") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v

# Step 1: Get latest video from RSS
print("Fetching latest video from RSS...")
rss_url = "https://www.youtube.com/feeds/videos.xml?channel_id=UCXPW-Zk-NPr4eRCOeQlDs0A"
with urllib.request.urlopen(rss_url) as r:
    rss = r.read().decode()

video_id = re.search(r'<yt:videoId>([^<]+)', rss).group(1)
full_title = re.search(r'<media:title>([^<]+)', rss).group(1)
# Skip first <published> (channel date), get the one inside first <entry>
entry_block = rss.split('<entry>')[1]
pub_date = re.search(r'<published>([^T]+)', entry_block).group(1)

# Parse "Title | Speaker | Service" format
parts = full_title.split("|")
sermon_title = parts[0].strip() if len(parts) > 0 else full_title
speaker = parts[1].strip() if len(parts) > 1 else "Unknown"

print(f"Video: {video_id}")
print(f"Title: {sermon_title}")
print(f"Speaker: {speaker}")
print(f"Date: {pub_date}")

# Step 2: Get transcript
print("Fetching transcript...")
import subprocess
curl_result = subprocess.run([
    "curl", "-s", "-X", "POST",
    "https://www.youtube-transcript.io/api/transcripts",
    "-H", f"Authorization: Basic {env['YOUTUBE_TRANSCRIPT_API_TOKEN']}",
    "-H", "Content-Type: application/json",
    "-d", json.dumps({"ids": [video_id]})
], capture_output=True, text=True)
tdata = json.loads(curl_result.stdout)

transcript = ""
if isinstance(tdata, list) and len(tdata) > 0:
    item = tdata[0]
    transcript = item.get("text", "")
    if not transcript:
        tracks = item.get("tracks", [])
        if tracks:
            transcript = " ".join(s.get("text", "") for s in tracks[0].get("transcript", []))

if not transcript:
    print("ERROR: No transcript available")
    exit(1)

transcript = transcript[:8000]
print(f"Transcript: {len(transcript)} chars")

# Step 3: Generate content via Gemini
print("Generating sermon page content...")
prompt = f"""You are generating content for a church sermon page. You must be ACCURATE to what was actually preached. Do not invent or add anything not in the sermon.

Output valid JSON only. No markdown, no explanation, no code fences. Just the JSON object:

{{"summary": "3-4 sentences capturing the ACTUAL core message. Use the speaker's own words and ideas. Be specific not generic.", "quotes": ["An actual memorable statement the speaker REALLY SAID", "Another real quote", "Another if available"]}}

RULES:
- Every quote must be something the speaker ACTUALLY SAID
- The summary must reflect what was ACTUALLY PREACHED
- Be specific. No filler. No generic church-speak.
- Output ONLY valid JSON. Nothing else.

TRANSCRIPT:
{transcript}"""

gemini_req = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
}

req = urllib.request.Request(
    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={env['YOUTUBE_GEMINI_API_KEY']}",
    data=json.dumps(gemini_req).encode(),
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=60) as r:
    result = json.loads(r.read().decode())

ai_text = ""
for part in result["candidates"][0]["content"]["parts"]:
    if "text" in part:
        ai_text = part["text"].strip()
        break

# Clean code fences
if ai_text.startswith("```"):
    ai_text = ai_text.split("\n", 1)[1] if "\n" in ai_text else ai_text[3:]
if ai_text.endswith("```"):
    ai_text = ai_text[:-3]
ai_text = ai_text.strip()

ai_data = json.loads(ai_text)

# Build sermon.json
sermon = {
    "title": sermon_title,
    "speaker": speaker,
    "date": pub_date,
    "videoId": video_id,
    "summary": ai_data["summary"],
    "quotes": ai_data["quotes"]
}

with open("sermon.json", "w") as f:
    json.dump(sermon, f, indent=2)
print("sermon.json written")

# Step 4: Push
print("Pushing to GitHub...")
subprocess.run(["git", "add", "sermon.json"], check=True)
result = subprocess.run(["git", "commit", "-m", f"Update sermon: {sermon_title}"], capture_output=True, text=True)
if result.returncode == 0:
    subprocess.run(["git", "push"], check=True)
    print("DONE - pushed")
else:
    print("No changes to push")
