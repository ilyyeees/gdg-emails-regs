import csv
import io
import sqlite3
from unittest.mock import patch, MagicMock
import smtplib
import test_sender as fixtures
import send_emails as sender

# Reuse fixture helpers, not the test methods, to keep normal-mode cases isolated.
import unittest
class NormalTests(unittest.TestCase):
    setUp = fixtures.SenderTests.setUp
    tearDown = fixtures.SenderTests.tearDown
    write_groups = fixtures.SenderTests.write_groups
    run_main = fixtures.SenderTests.run_main

    def roster(self, records):
        out = io.StringIO(); writer = csv.writer(out); writer.writerow(sender.HEADERS)
        for email, name, department in records:
            row = [''] * 11; row[1], row[2], row[3], row[10] = email, name, 'WRONG@example.invalid', department
            writer.writerow(row)
        return out.getvalue()
    def people(self):
        return sender.parse_recipients(self.roster([('person@example.com', 'Full Person', 'EVENTS'), ('second@example.com', 'Other Person', 'Ui /Ux')]))
    def fetched(self):
        return patch.object(sender, 'fetch_recipients', return_value=self.people())
    def ledger(self):
        return sender.read_ledger(self.root)
    def test_columns_aliases_normalization_and_dedup(self):
        people, rows, dup = sender.parse_recipients(self.roster([(' USER@Example.com ', ' Full   Name ', ' EVENTS '), ('user@example.com', 'Different Name', 'events'), ('ux@example.com','UX Person','Ui /Ux')]))
        self.assertEqual((rows,dup,len(people)),(3,1,2)); self.assertEqual(people[0],{'email':'user@example.com','name':'Full Name','slug':'events'})
        self.assertEqual(people[1]['slug'],'ui-ux')
    def test_bad_rows_fail_closed(self):
        for record in [('','Name','Events'),('bad\n@example.com','Name','Events'),('a@example.com','','Events'),('a@example.com','A\nB','Events'),('a@example.com','Name','wrong'),('a@example.com','Name','A💥I'),('a@example.com','Name','E.V.E.N.T.S')]:
            with self.subTest(record=record), self.assertRaises(sender.SafeError): sender.parse_recipients(self.roster([record]))
        with self.assertRaises(sender.SafeError): sender.parse_recipients(self.roster([]))
        with self.assertRaises(sender.SafeError): sender.parse_recipients('email,name,department\n')
    def test_conflicting_departments_block_all_smtp(self):
        bad=self.roster([('a@example.com','A','Events'),('A@example.com','A','AI')])
        with patch.object(sender,'fetch_recipients',side_effect=lambda:sender.parse_recipients(bad)):
            self.assertEqual(self.run_main('--send'),1)
        self.factory.assert_not_called()
    def test_fetch_exact_sheet_and_response_validation(self):
        response=MagicMock();response.status=200;response.headers.get_content_type.return_value='text/csv';response.read.return_value=self.roster([('a@example.com','A','AI')]).encode()
        with patch.object(sender.urllib.request,'urlopen') as op:
            op.return_value.__enter__.return_value=response
            self.assertEqual(len(sender.fetch_recipients()[0]),1)
            op.assert_called_once_with(sender.SHEET_URL,timeout=30)
            self.assertIn('gid=1180131178',op.call_args.args[0])
            response.headers.get_content_type.return_value='text/html'
            with self.assertRaises(sender.SafeError):sender.fetch_recipients()
    def test_fetch_errors_and_size_limit(self):
        with patch.object(sender.urllib.request,'urlopen',side_effect=sender.urllib.error.URLError('private')):
            with self.assertRaises(sender.SafeError):sender.fetch_recipients()
        response=MagicMock();response.status=200;response.headers.get_content_type.return_value='text/csv';response.read.return_value=b'x'*5_000_001
        with patch.object(sender.urllib.request,'urlopen') as op:
            op.return_value.__enter__.return_value=response
            with self.assertRaises(sender.SafeError):sender.fetch_recipients()
    def test_preview_fetches_without_credentials_or_smtp_or_recipient_file(self):
        with self.fetched(),patch.object(sender,'credentials',side_effect=AssertionError('must not load')):
            self.assertEqual(self.run_main('--dry-run'),0)
        self.factory.assert_not_called();self.assertFalse((self.root/'.send-state').exists());self.assertNotIn('person@example.com',self.output.getvalue())
    def test_requires_explicit_send_and_exclusive_modes(self):
        for args in [[],['--test','--send'],['--send','--dry-run'],['--send','--no-group-links']]:
            with self.subTest(args=args),self.assertRaises(SystemExit):self.run_main(*args)
        self.factory.assert_not_called()
    def test_normal_send_personalized_exact_matching_group_and_no_test_subject(self):
        with self.fetched():self.assertEqual(self.run_main('--send'),0)
        self.assertEqual(self.client.send_message.call_count,2)
        for call, person in zip(self.client.send_message.call_args_list,self.people()[0]):
            msg=call.args[0];self.assertEqual(str(msg['To']),person['email']);self.assertEqual(call.kwargs['to_addrs'],[person['email']])
            self.assertNotIn('Test',str(msg['Subject']));self.assertNotIn('Ilyes',str(msg['Subject']))
            html=msg.get_body(preferencelist=('html',)).get_content();self.assertIn('Dear '+person['name'],html);self.assertIn(self.groups[person['slug']],html);self.assertIn('content="light only"',html)
        self.assertEqual(len(self.ledger()),2);self.assertTrue(all(x[1]=='accepted' for x in self.ledger().values()))
    def test_repeated_send_new_run_id_skips_everyone_without_smtp(self):
        with self.fetched():self.assertEqual(self.run_main('--send'),0)
        self.factory.reset_mock()
        with self.fetched():self.assertEqual(self.run_main('--send','--run-id','new-run'),0)
        self.factory.assert_not_called()
    def test_changed_sheet_sends_only_new_recipient(self):
        with self.fetched():self.assertEqual(self.run_main('--send'),0)
        self.client.send_message.reset_mock()
        people,rows,dup=self.people();people.append({'email':'new@example.com','name':'New Name','slug':'ai'})
        with patch.object(sender,'fetch_recipients',return_value=(people,rows+1,dup)):
            self.assertEqual(self.run_main('--send'),0)
        self.assertEqual(self.client.send_message.call_count,1);self.assertEqual(self.client.send_message.call_args.kwargs['to_addrs'],['new@example.com'])
    def test_department_change_after_success_blocks_before_connection(self):
        with self.fetched():self.assertEqual(self.run_main('--send'),0)
        self.factory.reset_mock();people,rows,dup=self.people();people[0]['slug']='ai'
        with patch.object(sender,'fetch_recipients',return_value=(people,rows,dup)):self.assertEqual(self.run_main('--send'),1)
        self.factory.assert_not_called()
    def test_uncertain_failure_blocks_all_future_run_ids(self):
        self.client.send_message.side_effect=[{},smtplib.SMTPServerDisconnected('secret')]
        with self.fetched():self.assertEqual(self.run_main('--send'),1)
        self.assertEqual(sorted(x[1] for x in self.ledger().values()),['accepted','uncertain'])
        self.factory.reset_mock()
        with self.fetched():self.assertEqual(self.run_main('--send','--run-id','another'),1)
        self.factory.assert_not_called();self.assertNotIn('secret',self.output.getvalue())
    def test_keyboard_interrupt_marks_uncertain(self):
        self.client.send_message.side_effect=KeyboardInterrupt
        with self.fetched():self.assertEqual(self.run_main('--send'),1)
        self.assertEqual(next(iter(self.ledger().values()))[1],'uncertain')
    def test_login_failure_records_no_recipient_and_allows_retry(self):
        self.client.login.side_effect=smtplib.SMTPAuthenticationError(535,b'private')
        with self.fetched():self.assertEqual(self.run_main('--send'),1)
        self.assertEqual(self.ledger(),{})
        self.client.login.side_effect=None
        with self.fetched():self.assertEqual(self.run_main('--send'),0)
    def test_concurrent_or_crashed_lock_blocks_smtp(self):
        state=self.root/'.send-state';state.mkdir();(state/'normal.lock').write_text('')
        with self.fetched():self.assertEqual(self.run_main('--send'),1)
        self.factory.assert_not_called()
    def test_missing_group_or_template_blocks_entire_batch(self):
        with self.fetched():
            (self.root/'emails/ui-ux.html').unlink();self.assertEqual(self.run_main('--send'),1)
        self.factory.assert_not_called()
    def test_full_name_is_escaped_not_guessed(self):
        people,rows,dup=self.people();people[0]['name']='Family Given <b>&'
        with patch.object(sender,'fetch_recipients',return_value=(people,rows,dup)):self.assertEqual(self.run_main('--send'),0)
        html=self.client.send_message.call_args_list[0].args[0].get_body(preferencelist=('html',)).get_content()
        self.assertIn('Dear Family Given &lt;b&gt;&amp;',html)
    def test_ledger_contains_no_clear_email_names_or_invites(self):
        with self.fetched():self.assertEqual(self.run_main('--send'),0)
        blob=(self.root/'.send-state'/sender.LEDGER_FILE).read_bytes()
        for private in [b'person@example.com',b'Full Person',b'https://t.me/',b'test-secret-not-real']:self.assertNotIn(private,blob)
