#!/usr/bin/env python3
"""
Cron-driven YouTube sermon detector. Runs every 2 hours.
Detects new uploads from Jesus People SA channel, writes sermon-draft.json,
sends formatted draft to Antwan's Telegram for approval.
Never writes sermon.json (that's approve-sermon.py's job).
"""
import json, urllib.request, urllib.parse, subprocess, os, re, sys, time

os.chdir("/home/ubuntu/jpme")

env = {}
with open("/home/ubuntu/.jarvis/.env") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

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

# Step 1b: Skip if already drafted or published
for fname in ("sermon.json", "sermon-draft.json"):
    if os.path.exists(fname):
        try:
            with open(fname) as f:
                existing = json.load(f)
            if existing.get("videoId") == video_id:
                print(f"Already in {fname} - nothing to do")
                sys.exit(0)
        except Exception:
            pass

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
prompt = f"""You are writing the description for a church sermon video page. Your job is to make people want to watch.

This is a COPYWRITER PITCH, not an outline. Not a recap. Not a table of contents.

Output valid JSON only. No markdown, no explanation, no code fences:

{{"summary": "2-3 sentence pitch. Hook with the tension, lie, or question the sermon answers. Promise the payoff. Name specific Scriptures for SEO. Reframe everything in your own words.", "quotes": ["Punchy standalone line", "Another standalone line", "Another standalone line"]}}

SUMMARY RULES:
- 2-3 sentences MAXIMUM. Tight.
- Sentence 1: hook with the tension, lie, question, or contrarian punch the sermon addresses ("Culture says X. Scripture says Y.")
- Sentence 2-3: promise what the listener walks away with, name the specific Scriptures the speaker opens.
- NEVER stitch the speaker's exact phrases into the summary. Reframe in your own words.
- NEVER list out the sermon outline ("three points," "first he says, then he says").
- NEVER use generic church-speak ("powerful message," "transformative truth," "biblical insights").
- Write like you're pitching the video to a stranger scrolling YouTube.

QUOTE RULES:
- Pull 3 of the most memorable standalone lines the speaker ACTUALLY SAID.
- Each quote must make sense on its own with NO context needed. If it needs setup, skip it.
- Punchy. Short. Quotable. The kind of line that lands.
- Verbatim from the transcript — no paraphrasing quotes.

Output ONLY valid JSON. Nothing else.

TRANSCRIPT:
{transcript}"""

gemini_req = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {
        "temperature": 0.2,
        "maxOutputTokens": 4096,
        "responseMimeType": "application/json"
    }
}

def _alert_antwan(reason):
    """Telegram the user that the auto-draft failed so they can draft manually."""
    bot_token = env.get("JARVIS_TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "5349965230")
    if not bot_token:
        return
    msg = (
        f"⚠️ New sermon detected — auto-draft FAILED\n\n"
        f"Title: {sermon_title}\n"
        f"Date: {pub_date}\n"
        f"Video: {video_id}\n\n"
        f"Reason: {reason}\n\n"
        f"JARVIS, draft this manually using the copywriter playbook."
    )
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
        ), timeout=30)
    except Exception:
        pass

# Gemini call with retry (handles 503 model-overloaded responses)
result = None
last_err = None
for attempt, delay in enumerate([0, 30, 60, 120]):
    if delay:
        print(f"Gemini retry {attempt} in {delay}s...")
        time.sleep(delay)
    try:
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={env['YOUTUBE_GEMINI_API_KEY']}",
            data=json.dumps(gemini_req).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read().decode())
        break
    except Exception as e:
        last_err = e
        print(f"Gemini attempt {attempt+1} failed: {e}")

if result is None:
    _alert_antwan(f"Gemini API failed after 4 attempts: {last_err}")
    print(f"FATAL: Gemini API failed after retries — alert sent. Last error: {last_err}")
    sys.exit(1)

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

# Build sermon-draft.json (NOT sermon.json - approve-sermon.py handles publishing)
sermon = {
    "title": sermon_title,
    "speaker": speaker,
    "date": pub_date,
    "videoId": video_id,
    "summary": ai_data["summary"],
    "quotes": ai_data["quotes"]
}

with open("sermon-draft.json", "w") as f:
    json.dump(sermon, f, indent=2)
print("sermon-draft.json written")

# Step 4: Send draft to Antwan's Telegram for approval
def md2_escape(text):
    # Backslash first to avoid double-escaping subsequent additions
    for ch in ["\\", "_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]:
        text = text.replace(ch, "\\" + ch)
    return text

t_title = md2_escape(sermon_title)
t_speaker = md2_escape(speaker)
t_date = md2_escape(pub_date)
t_vid = md2_escape(video_id)
t_summary = md2_escape(ai_data["summary"])
quote_lines = "\n".join(f"{i+1}\\. {md2_escape(q)}" for i, q in enumerate(ai_data["quotes"]))

draft_msg = (
    f"\U0001F3AC *New Sermon Page Draft*\n\n"
    f"*Title:* {t_title}\n"
    f"*Speaker:* {t_speaker}\n"
    f"*Date:* {t_date}\n"
    f"*Video:* {t_vid}\n\n"
    f"*Summary:*\n{t_summary}\n\n"
    f"*Quotes:*\n{quote_lines}\n\n"
    f"Reply *Go* to publish, or send edits\\."
)

bot_token = env.get("JARVIS_TELEGRAM_BOT_TOKEN", "")
chat_id = env.get("TELEGRAM_CHAT_ID", "5349965230")

if not bot_token:
    print("ERROR: no telegram bot token in env")
    sys.exit(1)

tg_data = urllib.parse.urlencode({
    "chat_id": chat_id,
    "text": draft_msg,
    "parse_mode": "MarkdownV2"
}).encode()
tg_req = urllib.request.Request(
    f"https://api.telegram.org/bot{bot_token}/sendMessage",
    data=tg_data
)
try:
    with urllib.request.urlopen(tg_req, timeout=15) as r:
        r.read()
    print("DONE - draft sent to Telegram")
except Exception as e:
    print(f"TELEGRAM FAILED: {e}")
    sys.exit(1)
