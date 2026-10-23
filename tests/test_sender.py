import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import smtplib
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import send_emails as sender

class SenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copy(sender.ROOT / 'departments.json', self.root)
        shutil.copytree(sender.ROOT / 'emails', self.root / 'emails')
        self.groups = {slug: 'https://t.me/+TESTONLY_' + slug for slug in sender.SLUGS}
        self.write_groups(self.groups)
        self.env = patch.dict(os.environ, {'GMAIL_ADDRESS': 'sender@example.com', 'GMAIL_APP_PASSWORD': 'test-secret-not-real'}, clear=True)
        self.env.start()
        self.smtp = patch.object(sender.smtplib, 'SMTP_SSL')
        self.factory = self.smtp.start()
        self.client = self.factory.return_value
        self.client.send_message.return_value = {}
        self.output = io.StringIO()
        self.stdout = contextlib.redirect_stdout(self.output)
        self.stderr = contextlib.redirect_stderr(self.output)
        self.stdout.__enter__(); self.stderr.__enter__()
    def write_groups(self, groups):
        import csv
        with (self.root/'groups.csv').open('w',newline='') as f:
            w=csv.writer(f); w.writerow(['department','telegram_url']); w.writerows(groups.items())
    def tearDown(self):
        self.stderr.__exit__(None,None,None); self.stdout.__exit__(None,None,None)
        self.smtp.stop(); self.env.stop(); self.tmp.cleanup()
    def run_main(self, *args):
        return sender.main(list(args), root=self.root)
    def test_light_only_metadata_survives_mime_serialization(self):
        from email import policy
        from email.parser import BytesParser
        self.assertEqual(self.run_main('--test'), 0)
        for call in self.client.send_message.call_args_list:
            decoded = BytesParser(policy=policy.default).parsebytes(call.args[0].as_bytes())
            html = decoded.get_body(preferencelist=('html',)).get_content()
            self.assertIn('<meta name="color-scheme" content="light only">', html)
            self.assertIn('<meta name="supported-color-schemes" content="light only">', html)
            self.assertIn('<style>', html)
            self.assertIn('JOIN YOUR TELEGRAM GROUP', html)

    def test_normal_mode_never_connects(self):
        with self.assertRaises(SystemExit): self.run_main()
        self.factory.assert_not_called()
    def test_dry_run_requires_test_flag(self):
        with self.assertRaises(SystemExit): self.run_main('--dry-run')
        self.factory.assert_not_called()
    def test_missing_credentials_fails_before_network(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.run_main('--test'), 1)
        self.factory.assert_not_called()
    def test_ten_fixed_recipient_name_and_intact_html(self):
        self.assertEqual(self.run_main('--test'), 0)
        self.assertEqual(self.client.send_message.call_count, 10)
        self.factory.assert_called_once()
        self.assertEqual(self.factory.call_args.args, ('smtp.gmail.com', 465))
        self.assertTrue(self.factory.call_args.kwargs['context'].check_hostname)
        self.client.login.assert_called_once_with('sender@example.com', 'test-secret-not-real')
        for call, slug in zip(self.client.send_message.call_args_list, sender.SLUGS):
            msg = call.args[0]
            self.assertEqual(call.kwargs['to_addrs'], ['gdg@ensia.edu.dz'])
            self.assertEqual(call.kwargs['from_addr'], 'sender@example.com')
            self.assertEqual(msg['To'], 'gdg@ensia.edu.dz')
            self.assertEqual(msg['From'], 'sender@example.com')
            self.assertIn('[TEST test]', msg['Subject'])
            self.assertEqual(msg.get_content_type(), 'multipart/alternative')
            html = msg.get_body(preferencelist=('html',)).get_content()
            department = next(d['name'] for d in json.loads((self.root/'departments.json').read_text()) if d['slug']==slug)
            expected = sender.render((self.root/'emails'/f'{slug}.html').read_text(), True, department, self.groups[slug])
            self.assertEqual(html.replace('\r\n','\n').rstrip('\n'), expected.rstrip('\n'))
            self.assertIn('<head>', html); self.assertIn('<style>', html)
            self.assertIn('Dear Ilyes', html); self.assertNotIn('{{', html)
            self.assertIn(self.groups[slug], html)
            self.assertEqual(html.count('href="'+self.groups[slug]+'"'),1)
            self.assertIn('Ilyes', msg.get_body(preferencelist=('plain',)).get_content())
        self.assertNotIn('test-secret-not-real', self.output.getvalue())
    def test_success_can_be_intentionally_repeated(self):
        self.assertEqual(self.run_main('--test'),0)
        self.assertEqual(self.run_main('--test'),0)
        self.assertEqual(self.client.send_message.call_count,20)
        self.assertEqual(len(list((self.root/'.send-state').glob('*.completed-*.json'))),2)
    def test_ambiguous_failure_stops_and_blocks_repeat(self):
        self.client.send_message.side_effect = [{}, smtplib.SMTPServerDisconnected('test-secret-not-real')]
        self.assertEqual(self.run_main('--test'),1)
        self.assertEqual(self.client.send_message.call_count,2)
        journal=json.loads((self.root/'.send-state/test.json').read_text())
        self.assertEqual(journal['status'],'uncertain')
        self.assertEqual(len(journal['accepted']),1)
        self.assertEqual(journal['attempting']['department'],'multimedia')
        self.factory.reset_mock()
        self.assertEqual(self.run_main('--test'),1)
        self.factory.assert_not_called()
        self.assertNotIn('test-secret-not-real',self.output.getvalue())
        self.assertNotIn('test-secret-not-real',json.dumps(journal))
    def test_login_failure_is_safe_to_retry(self):
        self.client.login.side_effect = smtplib.SMTPAuthenticationError(535, b'test-secret-not-real')
        self.assertEqual(self.run_main('--test'),1)
        self.client.send_message.assert_not_called()
        self.assertFalse((self.root/'.send-state/test.json').exists())
        self.assertNotIn('test-secret-not-real',self.output.getvalue())
        self.client.login.side_effect = None
        self.assertEqual(self.run_main('--test'),0)
    def test_dry_run_uses_no_credentials_or_network(self):
        with patch.object(sender,'credentials',side_effect=AssertionError('must not load secrets')):
            self.assertEqual(self.run_main('--test','--dry-run'),0)
        self.factory.assert_not_called()
        self.assertEqual(len(list((self.root/'.test-output/test').glob('*.eml'))),10)
        self.assertFalse((self.root/'.send-state').exists())
    def test_all_templates_validated_before_network(self):
        (self.root/'emails/ai.html').write_text('{{unknown}}')
        self.assertEqual(self.run_main('--test'),1)
        self.factory.assert_not_called()
    def test_dotenv_parser_and_environment_precedence(self):
        (self.root/'.env').write_text('# local\nGMAIL_ADDRESS="local@example.com"\nGMAIL_APP_PASSWORD="abcd efgh ijkl mnop"\n')
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(sender.credentials(self.root),('local@example.com','abcdefghijklmnop'))
        self.assertEqual(sender.credentials(self.root),('sender@example.com','test-secret-not-real'))
    def test_invalid_config_not_printed(self):
        (self.root/'.env').write_text('SECRET_LEAK=test-secret-not-real\n')
        self.assertEqual(self.run_main('--test'),1)
        self.assertNotIn('test-secret-not-real',self.output.getvalue())
        self.factory.assert_not_called()
    def test_missing_one_group_blocks_all_sends(self):
        self.write_groups({k:v for k,v in self.groups.items() if k!='ai'})
        self.assertEqual(self.run_main('--test'),1)
        self.factory.assert_not_called()
    def test_invalid_groups_all_block_before_network(self):
        invalid=['', 'https://evil.example/group', 'http://t.me/testgroup', 'https://t.me@evil.example/testgroup',
                 'https://t.me:443/testgroup','https://t.me/share','https://t.me/+1234567890',
                 'https://t.me/testgroup?x=y','https://t.me/testgroup#x','https://t.me/testgroup/12',
                 'https://t.me/evil"><script>', 'https://t.me/te\nstgroup']
        for url in invalid:
            with self.subTest(url=url):
                self.write_groups(dict(self.groups, ai=url))
                self.assertEqual(self.run_main('--test'),1)
                self.factory.assert_not_called()
    def test_duplicate_and_unknown_departments_block(self):
        for suffix in ['ai,https://t.me/testgroup\n','unknown,https://t.me/testgroup\n']:
            self.write_groups(self.groups)
            with (self.root/'groups.csv').open('a') as f:f.write(suffix)
            self.assertEqual(self.run_main('--test'),1)
            self.factory.assert_not_called()
    def test_no_group_links_is_truly_noninteractive(self):
        (self.root/'groups.csv').unlink()
        self.assertEqual(self.run_main('--test','--no-group-links'),0)
        for call in self.client.send_message.call_args_list:
            msg=call.args[0]; h=msg.get_body(preferencelist=('html',)).get_content()
            self.assertNotIn('<a ',h); self.assertNotIn('href=',h)
            self.assertIn('aria-disabled="true"',h)
            self.assertNotIn('https://t.me',h)
            plain=msg.get_body(preferencelist=('plain',)).get_content()
            self.assertNotIn('https://',plain)
            self.assertIn('intentionally disabled',plain)
    def test_dry_run_requires_groups_unless_bypass(self):
        (self.root/'groups.csv').unlink()
        self.assertEqual(self.run_main('--test','--dry-run'),1)
        self.factory.assert_not_called()
        self.assertEqual(self.run_main('--test','--dry-run','--no-group-links'),0)
        self.factory.assert_not_called()
    def test_no_links_without_test_is_rejected(self):
        with self.assertRaises(SystemExit):self.run_main('--no-group-links')
        self.factory.assert_not_called()
    def test_custom_group_path_and_legacy_invite(self):
        self.write_groups(dict(self.groups,ai='https://t.me/joinchat/Test_hash'))
        alternate=self.root/'private.csv'; (self.root/'groups.csv').rename(alternate)
        self.assertEqual(self.run_main('--test','--groups',str(alternate)),0)
    def test_markup_is_escaped(self):
        template='<p>{{first_name}} {{next_step_text}}</p><a href="{{next_step_url}}">join</a>'
        with patch.object(sender,'FIRST_NAME','Ilyes <b>&'):
            result=sender.render(template,True,'A&B <tag>','https://t.me/testgroup')
        self.assertIn('Ilyes &lt;b&gt;&amp;',result)
        self.assertIn('A&amp;B &lt;tag&gt;',result)
        self.assertNotIn('<tag>',result)
    def test_invites_never_logged(self):
        self.assertEqual(self.run_main('--test'),0)
        self.assertNotIn('https://t.me',self.output.getvalue())
        for p in (self.root/'.send-state').glob('*.json'):
            self.assertNotIn('https://t.me',p.read_text())
    def test_run_id_cannot_escape_directory(self):
        with self.assertRaises(SystemExit): self.run_main('--test','--run-id','../oops')
        self.factory.assert_not_called()

if __name__ == '__main__': unittest.main()
