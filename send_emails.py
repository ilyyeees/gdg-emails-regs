#!/usr/bin/env python3
"""Send the ten GDG ENSIA test letters. Normal/CSV sending is intentionally disabled."""
import argparse
import csv
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid, parseaddr
import html
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


def render(template, html_mode, department, group_url):
    no_links = group_url is None
    if no_links and html_mode:
        # A span has no href, click handler, anchor behavior, or keyboard link focus.
        template, count = re.subn(r'<a href="{{next_step_url}}"([^>]*)>(.*?)</a>',
                                  r'<span\1 aria-disabled="true">\2</span>', template, flags=re.S)
        if count != 1:
            raise SafeError('Expected one Telegram button to disable. Nothing sent.')
    text = ('Layout test only. Telegram links are intentionally disabled.' if no_links
            else f'Join the {department} Telegram group to connect with your team.')
    values = {'first_name': FIRST_NAME, 'next_step_text': text, 'next_step_url': group_url or ''}
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
    parser.add_argument('--dry-run', action='store_true', help='With --test: write .eml files only; no credentials or network.')
    parser.add_argument('--run-id', default='test', help='Local duplicate-protection ID, e.g. iphone-v2 (default: test).')
    parser.add_argument('--groups', type=Path, default=root / 'groups.csv', help='Department Telegram mapping CSV (default: root groups.csv).')
    parser.add_argument('--no-group-links', action='store_true', help='With --test only: omit group links and make buttons nonclickable.')
    args = parser.parse_args(argv)
    if not args.test:
        # TODO: Define the normal-mode CSV schema with the user, then implement it.
        # Do not load recipients or open an SMTP connection until that work is approved.
        parser.error('Normal mode is disabled until the CSV format is agreed. Use --test or --test --dry-run.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', args.run_id):
        parser.error('--run-id must be 1–64 letters, digits, underscores or hyphens.')
    try:
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
