#!/usr/bin/env python3
"""
Cron-driven YouTube sermon detector. Runs every 2 hours.
Detects new uploads from Jesus People SA channel, writes sermon-draft.json,
sends formatted draft to Antwan's Telegram for approval.
Never writes sermon.json (that's approve-sermon.py's job).
AI brain: Claude (headless via Claude Max OAuth). No Google dependency.
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

print(f"Transcript: {len(transcript)} chars")

# Step 3: Generate content via Claude (headless via Claude Max OAuth)
print("Generating sermon page content via Claude...")
prompt = f"""You are a COPYWRITER writing a YouTube video description for a church sermon. Your job is to make a stranger scrolling YouTube click play. This is a sales pitch for the video, NOT a content recap.

Output valid JSON only. No markdown, no explanation, no code fences:

{{"summary": "...", "quotes": ["...", "...", "..."]}}

THE TWO HARD RULES YOU WILL BE TESTED ON:

RULE 1 — NO OUTLINE LANGUAGE IN THE SUMMARY.
The summary MUST NOT enumerate the sermon's structure. Forbidden patterns:
- "three levels of X — A, B, and C"
- "breaks down [N] [things]"
- "covers three points"
- "first explains X, then Y, then Z"
- ANY phrasing that lists what the sermon contains
A pitch sells the experience. An outline lists the contents. You are writing a pitch.

RULE 2 — QUOTES ARE VERBATIM. NEVER PARAPHRASE.
Each quote must appear character-for-character in the transcript. Do not "clean up" contractions, do not change "isn't" to "is not", do not adjust punctuation. Copy-paste fidelity. If you change one word, you have failed.

SUMMARY STRUCTURE (~60-80 words, 2-3 sentences):
- Sentence 1: A tension hook. "Culture says X. Scripture says Y." Or "Most Christians do X. Scripture does Y." Or a contrarian punch that names the lie the sermon exposes.
- Sentence 2-3: Name the specific Scriptures by name (for SEO — e.g. "Hebrews 11, James 2, and John 3"). Tease the payoff WITHOUT spoiling it. Make the reader want to watch.
- NEVER stitch the speaker's exact phrases into the summary. Reframe in your own words.
- NEVER use church-speak ("powerful," "transformative," "biblical insights," "unpacks").

GOOD EXAMPLE (approved by Antwan):
"Most Christians treat the Holy Spirit like a power to plug into when life gets hard. Scripture says He's a Person who wants to be known. In part 1 of the Introduction to the Holy Spirit series, Pastor Antwan opens John 14, Ephesians 4, and Acts 1:8 to show who the Holy Spirit really is, why your sin grieves Him like betrayal, and the simple daily habit that turns Him from a doctrine into a friend."

QUOTE RULES:
- 3 of the most memorable standalone lines the speaker actually said.
- Each must stand alone with NO context. If it needs setup, skip it.
- Punchy. Short. Quotable.
- VERBATIM from the transcript. Search the transcript for your candidate quote and confirm it appears EXACTLY before including it.

Output ONLY valid JSON. Nothing else.

TRANSCRIPT:
{transcript}"""

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

# Claude call with retry (rare but possible: OAuth glitch, network hiccup)
claude_bin = "/home/ubuntu/.local/bin/claude"
claude_env = os.environ.copy()
claude_env["HOME"] = "/home/ubuntu"

ai_text = None
last_err = None
for attempt, delay in enumerate([0, 30, 60]):
    if delay:
        print(f"Claude retry {attempt} in {delay}s...")
        time.sleep(delay)
    try:
        proc = subprocess.run(
            [claude_bin, "-p", "--model", "sonnet", "--output-format", "text"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            env=claude_env,
        )
        if proc.returncode != 0:
            last_err = f"claude exit {proc.returncode}: {proc.stderr.strip()[:500]}"
            print(f"Claude attempt {attempt+1} failed: {last_err}")
            continue
        ai_text = proc.stdout.strip()
        if not ai_text:
            last_err = "empty stdout"
            print(f"Claude attempt {attempt+1} failed: empty stdout")
            continue
        break
    except subprocess.TimeoutExpired:
        last_err = "timeout after 180s"
        print(f"Claude attempt {attempt+1} timed out")
    except Exception as e:
        last_err = str(e)
        print(f"Claude attempt {attempt+1} failed: {e}")

if not ai_text:
    _alert_antwan(f"Claude failed after 3 attempts: {last_err}")
    print(f"FATAL: Claude failed after retries — alert sent. Last error: {last_err}")
    sys.exit(1)

# Clean code fences if present
if ai_text.startswith("```"):
    ai_text = ai_text.split("\n", 1)[1] if "\n" in ai_text else ai_text[3:]
if ai_text.endswith("```"):
    ai_text = ai_text[:-3]
ai_text = ai_text.strip()

try:
    ai_data = json.loads(ai_text)
except json.JSONDecodeError as e:
    _alert_antwan(f"Claude returned non-JSON: {e}")
    print(f"FATAL: Claude output not valid JSON: {e}")
    print(f"Raw output: {ai_text[:500]}")
    sys.exit(1)

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
