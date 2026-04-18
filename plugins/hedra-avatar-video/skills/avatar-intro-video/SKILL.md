---
name: avatar-intro-video
description: Generate a talking-head intro video for an agent/persona using Hedra Character-3 (image + TTS → mp4). Use when the user asks to create an intro, promo, or avatar video from a still portrait and a script. Can also regenerate the source portrait via Nano Banana Pro I2I to fix masking/fringe artifacts.
---

# Avatar Intro Video (Hedra Character-3)

Generate a short talking-head video from a portrait image + spoken script.

## Prerequisites

- Hedra API key available as `HEDRA_API_KEY` env var OR at `/Users/sethward/GIT/Squidgy/.hedra-api-key`
- Python 3.10+ with `requests` installed

## Pick a voice

If the user hasn't supplied a `voice_id`, use the companion skill `hedra-list-voices` to filter, e.g.:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hedra-list-voices.py" --gender male --accent american --age young
```

Common picks (verified):
- `64f274fb-bbae-4151-8a2f-9aa8794b897f` — Liam, young American male, warm
- `e8e70cb7-97de-4571-9bab-3d33ce5fc8dc` — David, adult male, trustworthy/professional
- `7e2868a2-2269-44dd-98a4-07c3496abf09` — Alice, British female, friendly

## Script-writing rules

Length targets at normal pace:
- 15s ≈ 40 words
- 20s ≈ 55 words
- 30s ≈ 80 words

Structure an agent intro as:
1. **Hook / name** ("Hey, I'm Brandy.")
2. **What I do** — concrete capabilities, not vague mission
3. **Who it's for / outcome** — one line
4. **CTA** — what to do next ("Ask me to…" / "Let's start with…")

Avoid corporate filler ("empower", "leverage", "cutting-edge"). Use the agent's own tone from its config.

## Fix fringe artifacts on the source portrait

Many existing avatars are circular-cropped PNGs with white/transparent halo around hair. Character-3 picks up those artifacts. To get a clean baseline:

- Pass `--regen-image` with an `--image-prompt` describing the desired 16:9 portrait on a solid background.
- The script uses Nano Banana Pro I2I with the original as a reference, so the person stays recognisable.
- Cost: ~15 credits per regen try.

## Run the video pipeline

One-shot (portrait is already clean, square or 16:9):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hedra-intro-video.py" \
  --image /abs/path/to/portrait.png \
  --script "Hey, I'm … (full spoken script here)" \
  --voice-id 64f274fb-bbae-4151-8a2f-9aa8794b897f \
  --out /abs/path/to/output.mp4 \
  --aspect-ratio 16:9 \
  --resolution 720p
```

With portrait regeneration:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hedra-intro-video.py" \
  --image /abs/path/to/original.png \
  --regen-image \
  --image-prompt "Photorealistic studio portrait of the same person … 16:9 gradient background, clean hair edges, no artifacts" \
  --regen-out /abs/path/to/portrait_v2.png \
  --script "…" \
  --voice-id <id> \
  --out /abs/path/to/output.mp4
```

## Output

The script prints the final mp4 path on stdout. Open it with `open <path>` on macOS.

## Cost

Character-3: 6 credits/sec. A 20s 720p video ≈ 120 credits (~$0.30). 1080p is 1.6× (~$0.50).
Nano Banana Pro I2I regen: 15 credits per image (~$0.04).

## Troubleshooting

- **422 "Field required (…generated_video_inputs)"** — video body uses nested `generated_video_inputs`; image body uses flat fields. Script handles both.
- **400 "model missing not valid for generation type text_to_speech"** — TTS must be a separate `/generations` call first (type=text_to_speech), then pass the returned `asset_id` as `audio_id` in the video call. Script does this in two steps.
- **502 during polling** — handled with retry. If you see it from an external caller, just re-GET `/generations/{id}/status`.
- **Image result has no `url` in `/status`** — images are fetched via `GET /assets?type=image&ids=<asset_id>` instead. Script handles this.
