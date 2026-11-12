# claude-speak-hook: notes for agents

A Claude Code Stop hook that reads replies aloud with macOS `say`. One script, `speak.py`.
Keep it small: no dependencies beyond the Python standard library.

## This folder is shared by two Mac users

- **`/Users/Shared/claude-speak-hook` is used by `tydowner` and `cmc_tyrell`.** Each user's
  `~/.claude/hooks/speak.py` is a link to `speak.py` here, so a change here changes the hook
  for both at once.
- **Every commit must be by `Tyrell Downer <tdowner4@gmail.com>`.** The repo's own
  `.git/config` sets that for both users; never change it, and check with
  `git var GIT_AUTHOR_IDENT` before a commit.
- **Use plain `git` here, not GitButler.** This is an exception to Tyrell's global rule:
  GitButler keeps its project list per user, so it is not used in a shared folder. Commit on
  `main` (`git commit -m "..."`), then `git push origin main`.
- **Only `tydowner` pushes.** `cmc_tyrell` is signed in to a different GitHub account, so on
  that user commit and stop; do not push, pull or fetch. `.git/hooks/pre-push` refuses it.
  The hook is not in the repo's history, so a fresh clone lacks it.
- **Never use `sudo`, `chown` or `chmod` on this folder.** An access rule on it lets both
  users edit every file, and new files pick it up on their own. A file moved in from
  elsewhere, rather than made here, does not.

## Setup for the second user (`cmc_tyrell`)

```bash
git config --global --add safe.directory /Users/Shared/claude-speak-hook
mkdir -p ~/.claude/hooks
ln -sf /Users/Shared/claude-speak-hook/speak.py ~/.claude/hooks/speak.py
touch ~/.claude/speak.on
```

Then add the Stop hook and `env` block from `README.md` to that user's
`~/.claude/settings.json`. Summary mode needs `claude auth login` once as that user.
`git var GIT_AUTHOR_IDENT` in this folder must print `Tyrell Downer <tdowner4@gmail.com>`.

## Testing

- The hook reads JSON on stdin. Try it with
  `echo '{"last_assistant_message":"Hello there.","session_id":"t"}' | python3 -I speak.py`.
- Set `SPEAK_HOOK_CHILD=1` to make the hook exit without speaking.
- Failures go to `~/.claude/hooks/speak.log`.
