# claude-speak-hook

A Claude Code Stop hook that reads Claude's replies aloud on macOS with the built-in `say` command.

- Short replies are read in full. Longer ones can be turned into a spoken summary of one to three sentences by Haiku, through `claude -p` on your own Claude login.
- The summary prompt gets the previous reply, your latest prompt and the latest reply, so it has some context.
- Only one message plays at a time across all your sessions. The others wait their turn.
- The hook returns right away. Summarizing and speaking happen in a background process.
- If a summary fails, the reply is read instead (cut off at a sentence near `SPEAK_MAX_CHARS`), and the reason is written to `~/.claude/hooks/speak.log`.

## Install

```bash
mkdir -p ~/.claude/hooks
ln -s "$PWD/speak.py" ~/.claude/hooks/speak.py
touch ~/.claude/speak.on
```

Tyrell's copy lives in `/Users/Shared/claude-speak-hook` so two Mac users can share it. See `CLAUDE.md`.

Then add the hook to `~/.claude/settings.json`:

```json
{
  "env": {
    "SPEAK_SUMMARY": "true"
  },
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 -I \"$HOME/.claude/hooks/speak.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Summary mode needs the `claude` command line to be logged in. Run `claude auth login` once in a terminal. The Claude desktop app signs in its own sessions separately, so the terminal login can be expired without you noticing.

## Use

| Do this | Command |
| --- | --- |
| Turn speech off | `rm ~/.claude/speak.on` |
| Turn speech on | `touch ~/.claude/speak.on` |
| Skip the message playing now | `pkill -x say` |
| Preview a voice | `say -v Daniel "Testing this voice."` |
| List voices | `say -v '?'` |

## Settings

Set these in the `env` block of `~/.claude/settings.json`.

| Variable | Default | What it does |
| --- | --- | --- |
| `SPEAK_SUMMARY` | off | `true` speaks a short summary instead of the reply |
| `SPEAK_SUMMARY_MODEL` | `haiku` | Model used for the summary |
| `SPEAK_SUMMARY_WORDS` | `60` | Maximum length of the summary in words |
| `SPEAK_SUMMARY_MIN_CHARS` | `400` | Replies shorter than this are read in full |
| `SPEAK_MAX_CHARS` | `1500` | Without a summary, where to cut the reply (`0` = no limit) |
| `SPEAK_TITLE` | on | Announce the session's name before each message; `false` turns it off |
| `SPEAK_TITLE_VOICE` | `Daniel` | Voice for the session name, so it stands apart from the message |
| `SPEAK_VOICE` | system voice | Any name from `say -v '?'` |
| `SPEAK_RATE` | system rate | Words per minute |
| `SPEAK_CLAUDE_BIN` | found on `PATH` | Path to the `claude` command |

For better voices, download an Enhanced or Premium voice in System Settings → Accessibility → Spoken Content → System voice → Manage Voices.

## How it works

1. Claude Code runs the hook when a reply finishes and passes it `last_assistant_message`, `transcript_path` and `session_id`.
2. A short reply, or any reply with summaries off, has its markdown stripped and is queued to be spoken.
3. With summaries on, a background process reads the previous reply and your latest prompt from the transcript. It then runs `claude -p --model haiku` with no tools, no MCP servers and no user settings, so your hooks and plugins don't load. That call doesn't save a session, and an environment flag stops it from triggering this hook again.
4. If the same session sends a newer reply while a summary is being made, the older summary is dropped.
5. Each message waits on a shared lock file, then plays with `say`. Order is first come, first served in practice, but not strictly guaranteed.
