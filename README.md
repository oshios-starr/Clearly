# Clearly

Clearly explains why your code broke, in plain English, and offers a one-line fix you can accept or decline, right in your terminal.

It works with **Python** (`.py`) and **Node.js** (`.js`) files.

## Install

You need Python 3.9 or newer. For JavaScript files you also need [Node.js](https://nodejs.org).

Open your terminal (the VS Code terminal works) and run:

```
pip install https://github.com/oshios-starr/Clearly/archive/refs/heads/main.zip
```

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
4. If you accept, it saves a backup of your original as `yourfile.py.bak`, applies the fix, and re-runs your file to check it worked

If `clearly` isn't recognized after installing, use this instead:

```
python -m cli yourfile.py
```

## Good to know

- **The first run can take up to a minute.** Clearly's server sleeps when it's idle and needs a moment to wake up. After that it's fast.
- - **How it works:** to explain an error, Clearly sends the error and the code around it to an AI model. Avoid running it on files that contain passwords or API keys.
- **The auto-fix is a suggestion.** For some errors, such as an index that is out of range, Clearly can't know what you meant. Read the explanation, and check the fix before you accept it.
- Clearly only fixes the single line where the error happened. It doesn't look at your whole project yet.

## Feedback

This is an early version, and I'm looking for testers. Tell me:

- Was the explanation correct?
- Was it easy to understand?
- Did the fix work?

Screenshots of anything wrong or confusing are the most useful.

## Status

Early prototype, built by Itsuokor Emmanuel (Oshios), 300 level computer Engineering, Covenant University.