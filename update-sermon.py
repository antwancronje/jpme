#!/usr/bin/env python3
import json, urllib.request, subprocess, os, re

os.chdir("/home/ubuntu/jpme")

# Load env
env = {}
with open("/home/ubuntu/.jarvis/.env") as f:
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

# Check if this video is already live
try:
    with open("sermon.json") as f:
        current = json.load(f)
    if current.get("videoId") == video_id:
        print("NO UPDATE NEEDED - same video already live")
        import sys; sys.exit(0)
except SystemExit:
    raise
except:
    pass

print("New video detected - updating...")

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

{{"summary": "Exactly 2 sentences capturing the ACTUAL core message. Use the speaker's own words and ideas. Be specific not generic. Do NOT write more than 2 sentences.", "quotes": ["An actual memorable statement the speaker REALLY SAID", "Another real quote", "One more if available — maximum 3 quotes"]}}

RULES:
- Every quote must be something the speaker ACTUALLY SAID
- The summary must reflect what was ACTUALLY PREACHED
- Be specific. No filler. No generic church-speak.
- Output ONLY valid JSON. Nothing else.

TRANSCRIPT:
{transcript}"""

gemini_req = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}
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

# Clean common Gemini JSON issues
ai_text = ai_text.strip()
if ai_text.startswith("```json"):
    ai_text = ai_text[7:]
if ai_text.startswith("```"):
    ai_text = ai_text[3:]
if ai_text.endswith("```"):
    ai_text = ai_text[:-3]
ai_text = ai_text.strip()

try:
    ai_data = json.loads(ai_text)
except json.JSONDecodeError:
    try:
        import re
        match = re.search(r'\{[\s\S]*\}', ai_text)
        if match:
            ai_data = json.loads(match.group())
        else:
            raise ValueError("no json found")
    except:
        # Last resort: build it manually from the raw text
        print("WARN: JSON parse failed, extracting manually")
        summary_match = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', ai_text)
        quotes = re.findall(r'"((?:[^"\\]|\\.)*)"', ai_text)
        summary = summary_match.group(1) if summary_match else "Summary unavailable"
        # Filter out key names and short strings
        quotes = [q for q in quotes if len(q) > 30 and q != summary and "summary" not in q.lower() and "quotes" not in q.lower()]
        ai_data = {"summary": summary, "quotes": quotes[:3]}

# Build sermon.json
sermon = {
    "title": sermon_title,
    "speaker": speaker,
    "date": pub_date,
    "videoId": video_id,
    "summary": ai_data["summary"],
    "quotes": ai_data["quotes"]
}

# Step 4: Save as DRAFT only (approve-sermon.py writes sermon.json on publish)
with open("sermon-draft.json", "w") as f:
    json.dump(sermon, f, indent=2)
print("Draft saved to sermon-draft.json")

# Step 5: Send draft to Boss on Telegram for approval
with open("sermon-draft.json") as f:
    draft = json.load(f)

def esc_md(text):
    """Escape Telegram Markdown v1 special characters in user content."""
    for ch in ['_', '*', '`', '[']:
        text = text.replace(ch, '\\' + ch)
    return text

msg = f"🎬 *New Sermon Page Draft*\n\n"
msg += f"*{esc_md(draft['title'])}*\n"
msg += f"Speaker: {esc_md(draft['speaker'])}\n"
msg += f"Date: {draft['date']}\n\n"
msg += f"*Summary:*\n{esc_md(draft['summary'])}\n\n"
msg += f"*Quotes:*\n"
for i, q in enumerate(draft['quotes'][:3], 1):
    msg += f'{i}. "{esc_md(q)}"\n'
msg += f"\n✅ Reply to JARVIS with *go* to publish\n❌ Or tell me what to change"

bot_token = env.get("JARVIS_TELEGRAM_BOT_TOKEN", "")
chat_id = "5349965230"
if bot_token:
    import urllib.request
    tg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    tg_data = json.dumps({"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}).encode()
    tg_req = urllib.request.Request(tg_url, data=tg_data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(tg_req, timeout=10)
        print("DRAFT SENT TO TELEGRAM - waiting for Boss approval")
    except Exception as e:
        print(f"Telegram send failed: {e}")
        print("Draft saved locally - run manually")
else:
    print("No JARVIS_TELEGRAM_BOT_TOKEN found - draft saved locally only")
