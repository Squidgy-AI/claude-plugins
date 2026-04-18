---
name: hedra-list-voices
description: List Hedra TTS voices with optional filters (gender, accent, age). Use when the user wants to pick a voice for Character-3 intro videos or any Hedra TTS job.
---

# List Hedra Voices

Lists all voices available to the Hedra API key, with optional filters.

## Run

```bash
# All voices
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hedra-list-voices.py"

# Filter
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hedra-list-voices.py" --gender male --accent american --age young
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hedra-list-voices.py" --gender female --accent british
```

## Filter values

- `--gender`: `male` | `female`
- `--accent`: substring match, case-insensitive (e.g. `american`, `british`, `australian`)
- `--age`: `young` | `adult` | `middle aged` | `old`

## Output

One row per voice: `ID, Name, Gender, Accent, Age, Description`. Use the `ID` as `--voice-id` when calling the `avatar-intro-video` skill.
