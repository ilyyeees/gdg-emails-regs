#!/usr/bin/env python3
"""Send GDG ENSIA letters: fixed test messages or the validated ACCEPTED Google Sheet."""
import argparse
import csv
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid, parseaddr
import html
import hashlib
import http.client
import io
import sqlite3
import urllib.request
import urllib.error
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import sys
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
RECIPIENT = 'gdg@ensia.edu.dz'
FIRST_NAME = 'Ilyes'
SLUGS = ('events', 'multimedia', 'production', 'mobile-development', 'web-development',
         'relex', 'ui-ux', 'robotics', 'ai', 'graphic-design')

class SafeError(Exception):
    """Errors whose messages contain no credentials or SMTP server response text."""


def credentials(root):
    values = {}
    env_file = root / '.env'
    if env_file.exists():
        for number, raw in enumerate(env_file.read_text(encoding='utf-8').splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if not sep or key not in ('GMAIL_ADDRESS', 'GMAIL_APP_PASSWORD'):
                raise SafeError(f'Invalid .env entry on line {number}; only the two documented keys are allowed.')
            if key in values:
                raise SafeError(f'Duplicate .env key on line {number}.')
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise SafeError(f'Unclosed .env quote on line {number}.')
                value = value[1:-1]
            values[key] = value
    address = os.environ.get('GMAIL_ADDRESS', values.get('GMAIL_ADDRESS', '')).strip()
    password = os.environ.get('GMAIL_APP_PASSWORD', values.get('GMAIL_APP_PASSWORD', '')).replace(' ', '').strip()
    if not address or not password:
        raise SafeError('Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in the root .env file or environment. Nothing sent.')
    if any(c in address for c in '\r\n') or parseaddr(address)[1] != address or not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', address):
        raise SafeError('GMAIL_ADDRESS must be one plain email address. Nothing sent.')
    if any(c in password for c in '\r\n'):
        raise SafeError('GMAIL_APP_PASSWORD must be a single line. Nothing sent.')
    return address, password


def load_groups(path):
    """Validate the ENTIRE mapping locally before any SMTP connection. Never fetch links."""
    try:
        with path.open(newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, strict=True)
            if reader.fieldnames != ['department', 'telegram_url']:
                raise SafeError('Group CSV needs exactly this header: department,telegram_url. Nothing sent.')
            groups = {}
            for number, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise SafeError(f'Invalid group CSV row {number}. Nothing sent.')
                slug = row['department'].strip()
                raw_url = row['telegram_url']
                if any(ord(c) < 32 or ord(c) == 127 for c in raw_url):
                    raise SafeError(f'Invalid Telegram URL on group CSV row {number}. Nothing sent.')
                url = raw_url.strip()
                if slug not in SLUGS or slug in groups:
                    raise SafeError(f'Unknown or duplicate department on group CSV row {number}. Nothing sent.')
                # Reject whitespace/control characters BEFORE URL parsing, which can normalize them.
                if not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
                    raise SafeError(f'Missing or invalid Telegram URL on group CSV row {number}. Nothing sent.')
                parts = urlsplit(url)
                valid_path = re.fullmatch(r'/(?:[A-Za-z][A-Za-z0-9_]{4,31}|\+[A-Za-z0-9_-]{5,}|joinchat/[A-Za-z0-9_-]{5,})/?', parts.path)
                reserved = {'addemoji', 'addlist', 'addstickers', 'addtheme', 'addstyle', 'auction', 'auth', 'boost', 'call', 'confirmphone', 'contact', 'giftcode', 'invoice', 'joinchat', 'login', 'proxy', 'setlanguage', 'share', 'socks'}
                is_phone = parts.path.startswith('/+') and parts.path[2:].rstrip('/').isdigit()
                if parts.path.strip('/').lower() in reserved or is_phone or parts.scheme != 'https' or parts.netloc != 't.me' or parts.query or parts.fragment or not valid_path:
                    raise SafeError(f'Invalid Telegram URL on group CSV row {number}. Use an HTTPS t.me group link. Nothing sent.')
                groups[slug] = url
            missing = set(SLUGS) - groups.keys()
            if missing:
                raise SafeError('Group CSV is missing departments: ' + ', '.join(sorted(missing)) + '. Nothing sent.')
            return groups
    except OSError:
        raise SafeError('Cannot read the group CSV. Copy groups.example.csv to groups.csv and fill all ten links, or use --test --no-group-links for layout testing. Nothing sent.') from None


def render(template, html_mode, department, group_url, first_name=None):
    if first_name is None:
        first_name = FIRST_NAME
    no_links = group_url is None
    if no_links and html_mode:
        # A span has no href, click handler, anchor behavior, or keyboard link focus.
        template, count = re.subn(r'<a href="{{next_step_url}}"([^>]*)>(.*?)</a>',
                                  r'<span\1 aria-disabled="true">\2</span>', template, flags=re.S)
        if count != 1:
            raise SafeError('Expected one Telegram button to disable. Nothing sent.')
    text = ('Layout test only. Telegram links are intentionally disabled.' if no_links
            else f'Join the {department} Telegram group to connect with your team.')
    values = {'first_name': first_name, 'next_step_text': text, 'next_step_url': group_url or ''}
    for key, value in values.items():
        template = template.replace('{{' + key + '}}', html.escape(value, quote=True) if html_mode else value)
    if '{{' in template:
        raise SafeError('A template contains unresolved placeholders. Nothing sent.')
    return template


def messages(root, sender, run_id, groups):
    departments = json.loads((root / 'departments.json').read_text(encoding='utf-8'))
    if len(departments) != 10 or {d['slug'] for d in departments} != set(SLUGS):
        raise SafeError('Expected exactly the ten approved department templates. Nothing sent.')
    by_slug = {d['slug']: d for d in departments}
    result = []
    for slug in SLUGS:
        department = by_slug[slug]
        msg = EmailMessage(policy=SMTP)
        msg['From'] = sender
        msg['To'] = RECIPIENT
        msg['Subject'] = f'Test Test Test [{run_id}] GDG ENSIA · {department["name"]} · Ilyes'
        msg['Date'] = formatdate(localtime=False)
        msg['Message-ID'] = make_msgid(domain=sender.rsplit('@', 1)[1])
        msg.set_content(render((root / 'emails' / f'{slug}.txt').read_text(encoding='utf-8'), False, department['name'], None if groups is None else groups[slug]))
        # Keep the complete HTML document, including head, metadata and style blocks.
        msg.add_alternative(render((root / 'emails' / f'{slug}.html').read_text(encoding='utf-8'), True, department['name'], None if groups is None else groups[slug]),
                            subtype='html', cte='quoted-printable')
        result.append((slug, msg))
    return result


# The accepted roster is public-read; no Google token or recipient CSV is needed.
CAMPAIGN = 'gdg-2026-2027-acceptance'
LEDGER_FILE = CAMPAIGN + '.sqlite3'
SHEET_URL = ('https://docs.google.com/spreadsheets/d/'
             '1TCAWzbP9bsYoThGFoW_WI4EsBvVAY1dGDjaErLoB9Ic/'
             'export?format=csv&gid=1180131178')
HEADERS = ['Timestamp', 'Email Address', 'Full Name', 'Email Address ', 'School',
           'Year of Study', 'Why do you want to join us?',
           'Rank your top 3 preferred departments [1st Choice]',
           'Rank your top 3 preferred departments [2nd Choice]',
           'Rank your top 3 preferred departments [3rd Choice]', 'Accepted departemnt']


def fetch_recipients():
    try:
        with urllib.request.urlopen(SHEET_URL, timeout=30) as response:
            if response.status != 200 or response.headers.get_content_type() != 'text/csv':
                raise SafeError('The ACCEPTED sheet did not return CSV. Check public read access. Nothing sent.')
            data = response.read(5_000_001)
        if len(data) > 5_000_000:
            raise SafeError('Sheet export exceeds the safe size limit. Nothing sent.')
        return parse_recipients(data.decode('utf-8-sig'))
    except (urllib.error.URLError, TimeoutError, UnicodeError, http.client.HTTPException):
        raise SafeError('Cannot fetch the ACCEPTED sheet CSV. Check access and connection. Nothing sent.') from None


def parse_recipients(text):
    reader = csv.reader(io.StringIO(text), strict=True)
    if next(reader, None) != HEADERS:
        raise SafeError('Unexpected ACCEPTED sheet headers. Expected email in B, full name in C, accepted department in K. Nothing sent.')
    aliases = {re.sub(r'[\s/-]', '', slug): slug for slug in SLUGS}
    recipients, duplicates, rows = {}, 0, 0
    for number, row in enumerate(reader, 2):
        if not row or not any(value.strip() for value in row):
            continue
        rows += 1
        if len(row) != len(HEADERS):
            raise SafeError(f'Unexpected column count on sheet row {number}. Nothing sent.')
        address, name, department = row[1].strip().lower(), row[2].strip(), row[10].strip()
        if (not address.isascii() or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", address)
                or len(address) > 254 or address.startswith('.') or '..' in address or '.@' in address):
            raise SafeError(f'Missing or invalid column B email on sheet row {number}. Nothing sent.')
        if not name or len(name) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise SafeError(f'Missing or invalid column C name on sheet row {number}. Nothing sent.')
        name = ' '.join(name.split())
        slug = aliases.get(re.sub(r'[\s/-]', '', department.lower()))
        if not slug or any(ord(c) < 32 for c in department):
            raise SafeError(f'Missing or unknown column K department on sheet row {number}. Nothing sent.')
        if address in recipients:
            if recipients[address]['slug'] != slug:
                raise SafeError(f'Conflicting departments for a repeated email at sheet row {number}. Nothing sent.')
            duplicates += 1
            continue  # First valid same-email/same-department row wins, including its name.
        recipients[address] = {'email': address, 'name': name, 'slug': slug}
    if not recipients:
        raise SafeError('The ACCEPTED sheet has no valid recipients. Nothing sent.')
    return list(recipients.values()), rows, duplicates


def recipient_key(address):
    return hashlib.sha256(address.lower().encode('utf-8')).hexdigest()


def normal_messages(root, sender, recipients, groups):
    departments = json.loads((root / 'departments.json').read_text(encoding='utf-8'))
    if len(departments) != 10 or {d['slug'] for d in departments} != set(SLUGS):
        raise SafeError('Expected exactly the ten approved department templates. Nothing sent.')
    names = {d['slug']: d['name'] for d in departments}
    batch = []
    for person in recipients:
        slug = person['slug']
        msg = EmailMessage(policy=SMTP)
        msg['From'], msg['To'] = sender, person['email']
        msg['Subject'] = f'You’re in! Welcome to GDG ENSIA · {names[slug]}'
        msg['Date'] = formatdate(localtime=False)
        msg['Message-ID'] = make_msgid(domain=sender.rsplit('@', 1)[1])
        msg.set_content(render((root/'emails'/f'{slug}.txt').read_text(encoding='utf-8'), False, names[slug], groups[slug], person['name']))
        msg.add_alternative(render((root/'emails'/f'{slug}.html').read_text(encoding='utf-8'), True, names[slug], groups[slug], person['name']), subtype='html', cte='quoted-printable')
        batch.append((person, msg))
    return batch


def read_ledger(root):
    path = root / '.send-state' / LEDGER_FILE
    if not path.exists():
        return {}
    try:
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            return {key: (slug, status) for key, slug, status in db.execute('SELECT recipient_key, department, status FROM deliveries')}
    except sqlite3.Error:
        raise SafeError('Cannot read the normal-send ledger. Do not delete it; review it before sending.') from None


def pending_recipients(recipients, ledger):
    if any(status != 'accepted' for slug, status in ledger.values()):
        raise SafeError('Normal sending is blocked by an uncertain prior submission. Review the ledger and Gmail Sent before resolving it; do not delete the ledger or blindly retry.')
    pending = []
    for person in recipients:
        previous = ledger.get(recipient_key(person['email']))
        if previous and previous[0] != person['slug']:
            raise SafeError('A previously sent recipient now has a different department. Resolve this change before sending; nothing sent.')
        if not previous:
            pending.append(person)
    return pending


def send_normal(batch, sender, password, root):
    state_dir = root / '.send-state'
    state_dir.mkdir(mode=0o700, exist_ok=True)
    lock = state_dir / 'normal.lock'
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SafeError('A normal-send lock exists. Another run may be active or interrupted. Review it before removing the lock; nothing sent.') from None
    os.close(fd)
    db, client = None, None
    try:
        path = state_dir / LEDGER_FILE
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
        db = sqlite3.connect(path, timeout=5)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS deliveries (recipient_key TEXT PRIMARY KEY, department TEXT NOT NULL, status TEXT NOT NULL, message_id TEXT NOT NULL, updated_at TEXT NOT NULL)')
        db.commit()
        ledger = {key: (slug, status) for key, slug, status in db.execute('SELECT recipient_key, department, status FROM deliveries')}
        pending = {recipient_key(p['email']) for p in pending_recipients([p for p, m in batch], ledger)}
        batch = [(p, m) for p, m in batch if recipient_key(p['email']) in pending]
        if not batch:
            print('No new recipients. All are already recorded as SMTP accepted. Nothing sent.')
            return
        client = smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ssl.create_default_context(), timeout=30)
        client.login(sender, password)
        for index, (person, msg) in enumerate(batch, 1):
            key = recipient_key(person['email'])
            # Commit before DATA. A crash, lost reply or failed accepted commit leaves
            # 'uncertain', blocking ALL normal runs rather than risking a duplicate.
            db.execute('INSERT INTO deliveries VALUES (?, ?, ?, ?, ?)',
                       (key, person['slug'], 'uncertain', str(msg['Message-ID']), datetime.now(timezone.utc).isoformat()))
            db.commit()
            refused = client.send_message(msg, from_addr=sender, to_addrs=[person['email']])
            if refused:
                raise SafeError('SMTP refused a recipient. Normal run stopped without retrying; review the ledger.')
            db.execute("UPDATE deliveries SET status='accepted', updated_at=? WHERE recipient_key=?",
                       (datetime.now(timezone.utc).isoformat(), key))
            db.commit()
            print(f'SMTP accepted {index}/{len(batch)}: {person["slug"]}')
        print('Normal batch accepted by SMTP, not a guarantee of inbox delivery. Keep .send-state for future runs.')
    except (smtplib.SMTPException, OSError, sqlite3.Error, KeyboardInterrupt):
        raise SafeError('Normal run stopped; no automatic retry. Review .send-state and Gmail Sent. Accepted entries will not resend; any uncertain entry blocks normal sending. Server details suppressed.') from None
    finally:
        if db is not None:
            db.close()
        if client is not None:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                client.close()
        lock.unlink(missing_ok=True)


def normal_mode(args, root):
    groups = load_groups(args.groups)
    recipients, rows, duplicates = fetch_recipients()
    ledger = read_ledger(root)
    pending = pending_recipients(recipients, ledger)
    # Validate ALL templates and every rendered message, including already sent rows.
    normal_messages(root, 'preview@example.invalid', recipients, groups)
    print(f'ACCEPTED: {rows} rows; {len(recipients)} unique recipients; {duplicates} duplicate rows removed.')
    print(f'Already accepted: {len(recipients) - len(pending)}; new recipients: {len(pending)}.')
    for slug in SLUGS:
        print(f'{slug}: {sum(p["slug"] == slug for p in pending)} new')
    if args.dry_run:
        print('Dry run complete. Sheet fetched read-only; no credentials loaded, no SMTP, no recipient files written.')
        return 0
    if not pending:
        print('Nothing to send.')
        return 0
    address, password = credentials(root)
    batch = normal_messages(root, address, pending, groups)
    send_normal(batch, address, password, root)
    return 0


def write_state(path, data):
    # No credentials, rendered message bodies or SMTP responses are written here.
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def send_batch(batch, sender, password, root, run_id):
    state_dir = root / '.send-state'
    state_dir.mkdir(mode=0o700, exist_ok=True)
    state_path = state_dir / f'{run_id}.json'
    # Exclusive creation stops double clicks, concurrent runs and blind retries.
    try:
        fd = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SafeError('This run ID already has a journal. Nothing sent. Review .send-state and the recipient inbox before intentionally using a NEW --run-id.')
    os.close(fd)
    state = {'run_id': run_id, 'recipient': RECIPIENT, 'status': 'connecting', 'accepted': [], 'attempting': None}
    write_state(state_path, state)
    client = None
    try:
        client = smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ssl.create_default_context(), timeout=30)
        client.login(sender, password)
        for slug, msg in batch:
            state['status'] = 'sending'
            state['attempting'] = {'department': slug, 'message_id': msg['Message-ID']}
            write_state(state_path, state)  # Durable record BEFORE any DATA submission.
            refused = client.send_message(msg, from_addr=sender, to_addrs=[RECIPIENT])
            if refused:
                raise SafeError('SMTP refused a test recipient; stopped without retrying.')
            state['accepted'].append(state['attempting'])
            state['attempting'] = None
            write_state(state_path, state)
            print(f'SMTP accepted: {slug}')
        state['status'] = 'complete'
        write_state(state_path, state)
        # A fully successful run may be deliberately repeated with plain --test.
        state_path.rename(state_dir / f'{run_id}.completed-{uuid.uuid4().hex}.json')
    except (smtplib.SMTPException, OSError, SafeError, KeyboardInterrupt):
        if not state['accepted'] and state['attempting'] is None:
            state_path.unlink(missing_ok=True)
            raise SafeError('SMTP connection or login failed before any message submission. Check the local account settings and try again. Server details are suppressed to protect credentials.') from None
        state['status'] = 'uncertain' if state['attempting'] else 'stopped'
        try:
            write_state(state_path, state)
        except OSError:
            pass  # Existing pre-send record still prevents repeating the run ID.
        raise SafeError('SMTP test stopped. No automatic retry was attempted. Some messages may have been accepted; review .send-state and the recipient inbox before any new run. Server error details are suppressed to protect credentials.') from None
    finally:
        if client is not None:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                client.close()
    print('All 10 messages were accepted by SMTP. This does not guarantee inbox delivery.')


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='Send all 10 test letters to gdg@ensia.edu.dz with the name Ilyes.')
    parser.add_argument('--dry-run', action='store_true', help='Validate only: normal mode fetches the sheet, test mode writes .eml files. No SMTP.')
    parser.add_argument('--run-id', default='test', help='Local duplicate-protection ID, e.g. iphone-v2 (default: test).')
    parser.add_argument('--groups', type=Path, default=root / 'groups.csv', help='Department Telegram mapping CSV (default: root groups.csv).')
    parser.add_argument('--no-group-links', action='store_true', help='With --test only: omit group links and make buttons nonclickable.')
    parser.add_argument('--send', action='store_true', help='Explicitly send normal letters to new validated ACCEPTED-sheet recipients.')
    args = parser.parse_args(argv)
    if args.test and args.send:
        parser.error('--send is only for normal mode; --test already sends tests unless --dry-run is used.')
    if args.send and args.dry_run:
        parser.error('Choose --send OR --dry-run, not both.')
    if not args.test and args.no_group_links:
        parser.error('--no-group-links is only allowed with --test.')
    if not args.test and not (args.send or args.dry_run):
        parser.error('Use --dry-run to preview the ACCEPTED sheet, --send to send, or --test for fixed tests.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', args.run_id):
        parser.error('--run-id must be 1–64 letters, digits, underscores or hyphens.')
    try:
        if not args.test:
            return normal_mode(args, root)
        groups = None if args.no_group_links else load_groups(args.groups)
        if args.dry_run:
            batch = messages(root, 'preview@example.invalid', args.run_id, groups)
            output = root / '.test-output' / args.run_id
            output.mkdir(parents=True, exist_ok=True, mode=0o700)
            for slug, msg in batch:
                fd = os.open(output / f'{slug}.eml', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'wb') as f:
                    f.write(msg.as_bytes())
            print(f'Dry run: wrote 10 .eml files to {output}. No credentials loaded; no network; nothing sent.')
            return 0
        sender, password = credentials(root)
        batch = messages(root, sender, args.run_id, groups)  # Validate all ten before opening SMTP.
        send_batch(batch, sender, password, root, args.run_id)
        return 0
    except (SafeError, OSError, ValueError, KeyError, csv.Error) as error:
        # Only explicitly sanitized messages are shown; never print arbitrary exceptions.
        print(str(error) if isinstance(error, SafeError) else 'Local configuration, template or file error. Nothing further sent; check the files and any run journal.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
