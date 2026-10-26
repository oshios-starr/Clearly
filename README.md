# Clearly

Clearly explains why your code broke, in plain English, and fixes every problem it finds in one run, after one OK from you, right in your terminal.

It works with **Python** (`.py`) and **Node.js** (`.js`) files.

## Install

You need Python 3.9 or newer. For JavaScript files you also need [Node.js](https://nodejs.org).

You only need to install once. Open your terminal (the VS Code terminal works) and run these two commands, one at a time:

```
python -m pip install --user pipx
python -m pipx ensurepath
```

Now **close VS Code completely and open it again** (a new terminal tab is not enough). Then install Clearly:

```
pipx install https://github.com/oshios-starr/Clearly/archive/refs/heads/main.zip
```

You should see `clearly` listed under the apps that are now available.

## Use

Instead of running your file normally, run it through Clearly:

```
clearly yourfile.py
clearly yourfile.js
```

If your code runs fine, Clearly just shows its output. If it crashes, Clearly:

1. Reads the whole file and lists **every** problem it can find, in the order your program would hit them
2. Explains each one in plain English and shows the exact change
3. Asks you **once**: type `y` to apply all the fixes, `n` to skip them, or `r` to review them one by one. Nothing changes until you say yes
4. Saves a backup of your original as `yourfile.py.bak` (if that name is taken it uses `.2.bak`, `.3.bak` and so on, and never overwrites an older backup), applies the fixes, and runs your file again to check it worked

If fixing one file exposes a crash in another file, Clearly goes round again (up to 3 times) and asks you each time.

Programs that ask you questions (using `input()`) work normally. Clearly runs your file with the same `python` your terminal uses, so packages in your activated virtual environment work.

## Good to know

- **The first run can take up to a minute.** Clearly's server sleeps when it's idle and needs a moment to wake up. After that it's fast. An analysis can take up to 30 seconds.
- **What Clearly sends:** when your script crashes, Clearly sends the error message, the stack trace and the full text of the crashing file (up to about 500 lines; longer files are cut to the part around the crash) to our server and on to an AI provider, so it can look for every problem in one go. Avoid running it on files that contain passwords or API keys.
- **Fixes marked ⚠ are judgment calls.** For example, Clearly may have to guess what an empty list should average to, or what to show when a key is missing. Check those before you rely on them.
- **The AI can miss things or be wrong.** Clearly checks every change against your real file, skips any change that would break your file's syntax, and re-runs your program, but read the explanations, not just the fixes. If something is still wrong after the re-run, run Clearly again.
- **Logic problems are only flagged.** If something looks wrong but wouldn't crash, Clearly tells you about it as a heads-up and doesn't change it.

## Troubleshooting

- **`clearly` is not recognized:** you probably skipped the restart. Close VS Code completely and open it again.
- **`python` is not recognized (Windows):** use `py` instead, for example `py -m pip install --user pipx`.
- **`No module named pip`:** your Python was installed without pip. Run `python -m ensurepip --upgrade`, close VS Code completely, open it again, and repeat the install steps.
- **To update to the newest version:**

```
pipx install --force https://github.com/oshios-starr/Clearly/archive/refs/heads/main.zip
```

- **"Couldn't reach Clearly's server":** check your internet connection and try again in a minute.

## Feedback

This is an early version, and I'm looking for testers. After you try it, please fill in this 2-minute form:

https://docs.google.com/forms/d/e/1FAIpQLSfzl54xCaEZN1eYpaLRwUr_npz_7Z6XDIRgHdVNadTYcFhXWw/viewform?usp=dialog

I want to know:

- Was the explanation correct?
- Was it easy to understand?
- Did the fixes work, and were any of them wrong?

Screenshots of anything wrong or confusing are the most useful.

## Status

Early prototype, built by Itsuokor Emmanuel Oshioriamhe (Oshios), 300 level Computer Engineering, Covenant University.