![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Docker](https://img.shields.io/badge/docker-ready-blue)
![Python](https://img.shields.io/badge/python-3.12-green)

🇬🇧 **English** | 🇷🇺 [Русский](README.md)

# Obsidian Telegram bot

Notes into your Obsidian vault **straight from Telegram**. The bot runs in
Docker next to the vault and writes plain files into it, so it does not need a
running Obsidian — unlike plugins, which only work while the app is open. Phone
in your pocket, Obsidian closed, the note is already in the vault.

```
forward a post     →  a note in your inbox folder, from your own template
send a link        →  the readable text of the page as its own note
send plain text    →  a line in today's journal note
/service Immich    →  a new note from a template in your vault
/find /read /todo  →  search, read and open tasks without leaving the couch
```

No external services: just the Telegram Bot API and files on disk.

---

## What's inside

```
.
├── bot.py                  all the logic, knows nothing about any particular vault
├── config.example.yml      folders, templates, commands, reply texts
├── templates/              example templates — copy them into your vault
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example            token and the list of your own chat ids
└── selftest.py             offline checks, no Telegram needed
```

## How it works

| You send | Where it lands |
|---|---|
| a forwarded post from a channel or chat | `forward.folder`, rendered with `forward.template` |
| a link | `clipping.folder`, readable text extracted by [trafilatura](https://github.com/adbar/trafilatura) |
| plain text | a line in today's journal under `daily.thought_heading` |
| photo, video, voice, file, album | a folder from `attachments`, embedded into the note as `![[...]]` |
| `/<command> Title` | a note from a template into the folder from `routes` |

Telegram formatting is converted to markdown: bold, italic, strikethrough,
spoiler, `code`, fenced blocks with a language, links and blockquotes. Album
attachments are collected into one note instead of five.

Built-in commands: `/new` (pick a template with buttons), `/note`, `/task`,
`/clip`, `/today`, `/todo`, `/find`, `/read`, `/status`, `/cancel`, `/help`.
Your own commands come from `routes`, extra names from `aliases`.

## Quick start

1. Get a token from [@BotFather](https://t.me/BotFather) and find your
   `chat_id` — message the bot and read the log, it reports the id of whoever
   knocked.

2. Put the templates into your vault:

   ```bash
   cp templates/*.md /path/to/vault/Templates/
   ```

3. Configure:

   ```bash
   cp .env.example .env            # BOT_TOKEN and ALLOWED_CHATS
   cp config.example.yml config.yml
   ```

   Add to `.env`:

   ```ini
   VAULT_PATH=/path/to/vault
   TZ=Europe/Moscow
   UID=1000
   GID=1000
   ```

   `UID`/`GID` make the created files belong to you rather than to root.

4. Run it:

   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```

With an empty `ALLOWED_CHATS` the bot **refuses to start** — otherwise it would
obey anyone who found it by name.

## Configuration

`config.yml` is the only place that describes your particular vault.

```yaml
vault_name: MyVault          # for obsidian://open links
locale: en                   # en | ru — month names for MMMM formats
date_format: "DD-MM-YYYY"    # how the bot writes dates in replies and templates

routes:
  service:
    template: service.md     # a file inside the vault's templates_dir
    folder: Infra            # where the note goes
    ask: "Service name"      # what to ask when the command comes with no argument
    aliases: [srv]           # extra names for the command
```

Every reply text can be rewritten without touching the code:

```yaml
messages:
  help_head: "Your own help header."
  saved_note: "Saved"
  confused: "Not sure what to do with this."
```

Brushing off strangers:

```yaml
strangers:
  cooldown: 600              # answer at most once per 10 minutes
  notify_owner: true         # tell the owner who knocked
  replies:
    - "Wrong door."
    - "We don't know each other."
```

## Templates

The bot fills its own `{{...}}` tokens:

| Token | Available in | Holds |
|---|---|---|
| `{{title}}` `{{content}}` `{{date}}` | everywhere | title, body, date |
| `{{source}}` `{{channel}}` `{{link}}` `{{time}}` `{{attachments}}` `{{links}}` | forwards | where it came from, attachments, links from the post |
| `{{site}}` `{{author}}` `{{published}}` `{{excerpt}}` | articles | page metadata |

It also **stands in for Templater**, which is not available inside the
container: `<% tp.file.title %>` and `<% tp.date.now("DD-MM-YYYY") %>` work
(moment.js tokens — `YYYY MM DD HH mm ss`, `MMMM`, `ww`, `gggg`, `[literal]`).
Any other `tp.*` call is stripped so no leftovers end up in the note.

## Checks

```bash
python3 selftest.py
```

30 offline checks: date formats, template rendering, file names, markup
conversion (including offsets around emoji), writing notes and appending into
journal sections. No Telegram, no network.

## What it does not do

- no speech recognition — voice messages are stored as files and embedded;
- never edits or deletes existing notes, it only creates them and appends into
  journal sections;
- no webhooks, long polling only: nothing has to be exposed to the internet.

## License

MIT — see [LICENSE](LICENSE).
