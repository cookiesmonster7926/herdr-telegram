# herdr-telegram

Get a Telegram message when a coding agent running in [herdr](https://herdr.dev) is waiting for you,
and answer it from your phone with one tap.

[繁體中文說明](README.zh-TW.md)

## What it does

- When an agent in a herdr pane becomes **blocked** (a permission prompt, or a question from Claude
  Code's `AskUserQuestion`), you get a Telegram message that shows the dialog: the question, the
  options, the command it wants to run.
- **Every option is a button.** Tap it and that key is pressed in the agent's pane.
- **Several questions at once, multi-select questions and the final review page** all work: the
  message updates in place as you go (boxes tick, the next question appears) until you submit.
- **Reply to the message** to type a free-text answer ("Type something").
- It is careful:
  - only your own chat can press anything;
  - a key is sent only if the agent still shows the exact dialog from the message;
  - options that loosen permissions for good ("don't ask again", "always allow") are never buttons.

Buttons are built for Claude Code's dialogs (tested with Claude Code 2.1.304 and herdr 0.9.3).
For other agents you still get the notification with the screen text, without buttons.

## Requirements

- macOS with [herdr](https://herdr.dev) 0.9 or later
- [uv](https://docs.astral.sh/uv/) (runs the small Python listener that receives your taps)
- `jq` and `curl` (preinstalled on recent macOS; otherwise `brew install jq`)
- A Telegram account

## Install (macOS)

```sh
git clone https://github.com/cookiesmonster7926/herdr-telegram.git ~/herdr-telegram
cd ~/herdr-telegram
./install.sh
```

The script asks for two things:

1. **A bot token.** In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot` and follow
   the steps. Paste the token it gives you.
2. **A message to your bot.** Open your new bot, press **Start**, then press Enter in the terminal.
   This is how the script finds your chat id.

Then it links the plugin to herdr, saves the settings outside the repo (in
`herdr plugin config-dir herdr-telegram`, readable by you only), starts the listener in the
background (it also starts at login), and sends you a test message. That's it.

- **Update:** `git pull && ./install.sh`
- **Uninstall:** `./install.sh --uninstall` (your settings are kept)
- Keep the folder where it is: the listener runs from it.

## Language

Messages come in **English** or **Traditional Chinese**; `install.sh` asks (English if you just
press Enter). To change it later, write `en` or `zh-TW` into the file `language` in
`herdr plugin config-dir herdr-telegram`, then run `./install.sh` again.

Only the words herdr-telegram adds are translated: the headline ("Waiting for your answer:"), the
"Done with this question →" button and notes such as "Answers submitted". The question, its options
and the command are shown exactly as the agent wrote them, in whatever language it used, and words
drawn by Claude Code itself ("Submit answers", "Yes", "Type something") stay as they are. So an
English setting with a question asked in Chinese shows an English headline over the Chinese question.

## Windows (optional)

Notifications work on Windows too (PowerShell 5.1). The buttons are answered by the listener on your
Mac, which reaches the Windows machine through herdr's remote machines.

1. Clone the repo and link it:
   ```powershell
   git clone https://github.com/cookiesmonster7926/herdr-telegram.git $env:USERPROFILE\herdr-telegram
   herdr plugin link $env:USERPROFILE\herdr-telegram
   ```
2. In the folder printed by `herdr plugin config-dir herdr-telegram`, create a file named `telegram`
   (same bot as on your Mac):
   ```
   <bot token>
   <chat id>
   <optional: name shown at the bottom of messages, e.g. Lab PC>
   <optional: one letter for this machine, default w>
   ```
   Your chat id is the second line of the same file on your Mac. For Chinese messages, also create a
   file `language` there containing `zh-TW`. The two machines may use different languages.
3. On the Mac, make sure `herdr --machine <label> agent list` works for that machine
   (see `herdr machine add`). Then add the machine to the file `machines` in the Mac's
   `herdr plugin config-dir herdr-telegram`, one line per machine:
   ```
   w <herdr machine label>
   ```
   and run `./install.sh` again on the Mac.

## How it works

```
an agent becomes blocked
  └─ herdr on that machine runs the plugin (notify.sh on macOS, notify.ps1 on Windows)
       └─ reads the screen → formats the dialog → sends a Telegram message with buttons
you tap a button or reply
  └─ the listener on your Mac (launchd) receives it
       └─ reads the agent's screen again: still blocked, same dialog, a tappable option → presses keys
          (agents on other machines are reached with herdr --machine)
       └─ still asking (next question, ticked box)? → redraws the same message
          done? → marks the message answered and removes the buttons
```

## Good to know

- Telegram lets only one program read a bot's updates, so run the listener on **one** Mac per bot.
- While that Mac sleeps you still get notifications, but taps are not answered.
- In a multi-select question, a typed answer goes into its free-text row once; to change it, use
  the computer.
- The buttons depend on how Claude Code draws its dialogs. If a new version changes them,
  `tests/capture.py` records fresh screens to update the tests.
- Check the listener: `tail ~/Library/Logs/herdr-telegram.log` (taps are logged, typed text is not).
- Check the plugin ran: `herdr plugin log list`.

## Development

```sh
sh tests/run.sh                                    # dialog.awk against recorded screens
sh tests/install_test.sh                           # a first-time install with stand-ins, nothing real touched
cd listener && uv run --no-project --with pytest pytest -q
python3 tests/mutate.py                            # breaks one rule at a time; all must be caught
sh tests/desktop.sh <ssh-host>                     # same screens through dialog.ps1 on a Windows box
uv run tests/capture.py --help                     # record real Claude Code screens in a private pty
```

`dialog.awk` (macOS) and `dialog.ps1` (Windows) are two implementations of the same formatter and
must produce byte-identical output: the buttons carry a fingerprint of it. Keep both `.ps1` files in
UTF-8 with BOM, or PowerShell 5.1 reads them in the system code page.

## License

[MIT](LICENSE)
