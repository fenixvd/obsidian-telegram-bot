#!/usr/bin/env python3
"""Offline checks for the parts that do not touch Telegram."""
import os
import pathlib
import shutil
import sys
import tempfile
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent
TMP = pathlib.Path(tempfile.mkdtemp(prefix="obsidian-bot-test-"))
(TMP / "Templates").mkdir(parents=True)
for f in (ROOT / "templates").glob("*.md"):
    shutil.copy(f, TMP / "Templates" / f.name)

os.environ.update(BOT_TOKEN="test", ALLOWED_CHATS="1", VAULT=str(TMP),
                  STATE_DIR=str(TMP / "state"), CONFIG=str(ROOT / "config.example.yml"))
sys.path.insert(0, str(ROOT))
import bot

FAILED = []


def check(name, got, want):
    ok = got == want
    print("%-44s %s" % (name, "ok" if ok else "FAILED"))
    if not ok:
        print("   want: %r\n   got:  %r" % (want, got))
        FAILED.append(name)


D = datetime(2026, 10, 8, 22, 9, 5)

check("moment DD-MM-YYYY", bot.moment("DD-MM-YYYY", D), "08-10-2026")
check("moment with time", bot.moment("DD-MM-YYYY HH:mm", D), "08-10-2026 22:09")
check("moment literal in brackets", bot.moment("YYYY-[W]ww", D), "2026-W41")
check("moment month name", bot.moment("MMMM YYYY", D), "October 2026")

check("templater title", bot.render_templater("# <% tp.file.title %>", "Hello"), "# Hello")
check("templater date", bot.render_templater('x: <% tp.date.now("DD-MM-YYYY") %>', "t", D),
      "x: 08-10-2026")
check("templater drops unknown call", bot.render_templater("a<% tp.file.cursor() %>b", "t"), "ab")

check("filename keeps words apart", bot.safe_name("Cheatsheet: LVM/RAID [v2] #linux?"),
      "Cheatsheet LVM RAID v2 linux")
check("filename falls back", bot.safe_name("///"), "Untitled")

check("bold", bot.entities_to_md("bold text", [{"type": "bold", "offset": 0, "length": 4}]),
      "**bold** text")
check("link", bot.entities_to_md("see here", [{"type": "text_link", "offset": 4, "length": 4,
                                               "url": "https://example.com"}]),
      "see [here](https://example.com)")
check("code", bot.entities_to_md("run ls now", [{"type": "code", "offset": 4, "length": 2}]),
      "run `ls` now")
check("emoji keeps utf-16 offsets",
      bot.entities_to_md("🔥🔥 bold here", [{"type": "bold", "offset": 5, "length": 4}]),
      "🔥🔥 **bold** here")
check("blockquote marks every line",
      bot.entities_to_md("one\ntwo\nout", [{"type": "blockquote", "offset": 0, "length": 7}]),
      "> one\n> two\nout")
check("nested bold inside quote",
      bot.entities_to_md("a b", [{"type": "blockquote", "offset": 0, "length": 3},
                                 {"type": "bold", "offset": 2, "length": 1}]),
      "> a **b**")

check("url picked up", bot.first_url("text https://example.com/x, rest"),
      "https://example.com/x")
check("no url", bot.first_url("nothing here"), None)
check("title from bold first line",
      bot.guess_title("**Some Title**\n\nbody text"), "Some Title")
check("title skips a bare link",
      bot.guess_title("https://t.me/x/1 Real title follows"), "Real title follows")

check("t() formats", bot.t("ask_title", ask="Name"), "Name — send it in the next message.")
check("fill() drops unknown tokens", bot.fill("{{a}}|{{zzz}}", {"a": "1"}), "1|")

p = bot.write_note("Notes", "Test: note/name", "body")
check("note written", p.exists() and p.read_text() == "body", True)
check("note path", str(p.relative_to(TMP)), "Notes/Test note name.md")
check("second note gets a suffix",
      bot.write_note("Notes", "Test: note/name", "b2").name, "Test note name (2).md")
check("obsidian link", bot.obsidian_link(p), "obsidian://open?vault=MyVault&file=Notes/"
      "Test%20note%20name.md")

d = bot.ensure_daily()
check("journal note created", d.exists(), True)
bot.append_under(d, "## Tasks", "- [ ] first")
bot.append_under(d, "## Tasks", "- [ ] second")
bot.append_under(d, "## Notes", "- a thought")
body = d.read_text()
check("tasks land in their section",
      body.split("## Tasks")[1].split("##")[0].strip(), "- [ ] first\n- [ ] second")
check("thought lands in its section",
      body.split("## Notes")[1].split("##")[0].strip(), "- a thought")
bot.append_under(d, "## Missing heading", "- x")
check("missing heading is appended", "## Missing heading" in d.read_text(), True)

check("routes have templates",
      all((ROOT / "templates" / r["template"]).exists() for r in bot.ROUTES.values()), True)

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILED:
    print("FAILED: %d of them — %s" % (len(FAILED), ", ".join(FAILED)))
    sys.exit(1)
print("all good")
