# YT Sermon Check — Operations

This repo is the Jesus People sermon page. It shows the current week's sermon on **myjesus.co.za** (GitHub Pages, custom domain, deploys from `main`).

## Weekly flow

1. A new sermon is uploaded to the church YouTube channel.
2. The pipeline drafts a summary plus 3 short verbatim quotes, written in the pastor's voice.
3. On the pastor's explicit approval ("go"), it publishes to the site.

## Files

- `update-sermon.py` — detector/drafter. Reads the channel RSS, pulls the transcript, drafts the content, writes `sermon-draft.json`. (Its automatic drafting step is currently broken; drafting is done by hand until it is fixed.)
- `approve-sermon.py` — publisher. Reads `sermon-draft.json`, writes `sermon.json`, commits and pushes. Run only on approval.
- `sermon.json` — the currently published sermon. This is what the page renders.
- `sermon-draft.json` — a pending draft awaiting approval. Absent means nothing is pending.
- `index.html` — the page. Reads `sermon.json`.
- `service-worker.js` — PWA cache. `sermon.json` and page navigations are network-first, so a new sermon appears immediately; static assets stay cached.

## Publish (current manual method)

1. Confirm a new video exists (RSS) and differs from `sermon.json`.
2. Get the transcript.
3. Write `sermon-draft.json`: one summary plus exactly 3 quotes (see writing rules).
4. Present it to the pastor. Wait for "go". **Never publish without it.**
5. Run `./approve-sermon.py`. Live on myjesus.co.za within a couple of minutes.

## Writing rules

Summary in the pastor's voice: no em-dashes, short antithesis, fragments, plain words, straight to "you". Name the series or creed. End on a hook. Quotes: exactly 3, verbatim from the transcript, punchy and standalone.

## Full internal notes

Detailed setup, config, the voice profile, and known issues live in the JARVIS workspace (room "yt-sermon-check"), not in this public repo.
