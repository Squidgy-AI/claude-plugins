# hedra-avatar-video (Claude Code plugin)

Generate talking-head intro videos from a still portrait + text script using Hedra Character-3. Optionally regenerate the source portrait first via Nano Banana Pro I2I to remove masking artifacts (white hair fringe from circular-cropped avatars).

## Install

User-level (current install):

```
~/.claude/plugins/hedra-avatar-video/
```

To add to another project/team, copy this directory into a shared plugin marketplace repo or into `.claude/plugins/` inside that project.

## Skills provided

- `/avatar-intro-video` — full pipeline: upload image → TTS → Character-3 → mp4
- `/hedra-list-voices` — discover voice IDs with filters

## Setup

Set the Hedra API key:

```bash
# option 1: env
export HEDRA_API_KEY=sk_hedra_...

# option 2: file (the script checks this path automatically)
echo -n 'sk_hedra_...' > /Users/sethward/GIT/Squidgy/.hedra-api-key
chmod 600 /Users/sethward/GIT/Squidgy/.hedra-api-key
```

## Scripts

- `scripts/hedra-intro-video.py` — main pipeline
- `scripts/hedra-list-voices.py` — voice discovery

Both are standalone and can be run outside Claude Code.
