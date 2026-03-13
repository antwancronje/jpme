#!/bin/bash
set -euo pipefail

source /root/.openclaw/.env
REPO="/root/jpme"
CHANNEL_RSS="https://www.youtube.com/feeds/videos.xml?channel_id=UCXPW-Zk-NPr4eRCOeQlDs0A"

# Step 1: Get latest video from RSS
echo "Fetching latest video from RSS..."
RSS=$(curl -s "$CHANNEL_RSS")
VIDEO_ID=$(echo "$RSS" | grep -oP '<yt:videoId>\K[^<]+' | head -1)
TITLE=$(echo "$RSS" | grep -oP '<media:title>\K[^<]+' | head -1)
PUB_DATE=$(echo "$RSS" | grep -oP '<published>\K[^<]+' | head -1 | cut -d'T' -f1)

# Parse speaker from title format "Title | Speaker | Service"
SPEAKER=$(echo "$TITLE" | awk -F'|' '{print $2}' | xargs)
SERMON_TITLE=$(echo "$TITLE" | awk -F'|' '{print $1}' | xargs)

echo "Video: $VIDEO_ID"
echo "Title: $SERMON_TITLE"
echo "Speaker: $SPEAKER"
echo "Date: $PUB_DATE"

# Step 2: Get transcript
echo "Fetching transcript..."
TRANSCRIPT=$(curl -s -X POST "https://www.youtube-transcript.io/api/transcripts" \
  -H "Authorization: Basic ${YOUTUBE_TRANSCRIPT_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"ids\": [\"${VIDEO_ID}\"]}" | python3 -c "
import json,sys
data=json.load(sys.stdin)
if isinstance(data,list) and len(data)>0:
    item=data[0]
    text=item.get('text','')
    if not text:
        tracks=item.get('tracks',[])
        if tracks:
            text=' '.join(s.get('text','') for s in tracks[0].get('transcript',[]))
    print(text[:8000])
else:
    print('')
")

if [ -z "$TRANSCRIPT" ]; then
  echo "ERROR: No transcript available"
  exit 1
fi
echo "Transcript: $(echo "$TRANSCRIPT" | wc -c) chars"

# Step 3: Generate content via Gemini
echo "Generating sermon page content..."
python3 << PYEOF
import json, urllib.request, os

transcript = """$TRANSCRIPT"""
speaker = "$SPEAKER"
sermon_title = "$SERMON_TITLE"
pub_date = "$PUB_DATE"
video_id = "$VIDEO_ID"

prompt = """You are generating content for a church sermon page. You must be ACCURATE to what was actually preached. Do not invent or add anything not in the sermon.

Output valid JSON only. No markdown, no explanation. Just the JSON object:

{
  "summary": "[3-4 sentences capturing the ACTUAL core message. Use the speaker's own words and ideas. Be specific not generic.]",
  "quotes": [
    "[An actual memorable statement the speaker REALLY SAID]",
    "[Another real quote]",
    "[Another if available]"
  ]
}

RULES:
- Every quote must be something the speaker ACTUALLY SAID
- The summary must reflect what was ACTUALLY PREACHED
- Be specific. No filler. No generic church-speak.
- Output ONLY valid JSON. Nothing else.

TRANSCRIPT:
""" + transcript

req = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
}

data = json.dumps(req).encode()
key = os.environ['YOUTUBE_GEMINI_API_KEY']
r = urllib.request.Request(
    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
    data=data,
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(r, timeout=60) as resp:
    result = json.loads(resp.read().decode())

parts = result['candidates'][0]['content']['parts']
ai_text = ""
for part in parts:
    if 'text' in part:
        ai_text = part['text'].strip()
        break

# Clean markdown code fences if present
if ai_text.startswith('```'):
    ai_text = ai_text.split('\n', 1)[1] if '\n' in ai_text else ai_text[3:]
if ai_text.endswith('```'):
    ai_text = ai_text[:-3]
ai_text = ai_text.strip()

ai_data = json.loads(ai_text)

# Build final sermon.json
sermon = {
    "title": sermon_title,
    "speaker": speaker,
    "date": pub_date,
    "videoId": video_id,
    "summary": ai_data["summary"],
    "quotes": ai_data["quotes"]
}

with open("$REPO/sermon.json", "w") as f:
    json.dump(sermon, f, indent=2)

print("sermon.json written")
PYEOF

# Step 4: Push to GitHub
echo "Pushing to GitHub..."
cd "$REPO"
git add sermon.json
git commit -m "Update sermon: $SERMON_TITLE" 2>/dev/null || echo "No changes to commit"
git push

echo "DONE"
