# Main Profile apps: a Terminal with a small language, Files that browse, and small comforts

Date: 2026-10-16. Kind: implementation record. Follows the shell
([2026-10-03-GUI-SHELL.md](2026-10-03-GUI-SHELL.md)) and the recursive MVU
app contract ([2026-10-14-RECURSIVE-MVU-SHELL.md](2026-10-14-RECURSIVE-MVU-SHELL.md)).

## What changed, from the user's chair

- **Files** (the Browser archive) browses the namespace as directories. A
  directory is a prefix of the flat URL set: the root shows `home/`,
  `logs/`, `services/`..., Enter descends, Backspace goes up with the cursor
  on the directory just left, Enter on a file opens it as text. The status
  line says how many folders and files are under the prefix, and for an
  open file its line and byte counts. Any text a URL's owner answers to a
  read is viewable: a file under `/home` or `/tmp`, a log ring, a service's
  status page.
- **Terminal** (new, `terminal.qa`) is a command line over the same
  namespace, with a small language, `qsh`, described below. Typed keys reach
  it, Space included; Up and Down recall history; Page Up and Down scroll
  the output; ctrl-L clears it; ctrl-U erases the line.
- **Clock** shows the runtime time with hours, and has a stopwatch: Space
  starts and stops it, L takes a lap (the last six are listed), Backspace
  resets. Its resolution is the clock job's: one second.
- **Logs** says in its status line which keys choose a severity (N W E H),
  how many lines it shows, and that they are newest first; P pauses the
  automatic refresh so a line can be read while the system is busy, and
  resumes it.
- **The shell**: a space typed into an open app is a space (it used to act
  as Enter). Snapshots are P from the home grid and the shortcuts, and
  ctrl-P anywhere, so a typed p is the app's.

## qsh

A line is commands separated by `;`. A command is a pipeline of stages
separated by `|`. Every stage takes a list of lines and gives a list of
lines; the pipeline's output is printed, or kept when the command is
`let name = pipeline`, after which `$name` in a later command stands for
those lines as words.

| stage | does |
|---|---|
| `ls [path]` | what is directly under a prefix: deeper paths as `name/`, files as `name` |
| `cat <path>` | the text a URL answers to a read |
| `write <path> [text]` | replace a file's text with the words, or with the piped lines |
| `append <path> [text]` | add to a file (creating it) |
| `touch <path>`, `mkdir <path>`, `rm <path>` | create an empty file; create a directory (an empty `.dir` under it); delete a file |
| `cd [path]`, `pwd` | the working prefix (`/home` at start; `..` and `.` are understood) |
| `echo`, `grep <text>`, `head [n]`, `tail [n]`, `count`, `sort`, `rev`, `nl`, `uniq` | the usual filters, over lines |
| `ps` | the live actors of this process (id, running or blocked, parent) |
| `logs [n\|w\|e\|h]` | a log ring's lines |
| `uptime`, `history`, `vars`, `clear`, `help` | as named |

Pure stages run at once. A stage that reads or writes the namespace is one
job in the app's worker (the same persistent, deadline-bounded worker the
other apps use), and the pipeline resumes when the result arrives, so a
slow owner never blocks the shell; a second line typed meanwhile is
refused with "busy". Errors are lines beginning `error:`. There is no
quoting: words are split on spaces.

## The file namespaces

Files live under `/home` and `/tmp`, one actor per file over the storage
log (qsys's `filesMgr`). Two things changed so that a terminal can delete:

- The manager now registers each file's URL with itself as owner, and
  redirects an open to the file's actor (a hop that the first open already
  took). Only the owner of a URL may withdraw it, and the manager is now
  that owner.
- Opening a file in the `delete` mode makes the manager end the file's
  actor, withdraw its URL and delete its records; a delete of a file that
  does not exist is refused by name, like a read. A `write` from the
  Terminal is a delete followed by an append, because the files are
  append-only logs whose text is the replay of their records.

The manager also notices a file actor that has ended (a path whose owner is
dead is treated as absent), which an earlier kill would have left as a
stale entry.

The app wire grew `WritePath`, `AppendPath` and `DeletePath` jobs and a
`Done` snapshot; its magic is `qos.app-session/3`, so the shell and the
five archives rebuild together, as the contract says.

## Verification

- `tests/appsession.fpr` (in the smoke set and the GUI check) now drives the
  Terminal's language without a terminal: a pure pipeline, `let` and
  `$var`, `ls` as a job whose listing resumes the pipeline, `write` as a
  replacing job under the working prefix, an unknown word, `cd ..`; and the
  Browser's root folders, descent and ascent.
- `tools/guishell-check.py` seeds the Terminal as the fifth onboard archive
  (eleven tiles, two pages), snapshots with ctrl-P, types `help` into the
  Terminal, then `write /home/t.txt hi` and `cat /home/t.txt`, and expects
  each to change the view.
