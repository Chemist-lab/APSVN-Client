# APSVN

A simple client for working on Blender files together. Instead of SVN jargon,
a handful of plain actions: **get latest**, **lock a file**, **submit**,
**discard my changes**, **bring back an old version**.

## For the artist

1. Copy the whole `APSVN` folder (desktop, D: drive — anywhere).
2. Run `APSVN.exe`.
3. Sign in once: the studio server's address, your user name and password.
   APSVN shows the projects you may take; tick the ones you need, choose
   **where to put them**, and each project goes into its own folder there,
   named after it (`D:\Projects\Film_2026`).

On any other Subversion server there is no list of projects — *Connect by a
project's address instead* asks for the project's address and its folder,
as before.

Nothing to install — Python and svn live inside the folder.

### Day to day

* **⬇ Get latest** — pick up your team's newest work. Press it every morning.
  If the yellow badge at the top says *N new commits*, that is exactly the
  moment to press it, even when the file list is empty. Afterwards
  **everything** is re-read: the list of changes, the Explorer with every open
  branch of its tree, the project history (the commit you were looking at
  stays selected), your tasks and the task you have open, and the pictures of
  the newest versions. **⟳ Server** at the top does the same without
  downloading anything.
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

### Search

Every tab has a search box at the top (**Ctrl+F** jumps to it, **Esc** clears
it). The rule is the same everywhere: words separated by spaces, each of them
has to be found, capitals do not matter — Cyrillic included.

* **Changes** — narrows the list to the files whose path has the words.
  *Select all* then selects only what you see; anything selected that the
  search hides is counted next to it (*3 selected · 1 not shown by the
  search*), because *Submit* sends everything selected.
* **Explorer** — searches **the whole project**, not just the open folder:
  an asset, a shot, a file name. *new_w* finds the asset's folder and
  *new_w.blend* — not every texture inside the folder, although their paths
  mention it too; *new_w png* finds exactly those pictures. What is found
  stands in the list with the folder it is in, and behaves like any other
  row: pick it, open it, lock it, drag it into Blender. Clicking a folder
  there goes into it. Files that are on the server but not downloaded yet are
  found as well.
* **Project history** — the commits whose note, author or **changed files**
  have the words, with the files that matched under each one: *new_w* finds
  every commit that touched that asset. The last 2000 commits are searched.
* **Tasks** — by task name, type, folder or person.

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
sizes, dates. Opening a folder costs **no network at all**: it is read from the
disk, from a quick local `svn status` of that one folder, and from the last
check with the server — the one APSVN makes every 10 seconds anyway. So a
folder opens instantly, a folder you have already seen opens from memory, and
when fresh data arrives the rows that did not change stay exactly where they
are: nothing blinks, the scroll position stays, the row under the mouse keeps
its highlight. Your own actions (a lock, a move, a file you just saved) show
up at once; a colleague's show up with the next check, the same as in
*Changes*. You can browse even while a big transfer is running.

* **◀ ▶ ▲** — back, forward, one folder up (also Alt+←, Alt+→, Backspace).
* Click selects, **Ctrl**-click adds, **Shift**-click selects a range, Ctrl+A
  selects everything; ↑ ↓ move, Enter opens.
* **Right-click** — open, show in folder, copy path, history, lock or release,
  lock everything inside a folder, the file's page on the studio website.
* **📋 Copy path** (also Ctrl+C) — the full path on this computer, one per
  line for several files: paste it straight into Blender's file browser.
* **Drag onto a folder** — in the list, in the tree, onto the path at the top
  or onto `..` — to **move** it there. It is a real `svn move`: the history
  goes with the file and the server moves its task with it. Nothing reaches
  the server until you submit; the move shows up in *Changes* as one row —
  *moved here · from Shots/* — with **↶ Move back**, which puts it back as if
  nothing happened (anything you changed in the file since stays).
* **Drag out of the window — into Blender, onto the desktop, into Explorer**
  (Windows). The real file is handed over, so Blender opens it, links it or
  appends from it the same way as when you drop it from Explorer. Outside
  APSVN the file is only ever **copied**, never taken away from the project.

APSVN asks before a move only when there is something to say: a folder (all
of it goes), scenes that point at the file and would open without it, or a
file assigned to somebody else.

On the left is a folder tree — click a triangle to expand, click a name to go
there. A blue dot next to a folder means somebody submitted something inside
it; an orange one — you have unsubmitted work in there.

Every row says what svn knows about it: who holds the lock, whether there is
something newer on the server, and whether the file has been downloaded at all.
A folder gets a **new inside** badge when somebody submitted something in it.
(Locks do not bubble up that way — they do not create commits — so a lock is
only visible on the file itself.)

### Locking a whole folder

A folder row shows **🔓 lock folder** when you point at it or select it (it is
also in the right-click menu and in the folder's side panel). Subversion has
no such thing as a lock
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

### Which Blender opens a scene

The studio chooses **one Blender version** for everybody (on the studio
server), and **Lock and open** — any *Open* of a `.blend` — starts exactly
that version on every computer, whatever Windows would pick for `.blend`
there. A project may keep **its own version** (say, a long production that
stays on 4.2 while new ones move to 5.1) — then its scenes open in that one. APSVN finds it by itself: the installer's folders, what the installer
registered, *Programs and Features*.

* If that version is **not installed** on this computer, APSVN says so
  **before** locking anything, and offers **Download Blender 5.1** (its page
  on blender.org) or **Show where it is…** — for a portable copy unpacked
  from a zip; APSVN asks that Blender its version and takes it only if it is
  the studio's. It does not open the scene in another version instead: a
  file saved in a different Blender can lose things.
* If the studio has **not chosen** a version, a `.blend` opens as before —
  in whatever the computer uses for `.blend`. If nothing on the computer
  opens `.blend` files, the newest Blender APSVN can find does.
* **⚙ Settings → 🧊 Blender…** shows the studio's version (and the
  project's own, if it has one), what exactly a scene will open with here,
  and which versions are installed.

The version is remembered, so without the network scenes still open in the
studio's Blender, not in any. A version just changed on the server reaches
APSVN within ten minutes — at once after **Get latest** or **⟳ Server**.

### The studio's look

On the studio server APSVN looks like the studio's own site: the name,
logo and colours the administrator sets in the server's panel (*Theme*).
The top bar takes the studio's background — and so does the window's title
bar on Windows 11 — the main buttons its main colour, links, tabs, frames and
the selection its accent. A **dark** studio background tints the whole frame
(side panel, bars, fields) in the same tone; a light one only the top bar,
since APSVN itself is dark. Without a logo the studio's initials stand in
for it. Nothing set, or reset with *↺* in the panel — APSVN's own look. The
look is remembered, so APSVN starts in it at once and keeps it without the
network.

### What the studio server adds

If the project lives on the studio's own server (svn-native — an address like
`https://svn.example.com/svn/<project>`), APSVN also talks to its `/api/v1`
with the same user name and password. On any other Subversion server none of
this appears, and nothing else changes.

* **Tasks** — a tab listing what is assigned to *you* in this project,
  grouped by what to do about it: *Sent back* (your supervisor asked for
  changes — their note is right there in the task), *In progress*, *To do*,
  *Waiting for review*, and statuses the studio added in Kitsu under *Other
  statuses*; a filter finds one by name, type or folder. From a task:
  **▶ Start working**, **✔ Send to review** (with an optional note for your
  supervisor), **↩ Back to work**, comments, and the files — lock and open,
  show in folder, history, **📂 Open in the Explorer tab**; a task on a
  folder (an asset, a shot) lists the files inside it with an **Open**
  button each, and **🌐 Open in Kitsu** opens the task there. Which status
  buttons appear is decided by the server, by Kitsu's rules — so there are
  no buttons that would only ever be refused. At the top, **🌐 All my
  tasks** opens *My Tasks* in Kitsu and **Project board** the project's
  page in Kitsu (its shots, or its assets if it has no shots).
* **Tasks are yours; the project is everybody's.** The Tasks tab lists only
  your own tasks. The project itself — every folder and every file — is open
  to everybody who is in it, in the Explorer tab, whoever the task is
  assigned to: anything anybody changes is recorded in their name anyway.
  The board of everybody's tasks is in Kitsu (**Project board**).
* **Tasks in the file lists.** A file of *your* task shows its status
  (`📋 Retake`); a file assigned to *someone else* shows their name
  (`📋 taras`), so you know they may be working on it — you can still open
  it. Click either to open the task.
* **Steps in order (shots).** A shot goes through the steps of its process
  one after another — Blocking → Animation → Assembly. A step that waits for
  the one before it to be accepted is not work for now: it stands apart under
  **Coming up**, is not counted on the tab, cannot be moved, and your first
  commit does not start it. Its file shows `📋 Next` while it still belongs to
  the step before. The task's panel shows the whole shot as a strip — who is
  on each step, in what state, which step is yours — so *who am I waiting for
  and who comes after me* has an answer.
* **Studio templates.** New shots start from the files in `/templates` at the
  root of the project (the server copies them when shots are created). The
  Explorer marks that folder, and submitting a change to a template asks
  first: it becomes the start of every shot made after it.
* **Send to review with the submit.** When the files you tick belong to a
  task of yours, a checkbox appears next to *keep my locks*:
  *send “sh010.blend” to review*. Your submit note goes to the supervisor with
  it. There is no “start working” step on submit — the server moves the task
  into work by itself on your first commit.
* **Pictures.** The Explorer shows the server's picture for a file that is not
  downloaded yet; *Project history* shows the files of a commit with their
  pictures; a file's history shows a picture of **every version**, and marks
  the one you have — *you have this version*. If your file is changed but its
  contents match an older version (you brought one back and have not
  submitted it), that is recognised too, by the checksum the server keeps.
* **What a scene uses, and who uses a file.** Pick a `.blend` in the
  Explorer: **which project files it pulls in, by name** — the libraries and
  images it links directly, then what comes through them (*through
  rig_Ruka_01.blend*), each marked if it is newer on the server or not
  downloaded yet; click one to go to it in the Explorer. Also how much is
  packed, what comes live from shared storage (`X:\…` — by studio convention
  that is how it should be, not a mistake), and what is broken (missing,
  wrong letter case, a full path that only works on the author's machine).
  Pick a texture or a library: which scenes use it — click to go there.
* **Deleting something scenes still use** — before the submit, APSVN lists
  the scenes that would open without it and asks.
* **A conflict shows both sides as pictures** — yours and your colleague's —
  before you choose which one to keep.
* **🌐 On the studio website** — the file's page: its previews, history
  and links. Tasks open in Kitsu (above).

#### “These files are assigned to someone else”

The studio server no longer has **soft locks** (tasks moved to Kitsu):
anybody in the project may open, lock and submit any file, and the name on
it is a heads-up, not a barrier. An older server that still has them lets
only the assignee (or a supervisor) lock and submit such a file; everybody
else gets the server's refusal — in a window, word for word as the server
wrote it: whose file it is and who to ask. That is a studio rule, not a
broken network, and APSVN says so rather than “something went wrong”.

### Several projects

The dropdown at the top left switches projects, **＋** adds one. With a
project from the studio server already here, **＋** does not ask for the
password again — it goes straight to the list of projects, with the ones
already on this computer ticked and greyed out. A folder that already
exists and holds something else is never mixed with a project: that project
is skipped, with the reason, and the others are taken. The password is
stored per project, so the same user name on two servers is not a problem.
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

Run `build\package.ps1` — it puts `APSVN-<version>.zip` next to the folder (about 20 MB
compressed, 43 MB unpacked). Everything the artist needs is inside; there is
nothing to install.

```powershell
powershell -ExecutionPolicy Bypass -File build\package.ps1
```

Hand them the ZIP any way you like — a share, Nextcloud, a messenger. They
unpack it wherever they want and run `APSVN.exe`. On first start they fill in
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

### Where things live

Only one file sits in the root, and it is the one to double-click.

```
APSVN.exe      the program
app/           the code
ui/            the interface, and the icons
runtime/       its own Python — nothing is installed on the machine
svn/           its own Subversion
vendor/        third-party Python packages
build/         packaging and the icon generator, never shipped
docs/          this file
tests/
```

The split matters more than it looks. `app/` is the code; everything beside it
is what the code *uses*. A single notion of the root — `desktop.ROOT`, the
folder above `app/` — is where every module finds its neighbours; before it,
each one measured from its own file, and moving the code one level down would
have broken each of those places separately and **silently**: svn “not found”,
the interface not opening, no icon.

The same shape holds inside the macOS bundle: `Contents/Resources` plays the
part of the root, with the code in `Resources/app`.

### What is inside

| Folder / file   | What it is |
|-----------------|------------|
| `app/app.py`    | application logic, the bridge between the interface and svn |
| `app/svn_client.py` | wrapper around `svn.exe` |
| `app/server_api.py` | the studio server's `/api/v1`: tasks, pictures, what a scene uses |
| `ui/`           | the interface (HTML/CSS/JS) |
| `runtime/`      | Python 3.14 embeddable — so nothing has to be installed |
| `runtime-mac/`  | the same idea on macOS: a portable python.org framework, built by `make_runtime_mac.sh` |
| `svn-mac/`      | a portable Subversion for macOS, built by `make_svn_mac.sh` |
| `vendor/`       | pywebview, keyring and their dependencies |
| `svn/`          | SlikSvn 1.14.5 (Subversion CLI, Apache-2.0), the VC++ runtime it needs, its licences |
| `explorer.py`   | the Explorer: one folder at a time |
| `finder.py`     | search: the whole project by name, commits by file, note or author |
| `meter.py`      | the submit progress: a byte meter on the pipe to the server |
| `blender.py`    | which Blender opens a scene: the studio's version, found on this machine |
| `blendthumb.py` | preview embedded in a `.blend` |
| `imgthumb.py`   | previews for png/jpg/tga/exr |
| `tests/`        | 909 checks without a server, up to 26 more (read-only) against the real one |

Settings live in `%APPDATA%\APSVN\config.json`, format 2:
`{"format":2, "projects":[…], "current":"<id>", …mirror of the current one…}`.
The flat `wc`/`url`/`username`/`name` keys duplicate the current project **on
purpose**: this README tells people to copy the APSVN folder, so a studio will
inevitably end up with two builds sharing one `%APPDATA%`, and an older build
that knows nothing about `projects` would wipe the whole list. With the mirror
it only damages the mirror. A `config.json.bak` sits next to it.

The password is in Windows Credential Manager (service `APSVN`).
Startup failures are logged to `%APPDATA%\APSVN\error.log`; quiet background
work — how much the tidy-up of old file copies freed, or that it skipped a
busy copy — to `%APPDATA%\APSVN\apsvn.log` (at most a megabyte, then `.1`).

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
  `tests/exp_stdin_password.py`. SlikSvn 1.14.5 does not list the option in
  its help either (checked 2026-09-28), so on Windows nothing changed with
  the update: the same fallback, and the live checks log in fine.
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
* **The program cannot replace itself while it is running, so it does not
  try.** Windows holds every file that is currently executing — including the
  python running the update. So the order is: download, unpack alongside,
  write a swap script, launch it detached, exit. It waits for us to disappear
  and only then moves the folders. Doing it live gives a half-replaced build
  that does not start at all, which is not an update but the destruction of
  the program.
* **The old folder is renamed, not deleted.** Renaming is instant and
  reversible: if the swap fails, it goes back and the artist is left with the
  old working program rather than none. Settings, passwords and the working
  copy live outside the program folder and are never touched.
* **`DETACHED_PROCESS` is the wrong flag for this, and wrong in the worst
  way.** It leaves the process with no console at all, and a batch file needs
  one — `tasklist` and `ping` do nothing without it. The script would launch,
  do nothing, and the program would close having downloaded everything and
  changed nothing. `CREATE_NO_WINDOW` gives a console that is simply hidden.
  Found by `tests/test_updater.py`, which runs the real swap in a sandbox.
* **The generated script is pure ASCII.** Console codepage cp866 covers
  Russian Cyrillic but has no ‹і›, ‹ї›, ‹є›, ‹ґ›. One Ukrainian comment in
  that file and the update dies at the last step, after everything has been
  downloaded. The explanations live in `updater.py`; the throwaway script gets
  none.
* **The downloaded archive is checked before anything is swapped**: its size
  against what the release declares, that it opens, that it holds the files a build
  holds — in either the old or the new layout, so that moving code around
  never breaks updating for people still on the previous version — and that no entry tries to write
  outside the staging folder. The last one is zip-slip — cheap to check, and
  the cost of missing it is not “no update” but “something overwritten
  elsewhere”.
* **On macOS the thing being replaced is the `.app`, and it is unpacked with
  `ditto`.** Three separate reasons, each of which alone left the update dead
  there. `zipfile` cannot carry a bundle: measured on our own archive, it drops
  the executable bit so the launcher stops being a launcher, turns the symlinks
  inside `Python.framework` into copies, and breaks the signature — and an
  unsigned bundle does not start on Apple Silicon at all. The root of the
  archive is `APSVN.app`, whose own root holds none of the marker files, since
  the code lives in `Contents/Resources` — so the search for it came up empty
  and staging refused the build outright. And what has to be swapped is the
  whole bundle, not the folder the code runs from: its own Python and its own
  svn sit beside the code, so replacing `Contents/Resources` alone would leave
  new code on an old runtime under a broken seal. `desktop.app_bundle()` finds
  the bundle; outside one it answers `None`, which is the ordinary state when
  running from source. Verified by actually updating a real `.app`: the old
  build is gone, the signature is intact, and the program relaunches itself.
* **The list of deleted files is gone from the interface, and its code is
  not.** It was a tab, then a switch inside History, and at each step the same
  doubt: is anyone using it? On the real project it surfaced two leftover
  benchmark files and nothing else — no case of the kind it exists for. Space
  in the interface is paid for every day; an unanswered question is not worth
  that rent.
  What it answered has not gone away, though: *a file is missing and I have no
  idea when it went*. History holds 40 commits and needs you to know which one.
  So `Api.list_deleted()` and `Api.restore_deleted()` stay — working, tested,
  called by nothing. Bringing the screen back is a dozen lines in `ui/app.js`;
  deleting them now would mean writing the same thing twice. There is a comment
  above them saying so, because dead-looking code invites tidying.
* **The Explorer reads no network when you click.** It used to ask the
  server for every folder (`status -u -v --depth immediates`, plus two
  `svn info` calls for the “new inside” badge), so navigating was exactly as
  fast as the network: *Reading folder…*, an empty list, a blink. Now a folder
  is the disk, a local `svn status --depth immediates` of that folder
  (hundredths of a second), and the list from the last check with the server
  — which `state()` fetches for the whole project every 10 seconds anyway.
  One network round per check instead of one per click. What that costs is
  honest and small: a colleague's new lock appears in the Explorer with the
  same delay as in *Changes*. Your own lock appears at once, because it comes
  from the local status. While a transfer runs, the local status is skipped
  too (svn beside svn on the same copy hits its lock, and `_run` would try to
  *repair* it mid-operation); the folder still opens.
* **Rows are keyed, the list is swapped in one go.** The same reconciling as
  in *Changes*: a row whose data did not change survives a refresh as the same
  DOM node. Selection is drawn with classes on the existing rows rather than
  by rebuilding them. A folder already seen is painted from memory at once and
  corrected when the fresh answer arrives; an answer that arrives after the
  artist has already moved on is thrown away.
* **Moving is `svn move`, and both halves travel together.** svn records a
  move as two entries — the new place (`moved-from`) and the old
  (`moved-to`) — and refuses to commit one without the other (E200009,
  *both sides of the move must be committed together*, `tests/exp_move.py`).
  The artist sees one row; `do_commit` adds the other half. `move` accepts no
  `--targets`, so paths go in argv as 8.3 aliases, which svn expands back to
  the real Cyrillic names — both ends exist on disk (we move INTO an existing
  folder, keeping the name), so an alias always exists. A folder svn does not
  know yet is added with `--depth empty` first: moving into it fails
  otherwise (E155010), and its other contents are nobody's business.
* **A moved file whose name no code page can hold still commits.** The
  old place has to be named in `--targets`, and the file is no longer there,
  so there is no 8.3 alias. An empty placeholder brings the alias back — the
  same trick `remove()` uses — and is removed after the commit.
* **Moving back is a true undo.** svn recognises a move back to where the
  file came from and the status becomes clean, as if nothing had happened;
  edits made after the move stay in the file. That is **↶ Move back**.
* **A move needs the server to accept WebDAV `COPY` through its proxy.**
  Submitting a move (or any copy) sends `COPY` with an `https://`
  `Destination`; Apache behind a TLS-terminating proxy sees plain http and
  mod_dav answers **502 Bad Gateway** (*Destination URI refers to different
  scheme or port*) — every other request works, so only moves fail. That is
  fixed on the server (rewrite `Destination` https→http before mod_dav), not
  here; the offline tests use `file://` and cannot see it. APSVN says a
  5xx in plain words — nothing was lost, the move is still waiting — and the
  move can be submitted again once the server is fixed, or undone.
* **“I moved it, a colleague changed it meanwhile” is its own conflict —
  and the usual button would have eaten their work.** The tree conflict lands
  on the old place. `--accept working` (our *keep my file* for tree
  conflicts) marks it resolved and **silently drops the colleague's change**;
  committing the move then deletes the old place, their work included, from
  the server too. `--accept mine-conflict` carries their change into the file
  at the new place. Found by experiment, pinned by `tests/test_move.py`, which
  checks the colleague's bytes end up in the repository. The other way out,
  *put it back*, reverts both halves — and takes the safety copy of the new
  place **first**, because reverting the new half deletes the file together
  with anything edited after the move. The first version took the copy after
  the revert; the test found an empty *Safety copies* folder.
* **Dragging out is Windows' own drag, with two guards.** The pywebview
  window is a WinForms form, so dragging real files out of it is the ordinary
  `DoDragDrop` with `CF_HDROP` — exactly what Explorer offers Blender. The
  effects allowed are **Copy and Link, never Move**: for `CF_HDROP` the
  receiver does the moving, and Explorer on the same drive would take the file
  out of the working copy behind svn's back. And the drag is **not started if
  the mouse button is already up** by the time the request crosses the
  bridge: OLE then does not cancel, it *drops* — wherever the cursor happens
  to be. Rows are not HTML-draggable on Windows, or the web view would start
  its own drag that has nothing to give Blender. Off Windows the page's own
  drag moves files between folders; dragging into Blender needs an AppKit
  drag session with the mouse event in hand, which the bridge no longer has
  — attempting it blind, without a Mac to try it on, risked crashing the app.
* **A file dropped on the window from outside must not replace the app.**
  A web view opens whatever is dropped on it. The page refuses drops
  everywhere except on its own folders.
* **The clipboard goes through the system, not `navigator.clipboard`.** The
  web one wants document focus and permission, and fails silently exactly
  when a menu item was clicked and the menu has already closed.
* **“Whose file is it” is the server's rule, mirrored — so finished tasks are
  read too.** The soft-lock hook decides by the nearest level of tasks: a task
  on the file itself outranks one on the shot folder above — even an accepted
  one, which makes the file nobody's — and on that level only the step whose
  turn it is counts (Blocking, not Animation waiting for it). The marks in the
  lists follow `server_api.owners`, a copy of `tracker.owners`, so that APSVN
  never shows *free* for a file the hook will refuse, or a name on a file
  anybody may submit. That is why the task list carries finished tasks as
  well: without them an accepted task on a file would be invisible, and the
  folder's task above it would wrongly claim the file. The explanation APSVN
  rebuilds when the hook's own text is lost uses the server's newer shape,
  `path — people (Type, Status; …)`, because one file can have two current
  steps.
* **Kitsu's pages are built from the server's links to tasks.** The
  studio website has no task pages any more, and the server does not name
  Kitsu's address in `/v1/` — but every task it sends carries `url`,
  `<kitsu>/productions/<id>/<assets|shots>/tasks/<id>`. APSVN takes Kitsu's
  address and the project's production from those (`server_api.
  kitsu_links`), accepts only links of exactly that shape over http(s), and
  keeps them in the app: the interface still says only *what* to open (a
  task by number, *mine*, *board*). The paths were checked against the
  studio's Kitsu router: *My Tasks* is `/my-tasks` (older Kitsu had
  `/todos`, which this one no longer has), the list of all productions is
  for admins only, so a project without tasks yet opens `/open-productions`
  instead. A server without Kitsu keeps the studio website's pages.
* **Search reads the disk and remembers; it does not ask svn for every
  letter.** The Explorer's search walks the project folder itself
  (`finder.index`, a fraction of a second) instead of `svn list -R` or a
  project-wide `svn status` — those are the network, or seconds on a big
  copy. What svn knows about a found file (changed, whose lock, newer on the
  server, not downloaded yet) comes from the last check with the server, as
  in the Explorer. The walk is remembered for 15 seconds, so typing does not
  walk the project again for every letter. History search takes the last
  2000 commits with their changed paths in one `svn log -v`, remembers them
  for two minutes, and searches in memory. Any long action (Get latest,
  Submit, a move) forgets both — the files and the history may have changed.
  A found file must have one of the words in its own name, not just in its
  path: otherwise the name of an asset would bring up everything inside its
  folder.
* **A scene opens in the studio's Blender, found on each machine — not in
  whatever Windows prefers for `.blend`.** On the administrator's own
  computer (2026-09-27) the per-user default was one version, the
  installer's registration another, and eight versions were installed: every
  artist's machine answers “which Blender?” differently, and a scene saved
  in one version can lose things in another. So the version is the
  studio's, `major.minor` (that is how the installer names its folders; a
  patch release installs over the previous one). Which one applies to a
  project, the server says in `/api/v1/repos/<repo>`: `blender`, and
  `blender_pinned` when it is the project's own (the `altpicture:blender`
  property on the repository root) rather than the studio's. A server
  without that endpoint (404) has only `studio.blender` in `/api/v1/`, and
  that is used then. Any other failure keeps the project's last known
  version and asks again in a minute — falling back to the studio's version
  there would silently open a pinned project's scenes in the wrong Blender.
  `blender.py` finds the version locally without running
  anything: the installer's folders, the ProgIds registered for `.blend`, the
  *Uninstall* entries. A portable copy is taken only after asking it
  `--version`: a folder name proves nothing. The program is chosen **before**
  the lock, so a missing Blender never leaves the artist holding a file
  nothing can open; there is deliberately no “open it in another version
  anyway”. It starts detached, through `blender-launcher.exe` when it is
  there, as Windows itself does — bare `blender.exe` is a console program
  and would bring a black window along. Without a studio version the old
  behaviour stays, except that a computer where nothing opens `.blend`
  (`AssocQueryString` finds no program) gets the newest Blender found rather
  than “Could not open the file” with the file already locked.
* **Signing in once lists the projects; the folders are APSVN's.** The
  studio server says which projects a person may read (`/api/v1/repos`), so
  artists do not copy project addresses from somebody's message. The
  address the person types is reduced to the studio site whatever they
  paste — `svn.studio`, a project's address, a page of the browser — and a
  scheme-less one becomes https, since the password travels with every
  request. The typed password is only checked, and stored (per project, as
  always) only once a project is actually taken; with a studio project
  already here its saved login is reused. Each project goes into
  `<where>\<its name>`: the name is made safe for Windows (`:` → `_`, `CON` →
  `CON_`, `NUL.txt` → `NUL_.txt`), a folder that exists with other things in
  it is refused rather than mixed with the project, and a place inside
  another project is refused before anything is downloaded.
* **The studio's theme is data, not code, and only from its own server.**
  `/api/v1/` → `studio.name` and `studio.theme` (`primary`, `on_primary`,
  `accent_light`, `accent_dark`, `background`, `on_background`, `logo`).
  A colour is taken only as a strict `#rrggbb` (anything else is “not set”),
  and the logo only from a path of the same server's API
  (`…/api/v1/theme/logo?v=…`) — a foreign address would receive the
  password with the request. The logo is fetched once per `?v=` (it changes
  with the picture) and kept as a file; the colours are kept in the project,
  so the next start is in the studio's colours before the server answers.
  APSVN is dark, so it uses `accent_dark`. The colours go into CSS variables;
  the dark greys APSVN used to write out literally (fields, hover, pills,
  side panels) are variables too, so a dark studio background can re-tint
  the whole frame from one colour, while a light one only colours the top
  bar. The title bar: `DwmSetWindowAttribute` (caption and text colour),
  Windows 11 only — elsewhere it stays the system's.
* **Old copies of files are tidied up by themselves — with
  `--vacuum-pristines`, never a plain `cleanup`.** svn keeps the original of
  every version a copy has had in `.svn/pristine`; after a submit or an
  update the new one arrives and the old one stays until a cleanup. The
  server session measured it on the same SlikSvn 1.14.2 (2026-09-28): a
  56 GiB project grew from 112.5 to 157.5 GiB in five working days — 45 GiB
  of old copies, exactly what had changed. A plain `svn cleanup` would clear
  them too, but it also removes the copy's locks, and `svn help cleanup`
  warns that a copy another program is using at that moment can be damaged
  beyond repair. `--vacuum-pristines` only drops unreferenced originals and
  touches no locks: a busy copy is refused (E155004) with nothing broken.
  APSVN runs it after a successful submit or *Get latest*, at start and at
  least once a day — in the background, under the same action lock as any
  short read, never during a transfer, and without `_run`'s retry (which on
  a refusal would run a plain cleanup). It takes a fraction of a second; the
  result goes to `apsvn.log`, and a toast when it freed 100 MB or more. The
  *Repair* button and the E155004 cure stay exactly as they were.
* **The bundled svn is SlikSvn 1.14.5 — at least 1.14.4, because of
  CVE-2024-45720.** Up to 1.14.3 svn.exe on Windows received its command line
  in “ANSI”, and the best-fit conversion turned some Unicode characters into
  quotes, dashes and the like: an argument `a＂ --xml` (a fullwidth quote)
  split into `a` and an injected option `--xml` — shown on the old 1.14.2
  itself, which printed XML. Since 1.14.4 svn splits the command line while
  it is still UTF-16 (`wmain`), so that stays one argument;
  `test_apsvn.py` keeps checking it, and that the bundled svn is ≥ 1.14.4.
  The fix converts each argument to the ANSI code page afterwards, so
  Cyrillic in argv still becomes “?” — file names keep going through a
  `--targets` file, and the few paths that must be in argv (move, cat, copy,
  checkout, relocate, propget) come after `--`, so that a file named
  `-rHEAD.blend` is never read as an option. SlikSvn does not sign its
  packages (neither 1.14.5 nor the 1.14.2 before it); the MSI was read with
  the Windows Installer API first — its administrative sequence runs no
  custom actions — and unpacked with `msiexec /a`, nothing installed. The
  bundle now carries `vcruntime140.dll`, `vcruntime140_1.dll` and
  `msvcp140.dll` from the same package: svn.exe imports them, the old bundle
  relied on the machine having them, and a VS 2022 build with an older
  system `msvcp140.dll` is a known crash. The working-copy format is the same
  across 1.14.x: copies made with 1.14.2 need no upgrade, and the studio
  server runs 1.14.2 as well.
* **What a person may do with a task, the server says — APSVN does not
  guess.** A colleague's task opens from the name on its file, and a
  supervisor may change any task, so guessing would mean buttons that refuse
  or buttons that are missing. The
  Kitsu-era server answers with the statuses this person may set on this
  task (`task.moves`), whether they are a supervisor, and whether they are
  linked to a person in Kitsu at all; APSVN draws exactly those, with Kitsu's
  names — including statuses it does not know itself (*Ready To Start*,
  *Approved*), which is why `task_move` checks only the shape of a status key,
  not a fixed list. Commenting is offered to the assignee and supervisors
  only, as Kitsu allows. An older server that does not send `moves` gets the
  old artist rule, unchanged. Tasks in a status APSVN has no group for used
  to vanish from the list; they now stand under *Other statuses*.
* **Creating shots stays on the website.** The API allowed it for
  supervisors (with a plan-first dry run); the website does it with the
  context it needs, and the Kitsu-era server has moved shot creation to
  Kitsu anyway.
* **The launcher is distlib's, not PyInstaller's.** PyInstaller would give a
  7 MB exe — a whole Python inside a wrapper whose only job is to hand over
  control, a third of the weight of the program itself — and antivirus
  software picks at such files constantly. distlib's launcher ships inside
  every pip: 101 KB, the same bytes that sit behind every installed console
  command, and therefore familiar to scanners. The format is documented and
  trivial: the exe, then `#!path-to-python`, then a zip holding `__main__.py`.
  **The relative path in the shebang works** — established by experiment,
  because everything depended on it: the build is unpacked who-knows-where, so
  an absolute path baked in on the build machine would point at nothing.
* **Icons inside an exe must be DIB, not PNG.** In an `.ico` file PNG is
  accepted anywhere, which makes doing it uniformly tempting. Inside a PE
  resource Windows reads PNG only at 256; everything smaller must be DIB. Our
  icon group was therefore unreadable, the exe showed the launcher's Python
  logo, and **nothing reported an error** — it silently fell back to another
  group.
* **All resources are wiped before ours are written.** Giving our icon group
  the number 1 against the launcher's 101 should have been enough by directory
  order. It was not, again silently. Deleting foreign entries one by one does
  not work either — `UpdateResource` refuses to delete and re-add the same
  name in one pass. Wiping is safe here for a reason worth stating: the
  launcher is a process that lives a fraction of a second and has no window,
  so its manifest and version block do nothing for us.
* **`package.ps1` redraws the icon and rebuilds the exe every time.** Both are
  committed — a clone should be runnable at once — but they are build output,
  and committed build output goes stale in silence. Without those two lines it
  is enough to edit `make_icon.py` and forget to run it for a release to ship
  the old icon, with nothing to notice. They run under the **system** Python,
  not `runtime\python.exe`: the embedded runtime deliberately has no pip, and
  the launcher stub comes from `pip/_vendor/distlib`.
* **The icon is drawn by code, not stored as a file.** A binary icon in a
  repository is something nobody can rebuild or adjust by half a shade without
  the same editor and the same person. `make_icon.py` describes it with
  distance fields, so anyone can change it and git shows the change as a
  change in code. The same drawing produces `apsvn.ico` for Windows,
  `apsvn.icns` for macOS and `ui/icon.png` for the header — drawing them
  separately per platform means they drift apart at the first edit, and nobody
  notices because nobody holds both up side by side.
* **The taskbar icon comes from the window, the Explorer icon from the exe.**
  Two different places, and setting one does nothing for the other: the window
  is drawn by pywebview under `runtime\pythonw.exe`, so without
  `desktop.set_window_icon()` the taskbar would keep showing the Python logo
  next to an APSVN.exe that already looks right.
* **An action waits for the background check instead of refusing.** Every
  10 seconds `state()` asks the server what changed (`svn status -u`, over the
  network) and holds the action lock while it does. The guard used to refuse
  at once when the lock was taken — so *Get latest* pressed during that
  check said *Please wait — the previous action is still running* and did
  nothing, and the artist was left looking at the old state; the same for
  locking or submitting. Now an action waits for a short holder, and still
  refuses straight away when a real transfer is running (`busy`), re-checked
  while waiting in case one starts. Reading a commit's files or a file's
  history takes the lock without claiming to be a transfer, so it cannot make
  *Get latest* refuse either. `tests/test_refresh.py` reproduces the check
  holding the lock for a second, without relying on luck.
* **After *Get latest*, everything that was worked out from the old copy is
  thrown away.** Folders the Explorer remembers, open tree branches, the
  task list, shot data, file versions, and the pictures of the *newest*
  version (pictures of a specific revision never change and are kept). The
  history reloads in place, keeping the selected commit and the scroll.
* **The studio server is an addition, never a dependency.** Everything in
  `server_api.py` fails quietly into “no pictures, no tasks”: another server,
  an old image of ours, no network — APSVN works exactly as before. None of
  its calls takes the lock the long svn actions hold (a picture must not wait
  for a commit to finish), and none runs `svn` while a transfer is going: svn
  beside svn on the same working copy hits its lock, and `_run` would then try
  to *repair* the copy in the middle of somebody else's operation. What the
  server calls need from the copy comes from the last `state()`.
* **The API is looked for only where svn-native promises it.**
  `https://host/svn/<repo>` → `https://host/api/v1/`. Anything else is not
  asked at all: sending a password to an address nobody promised is not
  worth it, even on the same host.
* **Redirects are not followed, and absolute links from a response are not
  fetched.** `urllib` repeats a request to the new address *with the same
  `Authorization` header* — to any host. A server answering 302 to somewhere
  else would have been handed the artist's password. Picture links arrive
  relative and signed (`/api/v1/blobs/…?s=…`) and are fetched only from the
  origin the response came from. `tests/test_server.py` runs a second server
  as a trap and checks nobody came to it.
* **The password rides in every request (Basic), not after a 401.** Half the
  requests; the server remembers a good check for five minutes anyway. A
  refusal is remembered on our side for five minutes too — a wrong password
  repeated every ten seconds looks like guessing, and the server would close
  the door (429) for everything.
* **A scene's dependencies are summarised in Python.** One 1.2 GB scene on the
  real server answers with 181 KB of JSON — mostly packed images one by one.
  The interface gets counts, the broken links and what is newer on the server:
  216 bytes.
* **The last known task list survives a failed refresh.** A “this file is
  taras's” mark that is a minute old is better than the mark vanishing because
  the server hiccuped right after you changed a status. So a change marks the
  list stale instead of forgetting it.
* **A hook's refusal is shown word for word, in a window.** The soft-lock hook
  writes for people — whose file, who to ask — so `humanize()` checks for a
  hook refusal *first*: any rule below it that happened to match a word in the
  text (“locked”, “newer”) would replace the studio's explanation with advice
  about something else. It is also checked *before* the automatic
  cleanup-and-retry, because a hook message may well contain the word
  “cleanup”, and retrying a commit the server deliberately refused is wrong.
  Two things had to be undone on the way to the artist: svn writes a character
  it cannot print as `?\226?\128?\148` (the hook's “—”), and on Windows a hook's
  CRLF comes back as `\r\r\n`, which put a blank line between every two lines
  of the explanation — found by real `pre-commit` and `pre-lock` hooks in
  `tests/test_server.py`, not by the synthetic strings. It arrives as
  `RuleError`; pywebview passes the class name to the interface, which shows
  a window instead of a nine-second toast. When the text is lost on the way (a
  bare 403), the explanation is rebuilt from the tasks APSVN already knows —
  but only for a refusal that looks like a rule, so a colleague's ordinary lock
  is never mislabelled as a task.
* **What to relaunch after an update is read from the NEW build.** It used to
  be a hard-coded `APSVN.bat`; after the code moved into `app/` there is no
  such file, so the swap went through and the relaunch did not — the program
  vanished and Windows complained it could not find `APSVN.bat`.
  `updater.relaunch_target()` looks into the staged build, the same principle
  as recognising its layout.
* **Progress is only shown where it was actually measured.** Downloading one
  version is exact — the size is known in advance and the temporary file can be
  watched. Uploading used not to be: svn prints nothing while sending (the dots
  in “Transmitting file data” come one per 64 MB), its read counters come to
  1.0–4.0× the payload depending on the shape of the change, and the process
  I/O counters do not see network traffic at all (2026-10-02: svn downloaded
  ~17 KB, `OtherTransferCount` showed 7 KB). What svn *writes*, though, turned
  out to be exact — see the next point.
* **The submit bar follows the files, not the network.** While svn sends a
  file it writes that file's new copy into `.svn` (the base for the next
  change) and nothing else of any size, so what the svn process has written is
  how far it has got through the files (`svn_client._io_counts`). Measured
  2026-10-02 — svn 1.14.5, a 400 MB file, a local svnserve, process counters
  every 0.25 s:

  | Submit                          | Read  | **Written** | Over the network |
  |---------------------------------|-------|-------------|------------------|
  | new file                        | 1.00× | **1.00×**   | 1.00×            |
  | a quarter changed, scattered    | 2.00× | **1.00×**   | 0.25×            |
  | changed throughout              | 2.00× | **1.00×**   | 1.00×            |
  | same size, 1 MB changed         | 4.00× | **1.00×**   | 0.00×            |

  and the written bytes grew evenly in time. The last column is why the first
  version of the bar lied: it counted bytes on the network against the files'
  size, and svn sends a changed file only as its difference (compressed, too).
  A real submit of a 6.7 GB scene sent 2.2 GB; the bar sat at *0% · 1.2 MB/s ·
  95m 16s left* while svn went through the parts that had not changed, and the
  submit was over at a third of it. Now the bar reads *Sending — 4.2 GB of
  6.7 GB (63%) · 1m 10s left*, and under it is what actually went over the
  network: *1m 05s so far · 1.4 GB uploaded · 29 MB/s*. The remaining time
  uses the slower of two speeds through the files, over ~1 s and ~8 s. A
  changed file goes fast where svn only compares and at network speed where it
  sends; the short speed catches a slowdown at once, and the long one keeps a
  fast stretch from promising too much. The estimate appears after 3 s, not
  from the first random samples. A simulation of that submit (1 GB, two thirds
  barely changed, a network capped at 30 MB/s, 16 s in all): the old bar said
  *0% · 59m left* for five seconds and stopped at 31%; the new one was at 66%
  by 3.7 s, its estimate was within a second of the truth from 8 s on, and it
  ended at the end. The total counts only what svn goes through: added,
  changed and replaced files. A deleted file still lies on disk until the
  submit is done, and it used to inflate the total too. The bar stops at 99%
  until *Committing transaction*, where the rest is the server's. Not on
  `file://`: there svn.exe writes the repository itself as well. On a Mac,
  which has no process counters, the bar counts bytes on the network as
  before. Every submit of 64 MB or more leaves a line in `apsvn.log`, so
  real submits keep checking the measurement: *submit r41: 6.7 GB in 1m 40s;
  svn went through 6.7 GB (1.00x); uploaded 2.2 GB*.
* **What goes over the network is counted by a tunnel.** For the duration of
  a submit APSVN opens a CONNECT tunnel on `127.0.0.1` (`app/meter.py`) and
  tells svn to go through it with its own option, for that one command only
  (`servers:global:http-proxy-*`). TLS stays end to end between svn and the
  server — the tunnel moves encrypted bytes and sees neither the files nor the
  password — and it lets through only the project's own server. The cost is
  about 4% of one core per 100 MB/s (3 GiB through the tunnel in 1.4 s);
  traffic does not double — the svn → tunnel leg never leaves the machine.
  **The tunnel is a separate process**, and that is not decoration: the first
  version lived inside the program and gave an artist 1.7 MB/s instead of the
  usual ~20 — Python threads in one process share the GIL, and after every
  chunk (a TLS record, up to 16 KB) the tunnel waited its turn behind the
  window and its bridge. Measured: the same tunnel next to one busy Python
  thread did 6.7 MB/s instead of 2 GB/s; as its own process, 2.5 GB/s with the
  same busy thread. On the live server, four interleaved runs: 157 MB/s
  direct, 183 through the tunnel — noise, not a loss. The program only reads
  its “so much has gone” lines a few times a second; a failure is judged
  after the tunnel is stopped and its last numbers read, never from a report
  that has not arrived yet. Only for https; a tunnel that cannot open means a
  submit straight to the server, as before. And if svn did not reach the
  server through the tunnel at all (no tunnel opened — no transaction
  started), the submit is retried directly and that goes to `apsvn.log`; once
  the tunnel did reach the server, an error is a real one and is reported,
  never retried.

### Updating itself

**⚙ Settings → ⬆ Check for updates.** APSVN also looks once, quietly, three
seconds after it starts — if there is nothing new the artist never finds out
it looked. When there is, a dot appears on the Settings button and the menu
item reads *Update to 1.1.0*. No pop-up interrupts the work: a program that
nags about updates teaches people to close its windows without reading them.

Publishing a new version is: bump `VERSION` in `app/app.py`, run
`build\package.ps1`,
create a release on GitHub tagged `v<VERSION>` and attach the zip. The client
reads `/releases/latest`, needs no authentication while the repository is
public, and picks the asset for the system it is running on (`-mac.zip` or
not).

**1.0.0 cannot update itself to 1.1.0 or later.** It checks a downloaded build
against its own idea of what a build looks like — `app.py` and
`svn_client.py` in the root — and since 1.1.0 the code lives in `app/`, so
1.0.0 answers “this does not look like APSVN” and keeps running as it was.
Nothing breaks; those installs have to be replaced by hand once (settings and
passwords live outside the folder and survive). From 1.1.0 on the check
accepts either layout, so the next move of the code will not cut anybody off.

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
./make_svn_mac.sh       # once — builds the portable svn into svn-mac/
./package_mac.sh
```

It has been run — built on macOS 27 (Apple Silicon) against Python 3.14 and svn
1.14.5 from Homebrew. The window comes up, the WKWebView bridge works, and icons
come from the system.

The part that actually matters was checked somewhere else, because a build
machine cannot prove it: the zip was opened on **a second Mac with neither
`python3` nor `svn` installed** — not even Apple's 3.9 stub, so the Command Line
Tools were absent too — and the app started. There was nothing there to fall back
on: had the framework not relocated, the launcher would have found no candidate
and said so in a dialog instead. So the `.app` carries its own Python, and the
artist installs nothing, exactly as on Windows.

Nothing was wrong with the *logic*; everything that broke broke at the seam
between the code and the system, and the git history has each one.

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

#### The svn inside the bundle

`make_svn_mac.sh` does for `svn` what `make_runtime_mac.sh` does for Python, and
it matters more here: macOS has not shipped `svn` since Xcode 11, so on a clean
machine there is nothing to borrow at all. It copies `svn` and `svnadmin`, walks
the dependency closure (22 libraries, 10 MB), rewrites every absolute path to
`@executable_path`/`@loader_path` and re-signs. 11 MB in total.

One thing there is not obvious and would have shipped broken. **OpenSSL looks for
its root certificates at a compiled-in absolute path** — for the Homebrew build,
`/opt/homebrew/etc/openssl@3/cert.pem`, which does not exist on the artist's
machine. Everything else looks perfect: `svn --version` lists `https`, serf is
present, the binary has no absolute references left — and then every single
network action fails with `E230001: issuer is not trusted`. So `cert.pem` is
copied next to the bundled `svn`, and `svn_client` points `SSL_CERT_FILE` at it —
with `setdefault`, because a studio that has set its own (a corporate CA on a
proxy is a real thing) must win over ours. Verified both ways: without the file
the handshake fails, with it the connection reaches the server and stops at
authentication, which is the correct answer for a request carrying no password.

Nothing is left unsolved on macOS now, apart from notarisation — and that is a
decision, not a gap.

### Tests

Without a server — 889 checks against a temporary `file://` repository (and,
for the studio server, a fake one on `127.0.0.1`); they leave nothing behind:

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
  nested folder, searching the history by file, note and author;
* `test_projects.py` — several projects: config migration, per-project
  passwords, switching, removing from the list, a corrupted config;
* `test_progress.py` — progress events, honest percentages, estimated time;
* `test_folders.py` — a dropped folder full of files;
* `test_explorer.py` — the Explorer: paths, locks, what may be launched,
  escaping the project folder, thumbnails, searching the whole project.
* `test_conflicts.py` — all four kinds of conflict: that each one is
  visible, that the old buttons could not resolve the tree ones, that the
  new ones do, that a rescue copy is taken first, and that none of them
  can be submitted;
* `test_updater.py` — updating: version comparison (1.10 is newer than
  1.9), which asset belongs to which system, a truncated download, a
  foreign or zip-slip archive, and **the folder swap run for real** in a
  sandbox — real script, real renames, real relaunch;
* `test_desktop.py` — the platform layer: that `no_window()` cannot hand
  Popen a Windows-only flag on POSIX, where settings live on each system,
  the AppleScript escaping, and that the macOS icon branch imports and
  returns nothing rather than raising;
* `test_icons.py` — file-type icons: Blender, Unreal (whose extensions
  Windows does not know), folders, junk input, the cache;
* `test_incoming.py` — what “Get latest” will bring: your own commit does
  not make you “behind”, a colleague's additions, edits and deletions do.
* `test_blender.py` — versions as the studio, the installer and Blender
  write them, finding the one needed (installed, shown by hand, missing),
  starting it detached through the launcher, and what this machine has;
* `test_tidy.py` — `.svn/pristine` growing with every submit of a big file
  and back to the size of the files after the tidy-up; a copy locked by
  “another program” refused quietly with its lock intact; never a plain
  `cleanup`; tidied after a submit, an update, at start and daily, never
  during a transfer;
* `test_meter.py` — the submit byte meter: exact counts both ways, a reply
  after the end of writing, nowhere but the project's server, several tunnels
  at once, stopping; percent, speed and remaining time from it; https only;
  a submit that did not reach the server through it goes directly, one that
  did is never retried;
* `test_refresh.py` — *Get latest* pressed while the background check holds
  the lock waits and succeeds, a second action during a real transfer is
  still refused at once, reading history is not a transfer, and an update
  marks everything derived from the old copy as stale;
* `test_move.py` — moving: one row for the artist and both halves for svn,
  a U+02BC name, `@` in a name, moving back, into a folder svn does not know
  yet, a whole folder, a file somebody else holds, a file you hold, the
  colleague who changed the file while you were moving it (their bytes must
  end up on the server), the Explorer without network, the drag guard with
  the mouse button up, and copying a path;
* `test_server.py` — the studio server, against a fake one answering in the
  same shapes as the real `api_app.py`: where the API is looked for, paths in
  a copy taken from `/trunk`, which tasks cover a file (and that `sh01` does
  not cover `sh010.blend`), 401/403/404/429 in plain words, a redirect and an
  absolute link that must not take the password anywhere (a trap server
  counts visitors), pictures and their cache, the SHA-1 of a local file found
  among the versions, dependencies summarised, the delete warning,
  **real `pre-commit` and `pre-lock` hooks** refusing and their text reaching
  the artist intact, and both sides of a real conflict as pictures.

With a real server — up to 24 more checks, read-only (the ones about pictures,
shots and scene dependencies run only when the project and the server have
them); they take the connection from
`%APPDATA%\APSVN` (and are skipped without it). **These are the ones that catch
broken authentication:** a `file://` repository needs no password at all, so
none of the other suites would ever notice.

```bash
runtime\python.exe tests\test_live.py
```

`test_live_write.py` runs a full cycle that writes to the repository and cleans
up after itself; enable it deliberately with `set APSVN_LIVE_WRITE=1`.

Experiments (not tests — run them if you ever touch encodings, deletion,
moving or progress): `exp_encoding.py` — what `svn.exe` actually accepts on
this machine; `exp_delete.py` — why deletion needs `--keep-local`;
`exp_move.py` — what `svn status` says about a move, that its halves only
commit together, the placeholder for an unrepresentable name, moving back.
