# Send the ten Gmail test emails

Python 3.9+ and the standard library only. No package installation is required.

## 1. Clone and configure locally

```sh
git clone https://github.com/ilyyeees/gdg-emails-regs.git
cd gdg-emails-regs
cp .env.example .env
chmod 600 .env
```

Open **`.env` in the repository root, next to `send_emails.py`**, and fill in:

```dotenv
GMAIL_ADDRESS=your-sending-account@gmail.com
GMAIL_APP_PASSWORD=your-16-character-app-password
```

`GMAIL_ADDRESS` is the account you authenticate and send **from**, not necessarily the test recipient. `gdg@ensia.edu.dz` is the fixed **recipient** in test mode. Use your Google app password, not your ordinary account password. Spaces in Google's grouped app password are removed by the script. Matching single or double quotes around values are accepted; no shell commands, expansion, or interpolation are evaluated. Existing environment variables take precedence over `.env`.

Keep the filled `.env` on your own computer. It is ignored by Git, along with local messages and journals. Never paste it in chat, commit it, or share screenshots of it. `.env.example` is intentionally blank and safe to commit. `chmod` is for macOS/Linux; on Windows copy the example to `.env` and restrict access using your local file permissions.

Google requires 2-Step Verification for app passwords. They may be unavailable with certain managed accounts, security-key-only setups, or Advanced Protection. See [Google's app-password instructions](https://support.google.com/accounts/answer/185833?hl=en). The script uses authenticated `smtp.gmail.com:465` with certificate-verified TLS, per [Google's Gmail SMTP settings](https://support.google.com/a/answer/176600?hl=en).

## 2. Optional offline preview

```sh
python3 send_emails.py --test --dry-run
```

Writes ten multipart `.eml` messages into `.test-output/test/`. Does not read credentials, contact SMTP, or send anything. The dry-run From address is the reserved placeholder `preview@example.invalid`. Opening an `.eml` in an email client may itself download its hosted images; the Python dry run does not.

## 3. Send the actual test batch

```sh
python3 send_emails.py --test
```

**This sends ten real emails**, one per department, all to **gdg@ensia.edu.dz**, using **Ilyes** as the name. Subjects begin with `[TEST test]`. The From address is your configured authenticated account.

The script replaces all three placeholders. Test next-step copy explicitly says this is a rendering test with no membership action required. The button points to the existing HTTPS preview gallery, not an invented onboarding destination.

Each message contains a plain-text alternative and the complete HTML document, including its head, metadata, CSS, and public hosted-image URLs. The current templates are not altered by the sender. This lets you compare a raw-HTML SMTP message against one copied through a composer. It **does not promise a Gmail dark-mode fix**: check the newly received message on the actual phone in light and dark mode.

Running `--test` again after a fully successful batch deliberately sends all ten again. A completed batch journal is archived in `.send-state/`. SMTP acceptance is not a guarantee of inbox delivery; check the recipient inbox/spam folder.

## Interrupted or failed runs

There is no automatic retry. Before each SMTP submission, the script writes a local journal. An unresolved or partially completed run blocks another batch with the same run ID, preventing blind duplicate sends after a connection drop.

Read `.send-state/test.json` and check the recipient inbox. It lists the departments accepted by SMTP and the department whose outcome may be uncertain, without credentials or message bodies. Do not assume an error means nothing was sent. Server error details are deliberately suppressed so credentials cannot accidentally appear in logs.

After reviewing the outcome, if you deliberately want an entirely new ten-message test batch, use a new ID:

```sh
python3 send_emails.py --test --run-id iphone-v2
```

This starts a new full batch, **not a partial resume**, and marks its subjects `[TEST iphone-v2]`. Do not choose a new ID merely to bypass an unresolved delivery outcome.

## Normal sending is disabled

```sh
python3 send_emails.py
```

Exits before reading credentials or contacting SMTP. A TODO comment in `send_emails.py` reserves normal mode until the CSV format and recipient workflow are agreed. There is no CSV import, recipient override, or production send mode yet.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests mock SMTP. They verify all ten messages, fixed name/recipient, authenticated From, intact HTML, TLS configuration, credential-free dry runs, disabled normal mode, missing-credential failure, repeatable completed tests, ambiguous-failure duplicate protection, and absence of credentials in logs/journals. No real email is sent by the tests.
