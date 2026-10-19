# Clearly

Clearly explains why your code broke, in plain English, and offers a one-line fix you can accept or decline, right in your terminal.

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

1. Shows you why it happened, in plain English
2. Explains what to change
3. Offers to apply a one-line fix. You type `y` to accept or `N` to skip
4. If you accept, it saves a backup of your original as `yourfile.py.bak`, applies the fix, and runs your file again to check it worked

Programs that ask you questions (using `input()`) work normally.

## Good to know

- **The first run can take up to a minute.** Clearly's server sleeps when it's idle and needs a moment to wake up. After that it's fast.
- **How it works:** to explain an error, Clearly sends the error and the code around it to an AI model. Avoid running it on files that contain passwords or API keys.
- **Clearly fixes one line at a time.** If the same mistake appears on several lines (for example a misspelled variable used in more than one place), you may hit more errors after the first fix, and the fix may not be the complete one. Read the explanation, not just the fix.
- **The auto-fix is a suggestion.** For some errors, such as an index that is out of range, Clearly can't know what you meant. Check the fix before you accept it.

## Troubleshooting

- **`clearly` is not recognized:** you probably skipped the restart. Close VS Code completely and open it again. Or run `python -m cli yourfile.py`, which does the same thing.
- **`python` is not recognized (Windows):** use `py` instead, for example `py -m pip install --user pipx`.
- **To update to the newest version:**
```
  pipx install --force https://github.com/oshios-starr/Clearly/archive/refs/heads/main.zip
```

## Feedback

This is an early version, and I'm looking for testers. After you try it, please fill in this 2-minute form:

**[YOUR FORM LINK HERE]**

I want to know:

- Was the explanation correct?
- Was it easy to understand?
- Did the fix work?

Screenshots of anything wrong or confusing are the most useful.

## Status

Early prototype, built by Itsuokor Emmanuel Oshioriamhe(Oshios), 300 level computer Engineering, Covenant University.
