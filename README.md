# Squidgy Claude Code Plugin Marketplace

Shared plugin marketplace for the Squidgy team. Install once, get all Squidgy-specific skills, agents, and scripts as slash commands in Claude Code.

## Install

From any Claude Code session:

```
/plugin marketplace add Squidgy-AI/claude-plugins
/plugin install hedra-avatar-video@squidgy
```

To pick up updates later:

```
/plugin marketplace update squidgy
```

## Plugins

### hedra-avatar-video

Generate talking-head intro videos for agents/personas via Hedra Character-3.

- `/avatar-intro-video` — one-shot pipeline: portrait → TTS → Character-3 → mp4
- `/hedra-list-voices` — discover voice IDs with filters

Features: auto-regenerate clean 16:9 portraits via Nano Banana Pro I2I (fixes circular-crop fringe), silence-padded endings so the avatar settles to a resting face, start-frame trim for the first-frame soft-focus, and burned-in captions in Baloo 2 with the Squidgy brand palette.

Requires `HEDRA_API_KEY` (env var or `/Users/sethward/GIT/Squidgy/.hedra-api-key`) and `ffmpeg`.

## Adding a new plugin

1. Create `plugins/<plugin-name>/` with the standard layout:
   ```
   .claude-plugin/plugin.json
   skills/<skill-name>/SKILL.md
   scripts/…                         # optional bundled scripts
   README.md
   ```
2. Add an entry to `.claude-plugin/marketplace.json`.
3. Commit to `sw-branch`, open a PR, merge to `main`.
4. Teammates run `/plugin marketplace update squidgy` to pick up the new plugin.

## Conventions

- Skills reference bundled scripts via `${CLAUDE_PLUGIN_ROOT}/scripts/...` (never absolute paths)
- Scripts are self-contained and runnable outside Claude Code
- Prefer Python stdlib + `requests`; node/ts OK if the target integration is JS-native
- Include a `README.md` per plugin with prereqs, env vars, and a minimal example
