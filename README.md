# APSVN

A simple client for working on Blender files together. Instead of SVN jargon,
a handful of plain actions: **get latest**, **lock a file**, **submit**,
**discard my changes**, **bring back an old version**.

## For the artist

1. Copy the whole `APSVN` folder (desktop, D: drive — anywhere).
2. Run `APSVN.bat`.
3. Fill in once: the project address, a folder on your computer, your user
   name and password.

Nothing to install — Python and svn live inside the folder.

### Day to day

* **⬇ Get latest** — pick up your team's newest work. Press it every morning.
  If the yellow badge at the top says *N new commits*, that is exactly the
  moment to press it, even when the file list is empty.
* **🔓 Lock** — until a file is locked, it sits on disk read-only and Blender
  will not let you save over it. That is on purpose: two animators cannot
  quietly overwrite each other. Press *lock* and the file becomes yours and
  writable.
* **⬆ Submit** — send your work to the team. The file is **released** when you
  submit, which also makes it read-only again — so lock it once more if you
  carry on editing. If you would rather keep your locks, tick **keep my locks**
  next to the Submit button; APSVN remembers that choice.
* **✖ Discard my changes** — throw away what you did since your last submit.
  This cannot be undone.
* **🛠 Repair this project** (under **⚙ Settings**) — if APSVN was closed
  in the middle of a transfer and now complains that the project is busy. Your
  files are not affected.

Blender's temporary copies (`.blend1`, `.blend2` and friends) never show up in
the list and never reach the server.

### How the **Changes** tab is split

This tab is not a file browser — that is **Explorer**. It lists what is
*happening*: what you changed, what you hold, what somebody else holds, what is
about to come down from the server. Four sections, most important first. Click
a heading to fold it away.

* **Needs your decision** — conflicts, a lock somebody took away from you, and
  the nasty one: a file *you have already changed* that somebody else holds.
  That last case looks like ordinary work of yours, but it cannot be submitted,
  and finding that out at the end of a commit is the worst possible moment.
* **Your work** — your changes and the files you hold.
* **Locked by somebody else** — wait until they submit and release.
* **Coming from the team** — click *Get latest* to pick these up.

### When two of you touched the same file

Locks are there so this almost never happens. When it does, the file turns red,
climbs to the top of **Needs your decision**, and a red badge appears in the
header that stays there until it is sorted out — a toast can be missed, this
cannot. Nothing can be submitted while it is unresolved.

There are four kinds, and they need different words, so APSVN says which one
you have:

| The chip says | What actually happened | Your two ways out |
|---|---|---|
| **CONFLICT** | you both edited the same file | *keep my version* / *take my colleague's version* |
| **CONFLICT · moved or deleted** | they deleted or moved the file while you were working on it | *keep my file* (it goes back as a new file) / *take what the team has* (it disappears for you too) |
| **CONFLICT · your file is in the way** | a file of yours, never submitted, is sitting where the team's file should be | *keep my file* / *take what the team has* |
| **CONFLICT · file settings** | only the file's settings clash, the contents are fine | same two |

Whichever you pick, **a copy of the file as it is right now goes to *Safety
copies* first.** That is the only way back, and it is taken before anything is
overwritten.

For a text file there is a third button — **I sorted it out myself**. Use it
only if you opened the file, merged both versions by hand and saved it: it
takes exactly what is on your disk. Without it, *keep my version* would put
back your pre-conflict file and throw the manual merge away.

### Three actions that sound alike — and are not

This is the most dangerous spot in any client like this, so the three are
worded to share no words at all:

| What you want | Button | Where | What happens |
|---|---|---|---|
| “I ruined it today, I want this morning's file back” | **✖ Discard my changes** | on the file row | your unsubmitted work is gone; the file becomes what is on the server |
| “I want the version we submitted on Monday” | **⟲ Bring back this version** | in the file's history | that version becomes the newest one — you still have to submit it |
| “I just want to look at how it was” | **👁 Save a copy…** | in the file's history | nothing changes; the old version is written to a separate file |

The first two are never visible at the same time.

### A single file's history

Click the **file name** in the list and *What happened to …* opens: who did
what, and when. Renames show up too (*back then it was called …*).

If the file has changes you haven't submitted, **⟲ Bring back this version**
stays disabled: submit them or discard them first. Otherwise they would be gone
**for good** — they were never on the server. Before every such action APSVN
still puts a copy of your current file aside; reach it with **🛟 Safety
copies**.

### The Explorer

The **Explorer** tab shows the project the way a file manager would: folders,
sizes, dates. It reads one folder at a time, on demand — on a copy with 2000
files that is 24 KB instead of 505 KB, so it stays quick no matter how large
the project grows.

On the left is a folder tree — click a triangle to expand, click a name to go
there. A blue dot next to a folder means somebody submitted something inside
it. Subfolders are read only when you actually open them, so a project with
thousands of files costs nothing until you look.

Every row says what svn knows about it: who holds the lock, whether there is
something newer on the server, and whether the file has been downloaded at all.
A folder gets a **new inside** badge when somebody submitted something in it.
(Locks do not bubble up that way — they do not create commits — so a lock is
only visible on the file itself.)

### Locking a whole folder

Every folder row has **🔓 lock folder**. Subversion has no such thing as a lock
on a folder — locks only exist for files — so APSVN locks every file inside it,
subfolders included. The dialog shows real numbers taken from the server before
anything happens: how many files are in there, how many are already yours, and
how many somebody else holds.

Files held by a colleague are skipped, and you are told which. This matters:
svn reports the whole operation as failed if even one file is taken, while
still locking all the rest — so a naive client would say “somebody else has
this locked” after quietly handing you a hundred locks. APSVN counts the
result from a fresh reading instead of from svn's exit code.

Clicking the same button when you already hold everything offers to release the
folder instead.

Double-click opens a file. For a `.blend` the offer is **🔓 Lock and open**,
and that order matters: opening first and locking later means working for an
hour in a file you have no right to write to, and losing a colleague's
submitted day at the first save. You can still choose to look at it read-only.

Only known file types open this way — a project folder lives on a network
share, so `.exe`, `.bat`, `.lnk` and friends are never launched from here. Use
**Show in folder** and open them yourself if you trust them.

Picking a file shows it on the right: the preview thumbnail embedded in the
`.blend` (0.7 ms, about 35 KB read even from a gigabyte file), or the picture
itself for `.png` / `.jpg` / `.tga` / `.exr`.

### Project history

Two panes. On the left, the commits: what the note said, who submitted it and
how long ago (*2 days ago* — the exact date is in the tooltip and in the right
pane). Click one and the right pane shows its note in full plus every file it
touched, marked **+** added, **●** changed, **−** deleted, **↻** replaced.

There is deliberately no side-by-side diff. See the note under *Decisions* —
it is not laziness, it is a measured 13 seconds per file.

Tick the files in that list and press **↻ Bring back** to make them what they
were in that commit — one file or thirty at once. A copy of what you have now
goes to *Safety copies* first, and **nothing is sent to the server**: the files
change on your disk and you still have to press *Submit*.

A file that was **deleted** in the commit you are looking at comes back as it
was *just before* it — in that commit itself it no longer exists. The dialog
says so before you agree. Files you have unsubmitted changes in are left alone
and listed by name afterwards, rather than quietly overwritten.

### Deleted files

The **Deleted files** tab shows everything that ever disappeared from the
project and who removed it. **⟲ Bring this file back** returns it together with
its history, not as a brand-new file.

### Several projects

The dropdown at the top left switches projects, **＋** adds one. The password
is stored per project, so the same user name on two servers is not a problem.
A submit note you started typing stays with its own project.

**Remove project from list** (under **⚙ Settings**) takes it out of APSVN only
— files on disk are not touched. If you still hold locks in that project, APSVN warns you: nobody else
can edit those files until you connect again and release them.

If a project folder becomes unavailable (a drive did not connect), APSVN does
**not** throw you into the connect form — it explains what happened and lets
you switch to another project or point at the folder's new place.

### If a colleague has the file locked

The row shows `🔒 name` and the tick box is disabled. This is not an error —
wait until they submit their work and release the file.

### If it says “your lock was removed”

An administrator took your lock away while you were working. Press *get latest*
and lock the file again **before** carrying on — otherwise you will not be able
to submit.

## Giving APSVN to somebody else

Run `package.ps1` — it puts `APSVN.zip` next to the folder (about 20 MB
compressed, 43 MB unpacked). Everything the artist needs is inside; there is
nothing to install.

```powershell
powershell -ExecutionPolicy Bypass -File package.ps1
```

Hand them the ZIP any way you like — a share, Nextcloud, a messenger. They
unpack it wherever they want and run `APSVN.bat`. On first start they fill in
the project address, their **own** user name and password, and a folder for the
files.

Checked, so you do not have to guess:

* a path with spaces, Cyrillic letters and dots works (`…\проба роздачі\APSVN 2.0\`);
* running straight off a network share works too — about 4 seconds to the
  window instead of 2, and everybody must be able to reach the NAS at all times.
  Copying to the local disk is still the better default;
* files marked “came from the internet” (that is what a browser download does)
  still start. If Windows does warn, the fix is right-click the ZIP →
  Properties → **Unblock**, and only then unpack.

**Never copy `%APPDATA%\APSVN`.** That is one person's settings, their saved
passwords and their measured transfer speeds. Everybody gets their own on first
start.

To ship a new version, replace the folder. Settings survive, because they do
not live in it.

## For the administrator

A project address is whatever your server serves over http(s), for example:

```
https://svn.example.com/svn/<project>
```

APSVN does not care which server software is behind it — it speaks to
`svn.exe`, and `svn.exe` speaks to anything Subversion. (This line used to name
one particular server and its `/scm/repo/…` paths; that server had already
moved on, and the address in the README was quietly wrong for weeks. Keep it
generic.)

### What is inside

| Folder / file   | What it is |
|-----------------|------------|
| `app.py`        | application logic, the bridge between the interface and svn |
| `svn_client.py` | wrapper around `svn.exe` |
| `ui/`           | the interface (HTML/CSS/JS) |
| `runtime/`      | Python 3.14 embeddable — so nothing has to be installed |
| `runtime-mac/`  | the same idea on macOS: a portable python.org framework, built by `make_runtime_mac.sh` |
| `vendor/`       | pywebview, keyring and their dependencies |
| `svn/`          | SlikSvn (Subversion CLI, Apache-2.0) |
| `explorer.py`   | the Explorer: one folder at a time |
| `blendthumb.py` | preview embedded in a `.blend` |
| `imgthumb.py`   | previews for png/jpg/tga/exr |
| `tests/`        | 329 checks, 33 of them against a real server |

Settings live in `%APPDATA%\APSVN\config.json`, format 2:
`{"format":2, "projects":[…], "current":"<id>", …mirror of the current one…}`.
The flat `wc`/`url`/`username`/`name` keys duplicate the current project **on
purpose**: this README tells people to copy the APSVN folder, so a studio will
inevitably end up with two builds sharing one `%APPDATA%`, and an older build
that knows nothing about `projects` would wipe the whole list. With the mirror
it only damages the mirror. A `config.json.bak` sits next to it.

The password is in Windows Credential Manager (service `APSVN`).
Startup failures are logged to `%APPDATA%\APSVN\error.log`.

Comments in the source are in Ukrainian on purpose — they carry the reasoning
behind decisions that look odd until you know why.

### Decisions that should not be “simplified”

* **Paths and notes never go into argv.** `svn.exe` is not a Unicode program;
  Windows converts the command line to ANSI and substitutes `?` for anything it
  cannot represent. So paths go through a `--targets` file, the note through
  `-F --encoding UTF-8`, and the project folder through `cwd` plus the target
  `.`. Removing this means silently writing `????????` into the history and
  operating on the wrong files.
* **Releasing the lock on submit is a choice, not a default of ours.** svn does
  it unless `--no-unlock` is passed, and that is what APSVN now does — but be
  aware of the cost: a file with `svn:needs-lock` turns read-only the instant
  it is released, so an artist who submits an intermediate version and keeps
  working gets a refusal at the next Ctrl+S. That is why the toast says so in
  plain words, and why **keep my locks** sits right next to the Submit button.
  The `svn_client.commit()` primitive still defaults to keeping locks; only the
  application layer follows the user's preference.
* **`auto-props` in a private `--config-dir`.** Without `svn:needs-lock` on
  binaries the locks are decorative: the file stays writable for everyone.
* **When we ask the server, the server wins.** No lock on the server means
  there is no lock — even if the local copy still remembers its token.
* **Bringing back a version uses `svn cat`, not `svn merge`.** Established by
  experiment (`tests/exp_delete.py` and the agent reports): `merge` silently
  writes into a read-only file with no lock, and even when a colleague holds
  the lock — the disk is already overwritten and the commit then fails with
  E160037. It also conflicts on every binary that has unsubmitted changes, and
  it does not accept `--targets`. And `merge -c -N` does not go back *to*
  commit N at all — it removes only that one commit, so the artist would get
  the wrong version with no error at all. `svn cat` has no conflict state and,
  without a lock, simply fails safely.
* **Order of steps when bringing a version back: lock → safety copy → stream to
  a temporary file → size check → `os.replace`.** The lock is first for a
  reason: it is what catches an out-of-date folder (W160042) and a stolen lock
  *before* anything touches the disk. The size check against `svn info -r N`
  catches a broken download — otherwise a truncated `.blend` would sit on disk,
  shown by svn as merely “changed”, and somebody would happily submit it.
* **These subcommands do NOT accept `--targets`:** `cat`, `copy`, `list`,
  `propget`, `status`, `merge`. For those a Cyrillic path has to be passed
  either as an 8.3 alias or as a percent-encoded URL. The URL is safer: 8.3 can
  be turned off per volume, and for a deleted file it does not exist at all.
* **Every line in a `--targets` file ends with `@`.** Without it any name
  containing `@` (`render@2x.png` is entirely realistic) broke `commit`,
  `lock`, `add`, `delete` and `revert`: the contents of `--targets` go through
  the same peg-revision parsing as argv.
* **`svn:needs-lock` is set to `yes`, not `*`.** `svn.exe` expands wildcards in
  argv itself (this is not cmd.exe), so `*` turned into a directory listing and
  attached the property to unrelated files.
* **The password in Windows storage is keyed by project (`proj:<id>`), not by
  user name.** Otherwise a second project with the same login overwrote the
  first one's password, and the artist got “that user name or password is not
  right” for days in a project they never touched. The old key (login only)
  stays as a fallback — migration deletes nothing.
* **`svn delete --keep-local`, and we remove the file from disk ourselves.** A
  plain `svn delete` erases the file, and its 8.3 alias goes with it — so a
  name that does not exist in ANSI (the Ukrainian apostrophe `ʼ`, U+02BC) can
  no longer be named in the following commit. Experiment: `tests/exp_delete.py`.
* **The password goes through stdin IF this svn can do it.** SlikSvn 1.14.2
  accepts `--password-from-stdin` but never reads it — and every network action
  fails with “Authentication failed”. So `supports_stdin_password()` asks svn
  itself, and the `--password` fallback is offset by svn's own credential cache
  (encrypted with DPAPI on Windows) so the password sits in argv once rather
  than on every call. **The same probe was blind on macOS, the other way
  round:** svn 1.14.5 from Homebrew hides global options from
  `svn help <subcommand>` — there is not even a line about `--password`, only a
  hint to pass `-v` — so the probe answered “cannot” about a build that can, and
  the password went into argv for nothing. `-v` is therefore added off Windows
  only; the Windows probe is left exactly as it was, because there a wrong
  answer means every network action fails for the artist. That Homebrew's svn
  really does read stdin was established on a live `svnserve` that demands a
  password, not from the help text that had just lied:
  `tests/exp_stdin_password.py`.
* **“You are behind” is a count of files, never a difference of revision
  numbers.** It used to be `HEAD - <working copy revision>`, and it told an
  artist to *get the latest* the moment they finished submitting themselves.
  svn raises the revision of the submitted paths only — the root of the
  working copy stays on the old number, so the difference is >= 1 after almost
  every commit you make. Reproduced in `tests/test_incoming.py`: one commit
  into a fresh checkout leaves the root at r0 while HEAD is r1. What is counted
  now is the incoming changes themselves (`remote_change` from `svn status
  -u`), which is also exactly what “Get latest” is about to download.
* **“Get latest” says what it is about to download.** Updating blind over a
  folder holding half a day of work frightens anyone who has been burnt once,
  so the button opens a list first — file plus *new / updated / removed*. The
  list is capped at 300 entries in `state()` (a big incoming merge is
  thousands, and the interface does not need them); `incoming_n` keeps the full
  number, so the count and the progress total stay honest. Whoever finds the
  dialog tiresome ticks *stop showing me this list* and it never comes back.
* **The state is polled every 10 s, but the list is only redrawn when it
  changed.** The point of polling is that somebody else's lock should appear
  without a manual refresh. The point of the guard is that a redraw every
  10 seconds would jump rows out from under the cursor, close an open menu and
  drop a half-typed comment. Hence the signature over `files`: identical data,
  no redraw — only the selection bar is resynced.
* **When the list *does* change, rows are moved, not rebuilt.** `renderFiles()`
  used to start with `box.innerHTML = ""`, so every refresh threw away up to a
  few thousand live nodes and built them again: the scroll position went back
  to the top, the row under the cursor lost its highlight, and the whole list
  visibly blinked. Now each row carries a key (its path) and a signature (its
  data plus its ticked/expanded state); rows whose signature did not change are
  carried over as the same DOM node, and the whole list is swapped in one
  `replaceChildren()`, so the browser never paints an empty list. `scrollTop`
  is saved and restored around the swap — `replaceChildren` resets it.
* **File-type icons come from Windows, not from our repository.** Two reasons.
  The Blender and Unreal logos belong to other people and shipping them inside
  somebody else's application is not our call; and the system icon is always
  the truthful one — whoever has Blender 3.6 gets the 3.6 icon, and whoever
  has no Blender at all gets an honest grey sheet instead of a promise. It
  needs two sources, because one is not enough: the shell (`SHGetFileInfoW`)
  knows `.blend`, `.psd`, `.fbx`, folders — everything registered in HKCR, but
  **Unreal Engine does not register its own extensions at all** (checked:
  `.uasset`, `.umap`, `.uplugin` are simply absent), so for those the icon is
  pulled out of the `UnrealEditor.exe` that the registry says is installed.
  “The shell knows nothing about this one” is detected by comparing against the
  icon it hands out for a deliberately nonsensical extension.
* **Every ctypes call in `shellicon.py` declares `argtypes`/`restype`.** This
  is not tidiness. Without them ctypes tries to squeeze a handle into a C
  `int`, and the call dies with `OverflowError` exactly when Windows happened
  to hand out a handle above 2^31 — so icons appeared for some extensions and
  not for others, with no pattern to it. `tests/test_icons.py` therefore walks
  thirty extensions in a row: a single one could get lucky.
* **A conflict is read from three XML attributes, not one.** `svn status
  --xml` puts a tree conflict and a property conflict in their *own*
  attributes and leaves something peaceful in `item`. Measured on a live
  repository: a colleague deleting a file you were editing gives
  `item="added" copied="true" tree-conflicted="true"`; your own unversioned
  file standing where an incoming one should go gives `item="deleted"
  tree-conflicted="true"` **while your bytes are still on disk**; clashing
  properties give `item="normal" props="conflicted"`. Reading only `item` —
  which is what this did — meant three conflicts out of four were drawn as
  ordinary green rows, or (for the property one) skipped from the list
  entirely. The artist ticked the row, pressed Submit, was refused, and had no
  button anywhere to fix it. Every kind now reports `status="conflicted"`,
  which switches on every guard that already existed; the raw value is kept in
  `wc_item`, and `conflict_kind` carries the distinction.
* **Obstruction is told apart from the rest by looking at the disk.** svn
  reports it as `deleted`, so APSVN was labelling the artist's own unsaved
  work — possibly open in Blender at that moment — as *deleted*. If the item
  is `deleted`, it is tree-conflicted, and the file is physically there, it is
  an obstruction and is said so.
* **`--accept mine-full` and `theirs-full` DO NOT resolve a tree conflict.**
  Established by experiment, not from the documentation, which is misleading
  here. svn refuses with *“This file has a conflict — choose whose version to
  keep”* — in answer to the choice just made. So the buttons would have been a
  dead end even once the rows became visible. What works: `--accept working`
  to keep yours, plain `revert` to accept the team's. `resolve_conflict()`
  picks per kind; `tests/test_conflicts.py` reproduces the experiment so that
  a future svn changing its mind is caught rather than guessed at.
* **A rescue copy is taken before every destructive resolve.** svn removes the
  `.mine` artefact with the very call that resolves the conflict, so *take my
  colleague's version* used to destroy a day of work with nothing to recover
  it from. The same helper serves “bring back an old version”.
* **`svn:needs-lock` covers what artists actually open, not what is
  technically binary.** `.ma` is plain text, and merging two Maya scenes is
  exactly as impossible as merging two `.blend` files. **Unreal is the one
  that mattered:** without `.uasset`/`.umap` in the list, auto-props attached
  the property to nothing, so locks in a UE project were decorative and two
  people could edit one asset until the first conflict. Note the cost: a
  modified file with one of these extensions now demands a lock before it can
  be submitted.
* **Nothing re-protects an already-connected project, and that is deliberate.**
  auto-props only fire for **newly added** files, and the one-time sweep over
  existing ones runs **only when a project is first connected**. So a project
  connected before an extension joined the list keeps those files unprotected
  for good. There was a sidebar button for this and it was removed: nobody —
  the author of the project included — could tell from the label what it did,
  and a button that has to be explained three times is a bug, not a feature.
  Doing it silently was rejected too: an unannounced commit touching dozens of
  files, after which everybody's copies turn read-only, is not something a tool
  should decide on its own. What makes this safe is the premise that
  **everyone works through APSVN**, so every newly added file gets the property
  from auto-props. Should an old project ever need the sweep, it is a
  deliberate one-off job for whoever runs the server.
* **The sidebar shows two actions; the rest live under ⚙ Settings.** *Open
  folder* and *Safety copies* stay in plain sight because an artist reaches for
  them on their own — and every dangerous dialog in the app promises that a
  copy went to *Safety copies*, so that promise has to be one click away.
  *Repair*, *Change server address* and *Remove project from list* are rare and
  administrative; five flat buttons in a row gave them all the same weight as
  the two that matter daily. The menu opens **upwards** (it sits at the bottom
  of the panel) at `z-index: 20` — below the modal's 50, because *Repair*
  opens a confirmation right after itself and the menu must not sit on top of
  it. The buttons kept their ids, so none of their handlers changed.
* **The commit contents come from `svn log -v`, never from `svn diff`.**
  Measured against the real server: `svn diff -c N` on a single `.blend` takes
  **13.3 seconds** and returns 180 bytes saying *“Cannot display: file marked
  as a binary type”* — svn faithfully pulls both revisions of the file across
  the network and only then admits it cannot show them. In an artist's
  repository nearly everything is binary, so a panel that diffed the selected
  file would hang on every click. `svn log -v --xml -r N` returns the same list
  of paths in **0.10 s and 300 bytes**, and throws in `action`, `kind` and
  `text-mods`/`prop-mods` — so “only the settings changed” is distinguishable
  without a second request. A local `file://` repository would never have shown
  this: there is no network to be slow.
* **The file list is fetched per commit, not for all of them at once.**
  `log -v --limit 20` costs the same 0.12 s as the plain `log`, but 238 KB
  instead of 2.6 KB — half a megabyte across the Python↔webview bridge for
  forty commits of which one gets opened. Per commit it is 300 bytes, cached
  after the first read.
* **500 paths per commit, and the count says how many were really there.** The
  first commit of a real project is one commit with thousands of paths — in
  this user's repository, 2062. Drawing them all is neither possible nor
  useful, so the list stops at 500 and says so in the artist's own terms:
  *“this looks like the commit that first filled the project”*.
* **Bringing a file back reads the working copy's state, not the disk.** Our
  `svn delete` runs with `--keep-local` (otherwise the 8.3 alias goes with the
  file, and a name holding the Ukrainian apostrophe `ʼ` can no longer be
  named in the next commit). So after a delete **the bytes are still on disk**
  while svn no longer knows the path — and “the file is there, so overwrite
  it” walks straight into *svn could not find this file*. Three branches
  instead: svn knows it → `restore_revision`; svn calls it unversioned →
  rescue the stray bytes, remove them, `restore_deleted`; svn has nothing →
  `restore_deleted`. Caught by `tests/test_api.py`, not by reasoning.
* **Off-by-one is the whole game with a deleted file.** Picking a file that was
  deleted in commit N and restoring *N* gets you nothing — it does not exist
  there. `restore_many` subtracts one for `action == "D"`, and the dialog tells
  the artist that is what will happen.
* **One bad file does not sink the batch.** In a pick of thirty there is always
  one with unsubmitted changes; aborting everything because of it is punishment,
  not safety. Each file is attempted on its own, and the ones left alone are
  listed by name with the reason.
* **Progress is only shown where it was actually measured.** Downloading one
  version is exact — the size is known in advance and the temporary file can be
  watched. Uploading is not: svn prints nothing while sending, and its read
  counters come to 1.0–2.0× the payload depending on the shape of the commit,
  so a percentage there would be invented. The remaining time for an upload is
  an estimate from throughput measured on this user's earlier transfers, and it
  is marked `≈`.

### macOS

There is a `.app` build, and **it is not notarised** — that is a deliberate
choice, not an omission. Two things get confused here:

* a `.app` is just a folder with an `Info.plist`. It costs nothing, needs no
  Apple account, and is what gives an icon, a Dock entry and a double-click
  launch. Skipping it saves twenty lines and loses all of that;
* **notarisation** is what costs — a Developer ID at $99 a year. Without it
  macOS holds the app on first launch and the person has to go to *System
  Settings → Privacy & Security → Open Anyway*, once per install. Apple
  removed the old Control-click shortcut, so that is now the only route.

`codesign --sign -` in `package_mac.sh` is a third thing again: an **ad-hoc**
signature, free and accountless. It is not notarisation and Gatekeeper is not
fooled by it — but on Apple Silicon an unsigned binary does not warn, it
simply refuses to start, so the build would be dead without it.

```bash
./make_runtime_mac.sh   # once — builds the portable Python into runtime-mac/
./package_mac.sh
```

It has been run — on macOS 27 (Apple Silicon), Python 3.14, svn 1.14.5 from
Homebrew. The window comes up, the WKWebView bridge works, icons come from the
system, and the packaged `.app` starts from a fresh unpack on a machine that has
no Python of its own. Nothing was wrong with the *logic*; everything that broke
broke at the seam between the code and the system, and the git history has each
one.

#### The Python inside the bundle

`runtime-mac/` is the macOS twin of `runtime/` on Windows, and like it, it is
built rather than committed. `make_runtime_mac.sh` copies the **python.org**
framework — deliberately not Homebrew's, which reaches into `/opt/homebrew` for
its OpenSSL and would drag half of Homebrew along — trims it (CPython's own test
suite alone is 116 MB, and the interface is a WKWebView, so Tk goes too),
rewrites every absolute `install_name` to `@loader_path`/`@executable_path`, and
signs what it changed. 118 MB unpacked, 39 MB zipped, against 43 MB and 20 MB on
Windows.

Three things about it are load-bearing, and all three were paid for:

* **the interpreter lives in `Contents/MacOS`, and that is what gives the app
  its own name.** Borrowing the system Python meant `exec` into a binary inside
  *its* `Python.app`, so LaunchServices credited that bundle: the Dock said
  “Python”, with Python's icon. Nothing else was needed to fix it — the same
  binary, moved inside our own `Contents/MacOS`, registers as
  `cloud.altpicture.apsvn`;
* **`PYTHONHOME` is set explicitly.** The stub comes from `Python.app` inside
  the framework and now sits somewhere else entirely, so the landmarks CPython
  uses to find its own standard library are no longer where it looks. Guessing
  here is pointless when the answer can simply be stated;
* **the standard library's bytecode is hash-based `unchecked`** (PEP 552). Plain
  `.pyc` are validated by timestamp, and `cp -R` rewrites the `.py` timestamps —
  so the moment the framework is copied, the whole library counts as stale.
  Then one of two bad things: Python rewrites the `.pyc` *inside a signed
  bundle* and breaks the seal on the artist's machine, or, with
  `PYTHONDONTWRITEBYTECODE`, recompiles it on every launch. `unchecked-hash` is
  checked against neither, so copying cannot disturb it. Verified: the signature
  survives a run made deliberately without `PYTHONDONTWRITEBYTECODE`.

If `runtime-mac/` is absent the build still works — the launcher falls back to
hunting for a system Python and asks each candidate `import webview, objc,
keyring`, because a version number guesses at what an import answers. That
fallback is what the artist must never reach.

Tests: 445 of the 450 run here. The other five are not skipped for convenience
and nothing is missing — two exercise the Windows icon backend, and three need
Unreal Engine actually installed to have anything to look at.

Still not solved: **svn from Homebrew is not relocatable** as it stands (it links
against `/opt/homebrew/lib/*.dylib`), so the bundle falls back to the system
`svn` and says so during the build. It is the same `install_name_tool` and rpath
work `make_runtime_mac.sh` already does for Python, on a smaller target — the
script is the worked example to copy from.

### Tests

Without a server — 450 checks against a temporary `file://` repository; they
leave nothing behind:

```bash
runtime\python.exe tests\test_apsvn.py
```

* `test_apsvn.py` — Cyrillic in paths and notes, the U+02BC apostrophe,
  automatic `needs-lock`, temporary copies, deletion, discarding changes,
  message translation;
* `test_two_users.py` — a stolen lock and a conflict between two people;
* `test_api.py` — the `Api` layer: exactly what the interface calls;
* `test_history.py` — a file's history with renames, bringing a version back,
  bringing a deleted file back, names containing `@`, recognising a foreign or
  nested folder;
* `test_projects.py` — several projects: config migration, per-project
  passwords, switching, removing from the list, a corrupted config;
* `test_progress.py` — progress events, honest percentages, estimated time;
* `test_folders.py` — a dropped folder full of files;
* `test_explorer.py` — the Explorer: paths, locks, what may be launched,
  escaping the project folder, thumbnails.
* `test_conflicts.py` — all four kinds of conflict: that each one is
  visible, that the old buttons could not resolve the tree ones, that the
  new ones do, that a rescue copy is taken first, and that none of them
  can be submitted;
* `test_desktop.py` — the platform layer: that `no_window()` cannot hand
  Popen a Windows-only flag on POSIX, where settings live on each system,
  the AppleScript escaping, and that the macOS icon branch imports and
  returns nothing rather than raising;
* `test_icons.py` — file-type icons: Blender, Unreal (whose extensions
  Windows does not know), folders, junk input, the cache;
* `test_incoming.py` — what “Get latest” will bring: your own commit does
  not make you “behind”, a colleague's additions, edits and deletions do.

With a real server — 33 more checks; they take the connection from
`%APPDATA%\APSVN` (and are skipped without it). **These are the ones that catch
broken authentication:** a `file://` repository needs no password at all, so
none of the other suites would ever notice.

```bash
runtime\python.exe tests\test_live.py
```

`test_live_write.py` runs a full cycle that writes to the repository and cleans
up after itself; enable it deliberately with `set APSVN_LIVE_WRITE=1`.

Experiments (not tests — run them if you ever touch encodings, deletion or
progress): `exp_encoding.py` — what `svn.exe` actually accepts on this machine;
`exp_delete.py` — why deletion needs `--keep-local`.
