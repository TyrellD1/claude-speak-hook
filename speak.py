#!/usr/bin/env python3
"""Stop hook: read Claude's last reply aloud with macOS `say`.

On/off switch: it only speaks while ~/.claude/speak.on exists.
  touch ~/.claude/speak.on   # on
  rm ~/.claude/speak.on      # off

Settings (env vars, e.g. in the "env" block of ~/.claude/settings.json):
  SPEAK_VOICE              a `say -v` voice name (default: system voice)
  SPEAK_RATE               words per minute (default: system rate)
  SPEAK_MAX_CHARS          without a summary, cut the text here (default 1500, 0 = no limit)

  SPEAK_SUMMARY            "1"/"true" to speak a short summary instead of the reply itself
  SPEAK_SUMMARY_MODEL      model for the summary (default "haiku")
  SPEAK_SUMMARY_WORDS      target length of the summary in words (default 60)
  SPEAK_SUMMARY_MIN_CHARS  replies shorter than this are read in full (default 400)
  SPEAK_CLAUDE_BIN         path to the `claude` CLI (default: found on PATH)

The summary runs `claude -p` in the background, so it uses your Claude login
(run `claude auth login` once in a terminal). It gets the previous reply, your
latest prompt and the latest reply. If it fails, the cut-off reply is read
instead and the reason goes to ~/.claude/hooks/speak.log.

Only one message plays at a time, across all sessions: each one waits on a
lock file and plays when the one ahead of it finishes. `pkill -x say` skips
the message playing now.
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ON_FILE = os.path.expanduser("~/.claude/speak.on")
LOG_FILE = os.path.expanduser("~/.claude/hooks/speak.log")
STATE_DIR = tempfile.gettempdir()
LOCK_FILE = os.path.join(STATE_DIR, "claude-speak-hook.lock")
CHILD_FLAG = "SPEAK_HOOK_CHILD"


def env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def log(msg: str) -> None:
    try:
        with open(LOG_FILE, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg.replace("\n", " ")[:500] + "\n")
    except OSError:
        pass


# ---------- text cleanup ----------

def clean(text: str) -> str:
    text = re.sub(r"```.*?```", " (code block) ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links / images -> label
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"^\s*\|?[-:| ]+\|[-:| ]*$", "", text, flags=re.M)  # table rules
    text = text.replace("|", ", ")
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)  # headings
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)  # bullets
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)  # bold / italics
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def truncate(text: str) -> str:
    limit = env_int("SPEAK_MAX_CHARS", 1500)
    if limit and len(text) > limit:
        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("\n"))
        text = (cut[: end + 1] if end > limit // 2 else cut) + " ... and more on screen."
    return text


def strip_tags(text: str) -> str:
    """Drop harness blocks such as <system-reminder>...</system-reminder> from a prompt."""
    text = re.sub(r"<(system-reminder|command-[\w-]+|local-command-[\w-]+)>.*?</\1>", "", text, flags=re.S)
    return text.strip()


def tail(text: str, n: int) -> str:
    return text if len(text) <= n else "..." + text[-n:]


# ---------- speaking ----------

def speak_now(text: str) -> None:
    """Wait for our turn in the queue, then speak and block until done."""
    cmd = ["say"]
    if os.environ.get("SPEAK_VOICE"):
        cmd += ["-v", os.environ["SPEAK_VOICE"]]
    if os.environ.get("SPEAK_RATE"):
        cmd += ["-r", os.environ["SPEAK_RATE"]]
    with open(LOCK_FILE, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # released when this process lets go of the file
        subprocess.run(cmd, input=text.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def spawn(*args: str) -> None:
    """Run this script again, detached, so the hook itself returns at once."""
    subprocess.Popen(
        [sys.executable, "-I", os.path.abspath(__file__), *args],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def speak(text: str) -> None:
    fd, path = tempfile.mkstemp(prefix="claude-speak-", suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    spawn("--say", path)


def latest_file(session_id: str) -> str:
    safe = re.sub(r"[^\w-]", "", session_id or "default")
    return os.path.join(STATE_DIR, f"claude-speak-hook.{safe}.latest")


# ---------- summary ----------

def read_context(transcript_path: str):
    """Return (previous assistant reply, latest user prompt) from the transcript."""
    turns = []  # list of [user_prompt, [assistant texts]]
    try:
        with open(transcript_path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("isSidechain") or d.get("isMeta"):
                    continue
                msg = d.get("message") or {}
                content = msg.get("content")
                if d.get("type") == "user":
                    if isinstance(content, str):
                        prompt = content
                    elif isinstance(content, list) and all(b.get("type") == "text" for b in content):
                        prompt = "\n".join(b.get("text", "") for b in content)
                    else:
                        continue  # tool results, images, etc.
                    prompt = strip_tags(prompt)
                    if prompt:
                        turns.append([prompt, []])
                elif d.get("type") == "assistant" and turns and isinstance(content, list):
                    for b in content:
                        if b.get("type") == "text" and b.get("text", "").strip():
                            turns[-1][1].append(b["text"])
    except OSError as e:
        log(f"transcript unreadable: {e}")
    latest_prompt = turns[-1][0] if turns else ""
    previous_reply = "\n".join(turns[-2][1]) if len(turns) > 1 else ""
    return previous_reply, latest_prompt


def find_claude() -> str:
    for c in (os.environ.get("SPEAK_CLAUDE_BIN"), shutil.which("claude"),
              os.path.expanduser("~/.local/bin/claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise RuntimeError("claude CLI not found; set SPEAK_CLAUDE_BIN")


def summarize(latest_reply: str, transcript_path: str) -> str:
    previous_reply, latest_prompt = read_context(transcript_path or "")
    words = env_int("SPEAK_SUMMARY_WORDS", 60)
    system = (
        "You turn a coding assistant's reply into a short summary that will be read aloud by text-to-speech. "
        f"Write one to three plain sentences, never more than {words} words in total. Say what was done or "
        "found, and any question or decision the reply leaves for the user; don't invent questions it didn't ask. "
        "Talk to the user as 'you' and refer to the assistant as 'I'. "
        "No markdown, lists, code, file paths, or URLs. Output only the summary."
    )
    user = (
        f"<previous_reply>\n{tail(previous_reply, 3000) or '(none)'}\n</previous_reply>\n\n"
        f"<user_prompt>\n{tail(latest_prompt, 3000) or '(none)'}\n</user_prompt>\n\n"
        f"<latest_reply>\n{tail(latest_reply, 12000)}\n</latest_reply>\n\n"
        "Summarize latest_reply. Use the other two only as context."
    )
    env = {k: v for k, v in os.environ.items()
           if not (k == "CLAUDECODE" or k.startswith(("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")) or k in ("CLAUDE_PID", "CLAUDE_EFFORT"))
           or k == "CLAUDE_CODE_OAUTH_TOKEN"}
    env[CHILD_FLAG] = "1"  # our own Stop hook must not fire for this call
    cmd = [
        find_claude(), "-p",
        "--model", os.environ.get("SPEAK_SUMMARY_MODEL", "haiku"),
        "--system-prompt", system,
        "--tools", "",
        "--setting-sources", "project",  # skip user settings: no hooks or plugins
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    out = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=60,
                         env=env, cwd=tempfile.gettempdir())
    text = out.stdout.strip()
    if out.returncode != 0 or not text:
        raise RuntimeError(f"claude -p exit {out.returncode}: {(out.stderr or out.stdout).strip()[:300]}")
    return clean(text)


def worker(payload_path: str) -> int:
    with open(payload_path) as f:
        job = json.load(f)
    os.unlink(payload_path)
    reply = job["reply"]
    try:
        text = summarize(reply, job.get("transcript_path", ""))
    except Exception as e:  # noqa: BLE001 - any failure falls back to reading the reply
        log(f"summary failed, reading reply instead: {e}")
        text = truncate(clean(reply))
    try:
        with open(latest_file(job.get("session_id", ""))) as f:
            if f.read().strip() != job["token"]:
                return 0  # this session sent a newer reply while we were summarizing
    except OSError:
        pass
    speak_now(text)
    return 0


# ---------- hook entry ----------

def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return worker(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--say":
        with open(sys.argv[2]) as f:
            text = f.read()
        os.unlink(sys.argv[2])
        speak_now(text)
        return 0
    if os.environ.get(CHILD_FLAG) or not os.path.exists(ON_FILE):
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("stop_hook_active"):
        return 0
    reply = data.get("last_assistant_message") or ""
    if not clean(reply):
        return 0

    token = str(time.time_ns())
    session_id = data.get("session_id", "")
    with open(latest_file(session_id), "w") as f:
        f.write(token)

    if not env_bool("SPEAK_SUMMARY") or len(clean(reply)) < env_int("SPEAK_SUMMARY_MIN_CHARS", 400):
        speak(truncate(clean(reply)))
        return 0

    # Summarizing takes a few seconds, so hand it to a detached worker and return now.
    fd, path = tempfile.mkstemp(prefix="claude-speak-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump({"reply": reply, "transcript_path": data.get("transcript_path", ""),
                   "token": token, "session_id": session_id}, f)
    spawn("--worker", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
