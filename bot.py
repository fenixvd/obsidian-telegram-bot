#!/usr/bin/env python3
"""Obsidian Telegram bot — see README.md"""
import logging
import os
import pathlib
import random
import re
import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime, date, timedelta

import requests
import yaml

VAULT = pathlib.Path(os.environ.get("VAULT", "/vault"))
STATE = pathlib.Path(os.environ.get("STATE_DIR", "/state"))
TOKEN = os.environ.get("BOT_TOKEN", "")
ALLOWED = {int(x) for x in re.split(r"[,\s]+", os.environ.get("ALLOWED_CHATS", "")) if x.strip()}
CFG_PATH = pathlib.Path(os.environ.get("CONFIG", "/app/config.yml"))

API = "https://api.telegram.org/bot%s" % TOKEN
FILE_API = "https://api.telegram.org/file/bot%s" % TOKEN
STARTED = time.time()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%d-%m-%Y %H:%M:%S")
log = logging.getLogger("obsidian-bot")

CFG = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}
ROUTES = CFG.get("routes") or {}
ATTACH = CFG.get("attachments") or {}
DAILY = CFG.get("daily") or {}
FORWARD = CFG.get("forward") or {}
CLIPPING = CFG.get("clipping") or {}
STRANGERS = CFG.get("strangers") or {}

MSG = {
    "help_head": ("<b>Obsidian bot</b> — notes straight into your vault.\n"
                  "Runs in Docker next to the vault, so Obsidian may stay closed."),
    "help_send": ("<b>Just send me:</b>\n"
                  "• a forwarded post → <code>{forward}</code>\n"
                  "• a link → <code>{clipping}</code>, I extract the readable text\n"
                  "• any text → a line in today's journal note\n"
                  "• a photo or file → lands in attachments and gets embedded"),
    "help_templates": "<b>Note from a template:</b>\n<code>/new</code> — pick from a list",
    "help_tail": ("<b>Everything else:</b>\n"
                  "<code>/note text</code> — into today's journal\n"
                  "<code>/task text</code> — as an unchecked task\n"
                  "<code>/clip url</code> — force-save as an article\n"
                  "<code>/today</code> — today's journal note\n"
                  "<code>/todo</code> — every open task in the vault\n"
                  "<code>/find query</code> — search the vault\n"
                  "<code>/read name</code> — read a note right here\n"
                  "<code>/status</code> — what's in the vault\n"
                  "<code>/cancel</code> — forget what I'm waiting for"),
    "pick_template": "Which template?",
    "ask_title": "{ask} — send it in the next message.",
    "saved": "{what}: <b>{title}</b>\n<code>{path}</code>\n\n<a href=\"{link}\">open in Obsidian</a>",
    "saved_note": "Note",
    "saved_inbox": "In the inbox",
    "saved_article": ("Article: <b>{title}</b>\n{host} · {size} characters\n<code>{path}</code>\n\n"
                      "<a href=\"{link}\">open in Obsidian</a>"),
    "saved_quick": "{what} for {date}\n<code>{path}</code>\n\n<a href=\"{link}\">open</a>",
    "quick_thought": "Journal line",
    "quick_task": "Task",
    "fetching": "Fetching the article…",
    "no_template": "No such template in the vault: <code>{template}</code>.",
    "no_note": "Found no note called «{query}».",
    "nothing_found": "Nothing for «{query}».",
    "unknown_cmd": "Don't know <code>/{cmd}</code>. Try /help.",
    "cancelled": "Fine, dropped it.",
    "confused": "Not sure what to do with this. /help",
    "crashed": "I tripped: <code>{error}</code>",
    "usage": "<code>{example}</code>",
    "extract_failed": ("> [!warning] No readable text\n"
                       "> The page returned nothing usable — open the original instead.\n"),
    "extract_failed_body": "**The message said:**",
    "stranger_notice": ("A stranger knocked on the bot\n<b>{name}</b> · {nick} · "
                        "id <code>{chat}</code>{text}"),
    "status": ("<b>Obsidian bot</b>\n\nNotes: <b>{count}</b>\nPer folder: {folders}\n"
               "Free on disk: {free:.0f} GB\nUp for: {uptime}\n\n<b>Recently touched:</b>\n{recent}"),
    "tasks_head": "Open tasks: <b>{total}</b> across {files} notes",
    "tasks_none": "No open tasks.",
    "tasks_more": "  <i>…{n} more</i>",
    "search_head": "<b>{query}</b> — {total} hits ({names} by name)",
    "read_head": "<b>{title}</b>\n<code>{path}</code>",
    "read_more": "<i>{n} more similar</i>",
    "read_cut": "\n…truncated",
    "forward_no_text": "_no text_",
    "forward_links_head": "## Links from the post",
    "forward_source_dm": "a direct message",
    "stranger_default": ["Wrong door.", "We don't know each other.", "No."],
}
MSG.update(CFG.get("messages") or {})


def t(key, **kw):
    v = MSG.get(key, key)
    return v.format(**kw) if kw else v


MONTHS = {
    "en": (["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"],
           ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]),
    "ru": (["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
            "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"],
           ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]),
}
MONTH_FULL, MONTH_SHORT = MONTHS.get(CFG.get("locale", "en"), MONTHS["en"])

_MOMENT = [
    ("YYYY", lambda d: "%04d" % d.year),
    ("gggg", lambda d: "%04d" % d.isocalendar()[0]),
    ("MMMM", lambda d: MONTH_FULL[d.month - 1]),
    ("MMM", lambda d: MONTH_SHORT[d.month - 1]),
    ("SSS", lambda d: "%03d" % (d.microsecond // 1000)),
    ("YY", lambda d: "%02d" % (d.year % 100)),
    ("MM", lambda d: "%02d" % d.month),
    ("DD", lambda d: "%02d" % d.day),
    ("HH", lambda d: "%02d" % d.hour),
    ("mm", lambda d: "%02d" % d.minute),
    ("ss", lambda d: "%02d" % d.second),
    ("ww", lambda d: "%02d" % d.isocalendar()[1]),
    ("M", lambda d: str(d.month)),
    ("D", lambda d: str(d.day)),
    ("H", lambda d: str(d.hour)),
    ("w", lambda d: str(d.isocalendar()[1])),
]


def moment(fmt, dt=None):
    dt = dt or datetime.now()
    out, i = [], 0
    while i < len(fmt):
        if fmt[i] == "[":
            j = fmt.find("]", i)
            if j == -1:
                out.append(fmt[i]); i += 1; continue
            out.append(fmt[i + 1:j]); i = j + 1; continue
        for tok, fn in _MOMENT:
            if fmt.startswith(tok, i):
                out.append(fn(dt)); i += len(tok); break
        else:
            out.append(fmt[i]); i += 1
    return "".join(out)


TP_RE = re.compile(r"<%\s*(.*?)\s*%>", re.S)


def render_templater(text, title, dt=None):
    dt = dt or datetime.now()

    def sub(m):
        expr = m.group(1)
        if "tp.file.title" in expr:
            return title
        mm = re.search(r'tp\.date\.now\(\s*["\']([^"\']*)["\']', expr)
        if mm:
            return moment(mm.group(1), dt)
        return ""

    return TP_RE.sub(sub, text)


def fill(text, values):
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(values.get(m.group(1), "")), text)


FORBIDDEN = re.compile(r'[*?"<>#^\[\]]')
SEPARATORS = re.compile(r"[\\/:|]")


def safe_name(s, limit=80):
    s = unicodedata.normalize("NFC", s or "")
    s = SEPARATORS.sub(" ", s)
    s = FORBIDDEN.sub("", s).replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:limit].strip() or "Untitled"


def unique(path):
    if not path.exists():
        return path
    for n in range(2, 100):
        p = path.with_name("%s (%d)%s" % (path.stem, n, path.suffix))
        if not p.exists():
            return p
    return path.with_name("%s-%s%s" % (path.stem, int(time.time()), path.suffix))


def obsidian_link(path):
    return "obsidian://open?vault=%s&file=%s" % (
        urllib.parse.quote(CFG.get("vault_name", VAULT.name)),
        urllib.parse.quote(str(path.relative_to(VAULT))))


def write_note(folder, title, body):
    d = VAULT / folder
    d.mkdir(parents=True, exist_ok=True)
    p = unique(d / (safe_name(title) + ".md"))
    p.write_text(body, encoding="utf-8")
    log.info("note: %s", p.relative_to(VAULT))
    return p


S = requests.Session()


def api(method, **params):
    try:
        r = S.post("%s/%s" % (API, method), json=params, timeout=(10, 70))
        d = r.json()
        if not d.get("ok"):
            log.error("API %s: %s", method, d.get("description"))
        return d
    except Exception as e:
        log.error("API %s failed: %s", method, e)
        return {"ok": False}


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def say(chat, text, keyboard=None, preview=False):
    for chunk in [text[i:i + 3900] for i in range(0, max(len(text), 1), 3900)] or [text]:
        p = dict(chat_id=chat, text=chunk, parse_mode="HTML",
                 link_preview_options={"is_disabled": not preview})
        if keyboard:
            p["reply_markup"] = {"inline_keyboard": keyboard}
        api("sendMessage", **p)


def done(chat, path, what=None):
    say(chat, t("saved", what=what or t("saved_note"), title=esc(path.stem),
                path=esc(str(path.relative_to(VAULT))), link=obsidian_link(path)))


MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
            "video/mp4": "mp4", "audio/ogg": "ogg", "application/pdf": "pdf"}


def download(file_id, prefer_name=None, kind="other"):
    d = api("getFile", file_id=file_id)
    if not d.get("ok"):
        return None
    src = d["result"]["file_path"]
    try:
        r = S.get("%s/%s" % (FILE_API, src), timeout=180)
        r.raise_for_status()
    except Exception as e:
        log.error("attachment download failed: %s", e)
        return None

    folder = VAULT / ATTACH.get(kind, ATTACH.get("other", "Attachments"))
    folder.mkdir(parents=True, exist_ok=True)
    ext = pathlib.PurePath(src).suffix.lstrip(".") or MIME_EXT.get(
        r.headers.get("Content-Type", "").split(";")[0], "bin")
    if prefer_name:
        base = safe_name(pathlib.PurePath(prefer_name).stem, 60)
        ext = pathlib.PurePath(prefer_name).suffix.lstrip(".") or ext
    else:
        base = "tg-%s" % moment("YYYYMMDD-HHmmss")
    p = unique(folder / ("%s.%s" % (base, ext)))
    p.write_bytes(r.content)
    log.info("attachment: %s (%.0f KB)", p.relative_to(VAULT), len(r.content) / 1024)
    return p.name


def collect_media(msg):
    out = []
    if msg.get("photo"):
        big = max(msg["photo"], key=lambda x: x.get("file_size", 0))
        n = download(big["file_id"], kind="photo")
        if n:
            out.append("![[%s]]" % n)
    for key, kind in (("video", "video"), ("animation", "video"), ("voice", "voice"),
                      ("audio", "audio"), ("document", "other")):
        o = msg.get(key)
        if not o:
            continue
        n = download(o["file_id"], o.get("file_name"), kind)
        if n:
            out.append("![[%s]]" % n if (o.get("mime_type") or "").startswith("image/")
                       else "[[%s]]" % n)
    return out


def origin(msg):
    o = msg.get("forward_origin") or {}
    kind = o.get("type")
    if kind == "channel":
        ch = o.get("chat", {})
        name = ch.get("title") or ch.get("username") or "channel"
        link = ("https://t.me/%s/%s" % (ch["username"], o["message_id"])
                if ch.get("username") and o.get("message_id") else "")
        return ("[%s](%s)" % (name, link) if link else name), link, name
    if kind in ("user", "chat"):
        src = o.get("sender_user") or o.get("sender_chat") or {}
        name = (" ".join(x for x in (src.get("first_name"), src.get("last_name")) if x)
                or src.get("title") or src.get("username") or "someone")
        return name, "", name
    if kind == "hidden_user":
        name = o.get("sender_user_name") or "hidden sender"
        return name, "", name
    ch = msg.get("forward_from_chat")
    if ch:
        name = ch.get("title") or "channel"
        link = ("https://t.me/%s/%s" % (ch["username"], msg["forward_from_message_id"])
                if ch.get("username") and msg.get("forward_from_message_id") else "")
        return ("[%s](%s)" % (name, link) if link else name), link, name
    return "", "", ""


def entities_to_md(text, entities):
    if not text:
        return ""
    if not entities:
        return text
    raw = text.encode("utf-16-le")
    n = len(raw) // 2
    opens = [[] for _ in range(n + 1)]
    closes = [[] for _ in range(n + 1)]
    quotes = []

    for e in sorted(entities, key=lambda e: (e.get("offset", 0), -e.get("length", 0))):
        s, l, kind = e.get("offset", 0), e.get("length", 0), e.get("type", "")
        if s < 0 or l <= 0 or s + l > n:
            continue
        o = c = None
        if kind == "bold":
            o = c = "**"
        elif kind == "italic":
            o = c = "*"
        elif kind == "underline":
            o, c = "<u>", "</u>"
        elif kind == "strikethrough":
            o = c = "~~"
        elif kind == "spoiler":
            o = c = "=="
        elif kind == "code":
            o = c = "`"
        elif kind == "pre":
            o, c = "\n```%s\n" % (e.get("language") or ""), "\n```\n"
        elif kind == "text_link":
            o, c = "[", "](%s)" % e.get("url", "")
        elif kind in ("blockquote", "expandable_blockquote"):
            quotes.append((s, s + l))
            o, c = "> ", ""
        if o is None:
            continue
        opens[s].append(o)
        if c:
            closes[s + l].append(c)

    parts = []
    for i in range(n + 1):
        for c in reversed(closes[i]):
            parts.append(c.encode("utf-16-le"))
        for o in opens[i]:
            parts.append(o.encode("utf-16-le"))
        if i < n:
            ch = raw[i * 2:i * 2 + 2]
            if ch == b"\n\x00" and any(s <= i < e for s, e in quotes):
                parts.append("\n> ".encode("utf-16-le"))
            else:
                parts.append(ch)
    return b"".join(parts).decode("utf-16-le", "replace")


URL_RE = re.compile(r"https?://[^\s<>()\[\]«»\"']+")


def first_url(text):
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(".,;:!?") if m else None


def guess_title(text, fallback="Untitled"):
    for line in (text or "").splitlines():
        line = re.sub(r"^[>\s*_#\-•]+", "", line).strip()
        line = re.sub(r"\*\*|__|`|\[|\]\([^)]*\)", "", line)
        line = URL_RE.sub("", line).strip(" —-·|")
        if len(line) >= 3:
            if len(line) > 70:
                cut = line[:70]
                line = cut[:cut.rfind(" ")] if " " in cut else cut
            return line
    return fallback


def tmpl_text(rel):
    if not rel:
        return ""
    p = VAULT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def save_forward(chat, msg, body_md, media):
    human, link, channel = origin(msg)
    title = guess_title(body_md, "Forwarded %s" % moment("DD-MM-YYYY HH:mm"))
    now = datetime.now()

    seen, links = set(), []
    for u in URL_RE.findall(body_md or ""):
        u = u.rstrip(".,;:!?")
        if u not in seen:
            seen.add(u)
            links.append(u)
    links_block = ("%s\n\n%s" % (t("forward_links_head"),
                                 "\n".join("- %s" % u for u in links[:15]))) if links else ""

    base = tmpl_text(FORWARD.get("template")) or "---\ntype: inbox\n---\n\n# {{title}}\n\n{{content}}\n"
    body = fill(render_templater(base, title, now), {
        "title": title,
        "content": body_md or t("forward_no_text"),
        "source": human or t("forward_source_dm"),
        "channel": channel,
        "link": link,
        "date": moment(CFG.get("date_format", "DD-MM-YYYY"), now),
        "time": moment("HH:mm", now),
        "attachments": "\n".join(media),
        "links": links_block,
    })
    done(chat, write_note(FORWARD.get("folder", "Inbox"), title,
                          re.sub(r"\n{4,}", "\n\n\n", body)), t("saved_inbox"))


def save_clipping(chat, url, note_text, media):
    say(chat, t("fetching"))
    content = meta = None
    try:
        import trafilatura
        dl = trafilatura.fetch_url(url)
        if dl:
            content = trafilatura.extract(dl, output_format="markdown", include_links=True,
                                          include_images=True, include_tables=True,
                                          favor_precision=True)
            try:
                meta = trafilatura.extract_metadata(dl)
            except Exception:
                meta = None
    except Exception as e:
        log.warning("extraction failed for %s: %s", url, e)

    host = urllib.parse.urlparse(url).netloc.replace("www.", "")
    title = (getattr(meta, "title", None) or guess_title(note_text, "")
             or "Article from %s" % host)
    excerpt = (getattr(meta, "description", None) or "").strip()
    if not excerpt and content:
        excerpt = re.sub(r"\s+", " ", re.sub(r"[#>*`\[\]]", "", content))[:220].strip() + "…"

    if not content:
        content = t("extract_failed")
        if note_text:
            content += "\n%s\n\n%s" % (t("extract_failed_body"), note_text)
    if media:
        content = "\n".join(media) + "\n\n" + content

    now = datetime.now()
    base = (tmpl_text(CLIPPING.get("template"))
            or "---\ntype: article\nsource: {{link}}\n---\n\n# {{title}}\n\n{{content}}\n")
    body = fill(render_templater(base, title, now), {
        "title": title, "content": content, "link": url, "site": host,
        "author": getattr(meta, "author", None) or "",
        "published": getattr(meta, "date", None) or "",
        "date": moment(CFG.get("date_format", "DD-MM-YYYY"), now),
        "excerpt": excerpt or "—",
    })
    p = write_note(CLIPPING.get("folder", "Clippings"), title, body)
    say(chat, t("saved_article", title=esc(title), host=esc(host), size=len(content),
                path=esc(str(p.relative_to(VAULT))), link=obsidian_link(p)))


def from_template(chat, key, title):
    r = ROUTES[key]
    body = tmpl_text("%s/%s" % (CFG.get("templates_dir", "Templates"), r["template"]))
    if not body:
        say(chat, t("no_template", template=esc(r["template"])))
        return
    body = render_templater(body, title)
    if "# " not in body.split("---")[-1]:
        body += "\n# %s\n" % title
    done(chat, write_note(r["folder"], title, body))


def daily_path(d=None):
    d = d or date.today()
    name = moment(DAILY.get("format", "YYYY-MM-DD"), datetime(d.year, d.month, d.day))
    return VAULT / DAILY.get("folder", "Journal") / (name + ".md")


def ensure_daily(d=None):
    p = daily_path(d)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_templater(tmpl_text(DAILY.get("template")) or "## Notes\n", p.stem),
                     encoding="utf-8")
        log.info("journal note created: %s", p.name)
    return p


def append_under(path, heading, line):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == (heading or "").strip())
    except StopIteration:
        path.write_text(text.rstrip() + "\n\n%s\n\n%s\n" % (heading, line), encoding="utf-8")
        return
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def quick(chat, text, kind="thought"):
    p = ensure_daily()
    if kind == "task":
        append_under(p, DAILY.get("task_heading", "## Tasks"), "- [ ] %s" % text)
        what = t("quick_task")
    else:
        append_under(p, DAILY.get("thought_heading", "## Notes"),
                     "- %s — %s" % (moment("HH:mm"), text))
        what = t("quick_thought")
    say(chat, t("saved_quick", what=what, date=moment(CFG.get("date_format", "DD-MM-YYYY")),
                path=esc(str(p.relative_to(VAULT))), link=obsidian_link(p)))


def all_notes():
    skip = set(CFG.get("skip_folders") or [".obsidian", ".trash", ".git"])
    for p in VAULT.rglob("*.md"):
        if skip & set(p.relative_to(VAULT).parts):
            continue
        yield p


def search(chat, q):
    ql = q.lower()
    by_name, by_text = [], []
    for p in all_notes():
        if ql in p.stem.lower():
            by_name.append((p, ""))
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if ql in line.lower():
                    by_text.append((p, line.strip()[:120]))
                    break
        except OSError:
            pass
    res = by_name[:10] + by_text[:10]
    if not res:
        say(chat, t("nothing_found", query=esc(q)))
        return
    out = [t("search_head", query=esc(q), total=len(by_name) + len(by_text), names=len(by_name)), ""]
    for p, frag in res[:12]:
        out.append("• <a href=\"%s\">%s</a>\n  <i>%s</i>%s"
                   % (obsidian_link(p), esc(p.stem), esc(str(p.parent.relative_to(VAULT))),
                      "\n  " + esc(frag) if frag else ""))
    say(chat, "\n".join(out))


def tasks(chat):
    found = {}
    for p in all_notes():
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = [m.group(1).strip() for m in re.finditer(r"^\s*-\s\[ \]\s+(.+)$", txt, re.M)
                if m.group(1).strip()]
        if hits:
            found[p] = hits
    if not found:
        say(chat, t("tasks_none"))
        return
    out = [t("tasks_head", total=sum(len(v) for v in found.values()), files=len(found)), ""]
    for p, hits in sorted(found.items(), key=lambda kv: -len(kv[1]))[:12]:
        out.append("<a href=\"%s\">%s</a>" % (obsidian_link(p), esc(p.stem)))
        out += ["  - %s" % esc(h[:110]) for h in hits[:4]]
        if len(hits) > 4:
            out.append(t("tasks_more", n=len(hits) - 4))
    say(chat, "\n".join(out))


def read_note(chat, q):
    ql = q.lower()
    cand = [p for p in all_notes() if ql in p.stem.lower()]
    if not cand:
        say(chat, t("no_note", query=esc(q)))
        return
    cand.sort(key=lambda p: (len(p.stem), p.stem.lower() != ql))
    p = cand[0]
    txt = p.read_text(encoding="utf-8", errors="replace")
    head = t("read_head", title=esc(p.stem), path=esc(str(p.relative_to(VAULT))))
    if len(cand) > 1:
        head += "\n" + t("read_more", n=len(cand) - 1)
    say(chat, "%s\n\n<pre>%s</pre>\n\n<a href=\"%s\">open in Obsidian</a>"
        % (head, esc(txt[:3300]) + (t("read_cut") if len(txt) > 3300 else ""), obsidian_link(p)))


def status(chat):
    notes = list(all_notes())
    st = os.statvfs(str(VAULT))
    per = {}
    for p in notes:
        parts = p.relative_to(VAULT).parts
        key = parts[0] if len(parts) > 1 else "root"
        per[key] = per.get(key, 0) + 1
    newest = sorted(notes, key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    say(chat, t("status",
                count=len(notes),
                folders=esc(", ".join("%s %d" % kv for kv in
                                      sorted(per.items(), key=lambda kv: -kv[1])[:6])),
                free=st.f_bavail * st.f_frsize / 1024 ** 3,
                uptime=timedelta(seconds=int(time.time() - STARTED)),
                recent="\n".join("• %s — %s" % (esc(p.stem), moment(
                    "DD-MM-YYYY HH:mm", datetime.fromtimestamp(p.stat().st_mtime)))
                    for p in newest)))


PENDING = {}
ALIASES = {}
for _key, _r in ROUTES.items():
    for _a in (_r.get("aliases") or []):
        ALIASES[str(_a).lower()] = _key
for _a, _target in (CFG.get("aliases") or {}).items():
    ALIASES[str(_a).lower()] = str(_target).lower()

LATIN_CMD = re.compile(r"^[a-z0-9_]{1,32}$")


def help_text():
    rows = "\n".join("<code>/%s …</code> → %s" % (k, r["folder"]) for k, r in ROUTES.items())
    return "\n\n".join(x for x in (
        t("help_head"),
        t("help_send", forward=FORWARD.get("folder", "Inbox"),
          clipping=CLIPPING.get("folder", "Clippings")),
        "%s\n%s" % (t("help_templates"), rows),
        t("help_tail"),
    ) if x)


def keyboard():
    keys, row = [], []
    for k in ROUTES:
        row.append({"text": k, "callback_data": "tpl:%s" % k})
        if len(row) == 3:
            keys.append(row)
            row = []
    if row:
        keys.append(row)
    return keys


def command(chat, cmd, arg, msg):
    cmd = ALIASES.get(cmd, cmd)
    if cmd in ("start", "help"):
        say(chat, help_text())
    elif cmd == "new":
        say(chat, t("pick_template"), keyboard())
    elif cmd in ROUTES:
        if arg:
            from_template(chat, cmd, arg)
        else:
            PENDING[chat] = cmd
            say(chat, t("ask_title", ask=esc(ROUTES[cmd].get("ask", "Title"))))
    elif cmd == "note":
        quick(chat, arg, "thought") if arg else say(chat, t("usage", example="/note text"))
    elif cmd == "task":
        quick(chat, arg, "task") if arg else say(chat, t("usage", example="/task text"))
    elif cmd == "clip":
        u = first_url(arg)
        save_clipping(chat, u, "", []) if u else say(chat, t("usage", example="/clip https://…"))
    elif cmd == "today":
        read_note(chat, ensure_daily().stem)
    elif cmd == "todo":
        tasks(chat)
    elif cmd == "find":
        search(chat, arg) if arg else say(chat, t("usage", example="/find query"))
    elif cmd == "read":
        read_note(chat, arg) if arg else say(chat, t("usage", example="/read note name"))
    elif cmd == "status":
        status(chat)
    elif cmd == "cancel":
        PENDING.pop(chat, None)
        say(chat, t("cancelled"))
    else:
        say(chat, t("unknown_cmd", cmd=esc(cmd)))


STRANGER_SEEN = set()
STRANGER_WHEN = {}


def brush_off(msg):
    chat = msg["chat"]["id"]
    who = msg.get("from") or {}
    name = " ".join(x for x in (who.get("first_name"), who.get("last_name")) if x) or "no name"
    nick = "@%s" % who["username"] if who.get("username") else "no username"
    log.warning("stranger: %s (%s, id %s) brushed off", name, nick, chat)

    replies = STRANGERS.get("replies") or MSG["stranger_default"]
    now = time.time()
    if replies and now - STRANGER_WHEN.get(chat, 0) > STRANGERS.get("cooldown", 600):
        STRANGER_WHEN[chat] = now
        api("sendMessage", chat_id=chat, text=random.choice(replies))

    if STRANGERS.get("notify_owner", True) and chat not in STRANGER_SEEN:
        STRANGER_SEEN.add(chat)
        text = (msg.get("text") or msg.get("caption") or "")[:200]
        for owner in ALLOWED:
            say(owner, t("stranger_notice", name=esc(name), nick=esc(nick), chat=chat,
                         text="\n\n<i>%s</i>" % esc(text) if text else ""))


ALBUMS = {}
ALBUM_WAIT = 3


def is_forward(msg):
    return bool(msg.get("forward_origin") or msg.get("forward_from")
                or msg.get("forward_from_chat"))


def body_of(msg):
    return entities_to_md(msg.get("text") or msg.get("caption") or "",
                          msg.get("entities") or msg.get("caption_entities") or [])


def is_own_link(url):
    return bool(url) and not urllib.parse.urlparse(url).netloc.endswith("t.me")


def handle(msg):
    chat = msg["chat"]["id"]
    if chat not in ALLOWED:
        brush_off(msg)
        return

    plain = msg.get("text") or msg.get("caption") or ""
    m = re.match(r"^/(\w+)(?:@\w+)?(?:\s+([\s\S]*))?$", plain.strip(), re.U)
    if m and not is_forward(msg):
        PENDING.pop(chat, None)
        command(chat, m.group(1).lower(), (m.group(2) or "").strip(), msg)
        return

    if chat in PENDING and plain and not is_forward(msg):
        from_template(chat, PENDING.pop(chat), plain.strip())
        return

    media = collect_media(msg)
    body = body_of(msg)

    if is_forward(msg):
        save_forward(chat, msg, body, media)
    elif is_own_link(first_url(plain)):
        save_clipping(chat, first_url(plain), body, media)
    elif media:
        save_forward(chat, msg, body, media)
    elif body.strip():
        quick(chat, body.strip().replace("\n", " "), "thought")
    else:
        say(chat, t("confused"))


def handle_album(msgs):
    first = next((m for m in msgs if (m.get("caption") or "").strip()), msgs[0])
    chat = first["chat"]["id"]
    if chat not in ALLOWED:
        brush_off(first)
        return
    media = []
    for m in sorted(msgs, key=lambda m: m["message_id"]):
        media += collect_media(m)
    body = body_of(first)
    url = first_url(first.get("caption") or "")
    if not is_forward(first) and is_own_link(url):
        save_clipping(chat, url, body, media)
    else:
        save_forward(chat, first, body, media)


def handle_callback(cb):
    chat = cb["message"]["chat"]["id"]
    api("answerCallbackQuery", callback_query_id=cb["id"])
    if chat not in ALLOWED:
        brush_off(cb["message"])
        return
    data = cb.get("data", "")
    if data.startswith("tpl:") and data[4:] in ROUTES:
        key = data[4:]
        PENDING[chat] = key
        say(chat, t("ask_title", ask=esc(ROUTES[key].get("ask", "Title"))))


def offset_file():
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE / "offset"


def publish_commands():
    menu = [("new", "note from a template"), ("note", "line in today's journal"),
            ("task", "add an open task"), ("today", "today's journal note"),
            ("todo", "all open tasks"), ("find", "search the vault"),
            ("read", "read a note here"), ("clip", "save an article"),
            ("status", "vault summary"), ("help", "what I can do")]
    menu += [(k, "note in %s" % r["folder"]) for k, r in ROUTES.items() if LATIN_CMD.match(k)]
    api("setMyCommands", commands=[{"command": c, "description": d[:256]} for c, d in menu])


def main():
    if not TOKEN:
        log.error("BOT_TOKEN is not set")
        return 1
    if not ALLOWED:
        log.error("ALLOWED_CHATS is empty: refusing to start, the bot would obey anyone")
        return 1
    if not VAULT.is_dir():
        log.error("vault is not mounted at %s", VAULT)
        return 1

    me = api("getMe").get("result", {})
    log.info("@%s up, vault %s, owners: %s", me.get("username"), VAULT,
             ", ".join(str(x) for x in ALLOWED))
    publish_commands()

    off = 0
    try:
        off = int(offset_file().read_text().strip())
    except Exception:
        pass

    while True:
        try:
            d = S.get("%s/getUpdates" % API, params={"offset": off, "timeout": 40},
                      timeout=(10, 60)).json()
        except Exception as e:
            log.warning("getUpdates: %s", e)
            time.sleep(3)
            continue
        if not d.get("ok"):
            log.error("getUpdates refused: %s", d.get("description"))
            time.sleep(5)
            continue

        for upd in d.get("result", []):
            off = upd["update_id"] + 1
            msg = None
            try:
                if "callback_query" in upd:
                    handle_callback(upd["callback_query"])
                    continue
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                gid = msg.get("media_group_id")
                if gid:
                    ALBUMS.setdefault(gid, {"msgs": [], "ts": 0})
                    ALBUMS[gid]["msgs"].append(msg)
                    ALBUMS[gid]["ts"] = time.time()
                    continue
                handle(msg)
            except Exception as e:
                log.exception("update failed: %s", e)
                if msg:
                    try:
                        say(msg["chat"]["id"], t("crashed", error=esc(str(e)[:300])))
                    except Exception:
                        pass

        for gid in [g for g, v in ALBUMS.items() if time.time() - v["ts"] > ALBUM_WAIT]:
            try:
                handle_album(ALBUMS.pop(gid)["msgs"])
            except Exception as e:
                log.exception("album failed: %s", e)

        try:
            offset_file().write_text(str(off))
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main() or 0)
