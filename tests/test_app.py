import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class StreakDuckTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / 'test.db'
        # Import-time initialization must never touch the real streak database.
        connect = sqlite3.connect
        spec = importlib.util.spec_from_file_location('streakduck', Path(__file__).resolve().parents[1] / 'app.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch('sqlite3.connect', side_effect=lambda _: connect(self.database)):
            spec.loader.exec_module(self.module)
        self.module.DB_PATH = self.database
        self.module.app.config['TESTING'] = True
        self.client = self.module.app.test_client()

    def rows(self):
        with self.module.get_db() as conn:
            return conn.execute('SELECT * FROM streaks ORDER BY rowid').fetchall()

    def create(self, client=None):
        response = (client or self.client).post('/create')
        self.assertEqual(response.status_code, 200)
        return self.rows()[-1]

    def link(self, row, buddy=1):
        return f"/s/{row['id']}/{row[f'user{buddy}_token']}"

    def test_multiple_streaks_are_saved_and_dashboard_does_not_check_in(self):
        first = self.create()
        second = self.create()
        dashboard = self.client.get('/', follow_redirects=True).get_data(as_text=True)
        self.assertIn(self.link(first), dashboard)
        self.assertIn(self.link(second), dashboard)
        self.assertEqual(dashboard.count('Open streak'), 2)
        self.assertTrue(all(row['last_visit_user1_date'] is None for row in self.rows()))
        self.assertNotIn('Open streak', self.module.app.test_client().get('/', follow_redirects=True).get_data(as_text=True))

    def test_existing_link_is_remembered_once_and_switches_buddy(self):
        row = self.create()
        buddy = self.module.app.test_client()
        for _ in range(2):
            self.assertEqual(buddy.get(self.link(row, 2)).status_code, 200)
        dashboard = buddy.get('/', follow_redirects=True).get_data(as_text=True)
        self.assertEqual(dashboard.count('Open streak'), 1)
        self.assertIn(self.link(row, 2), dashboard)
        buddy.get(self.link(row))
        dashboard = buddy.get('/', follow_redirects=True).get_data(as_text=True)
        self.assertEqual(dashboard.count('Open streak'), 1)
        self.assertIn(self.link(row), dashboard)

    def test_names_persist_and_appear_on_all_pages(self):
        row = self.create()
        response = self.client.post(self.link(row) + '/name', data={'name': ' Shawn '}, follow_redirects=True)
        self.assertIn('I am Shawn', response.get_data(as_text=True))
        self.assertIn('Back to dash', response.get_data(as_text=True))
        self.client.post(self.link(row, 2) + '/name', data={'name': 'Sam'})
        self.assertIn('Shawn &amp; Sam', self.client.get('/', follow_redirects=True).get_data(as_text=True))
        choice = self.client.get(f"/s/{row['id']}").get_data(as_text=True)
        self.assertIn('I am Shawn', choice)
        self.assertIn('I am Sam', choice)
        self.assertEqual(self.rows()[0]['user1_name'], 'Shawn')

    def test_name_validation_and_escaping(self):
        row = self.create()
        for name in ('', '   ', 'x' * 61):
            self.assertEqual(self.client.post(self.link(row) + '/name', data={'name': name}).status_code, 400)
        self.assertEqual(self.rows()[0]['user1_name'], 'Duck A')
        self.client.post(self.link(row) + '/name', data={'name': '<script>alert(1)</script>'})
        page = self.client.get(self.link(row)).get_data(as_text=True)
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>', page)

    def test_invalid_links_cannot_rename_or_join_dashboard(self):
        row = self.create()
        stranger = self.module.app.test_client()
        invalid = f"/s/{row['id']}/invalid"
        self.assertEqual(stranger.get(invalid).status_code, 404)
        self.assertEqual(stranger.post(invalid + '/name', data={'name': 'Changed'}).status_code, 404)
        self.assertEqual(stranger.get('/s/missing/token').status_code, 404)
        self.assertNotIn('Open streak', stranger.get('/', follow_redirects=True).get_data(as_text=True))
        self.assertEqual(self.rows()[0]['user1_name'], 'Duck A')

    def test_daily_increment_remains_once_per_streak(self):
        first = self.create()
        second = self.create()
        for _ in range(3):
            self.client.get(self.link(first))
            self.client.get(self.link(first, 2))
        self.assertEqual([row['streak_count'] for row in self.rows()], [1, 0])
        self.assertIsNone(self.rows()[1]['last_visit_user1_date'])
        self.client.get(self.link(second))
        self.assertEqual(self.rows()[1]['streak_count'], 0)

    def test_legacy_database_migration_preserves_links_and_counts(self):
        with self.module.get_db() as conn:
            conn.execute('DROP TABLE streaks')
            conn.execute('''CREATE TABLE streaks (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, streak_count INTEGER NOT NULL,
                last_increment_date TEXT, last_visit_user1_date TEXT, last_visit_user2_date TEXT,
                user1_token TEXT NOT NULL, user2_token TEXT NOT NULL)''')
            conn.execute("INSERT INTO streaks VALUES ('legacy', '2026-01-01', 25, NULL, NULL, NULL, 'a', 'b')")
        self.module.init_db()
        self.module.init_db()
        row = self.rows()[0]
        self.assertEqual((row['id'], row['streak_count'], row['user1_token'], row['user2_token']), ('legacy', 25, 'a', 'b'))
        self.assertEqual((row['user1_name'], row['user2_name']), ('Duck A', 'Duck B'))
        self.assertEqual(self.client.get('/s/legacy/a').status_code, 200)
        self.assertIn('/s/legacy/a', self.client.get('/', follow_redirects=True).get_data(as_text=True))


    def dashboard_path(self, client=None):
        client = client or self.client
        return '/d/' + client.get_cookie(self.module.DASHBOARD_COOKIE).value

    def test_permanent_link_restores_all_streaks_after_cookies_are_cleared(self):
        first = self.create()
        second = self.create()
        path = self.dashboard_path()
        self.assertEqual(self.client.get('/').location, path)
        self.client.delete_cookie(self.module.DASHBOARD_COOKIE)
        self.assertNotIn('Open streak', self.client.get('/').get_data(as_text=True))
        restored = self.client.get(path)
        self.assertEqual(restored.status_code, 200)
        page = restored.get_data(as_text=True)
        self.assertIn(self.link(first), page)
        self.assertIn(self.link(second), page)
        self.assertIn('http://localhost' + path, page)
        self.assertEqual(self.dashboard_path(), path)
        self.assertEqual(self.client.get('/').location, path)
        self.assertTrue(all(row['last_visit_user1_date'] is None for row in self.rows()))

    def test_new_device_uses_same_permanent_dashboard_for_future_streaks(self):
        first = self.create()
        path = self.dashboard_path()
        device = self.module.app.test_client()
        self.assertEqual(device.get(path).status_code, 200)
        second = self.create(device)
        for client in (device, self.client):
            page = client.get(path).get_data(as_text=True)
            self.assertIn(self.link(first), page)
            self.assertIn(self.link(second), page)
        third = self.create()
        self.assertIn(self.link(third), device.get(path).get_data(as_text=True))

    def test_existing_dashboard_id_remains_the_permanent_link(self):
        row = self.create()
        legacy_id = 'existing-browser-dashboard-token'
        with self.module.get_db() as conn:
            conn.execute('UPDATE dashboard_streaks SET dashboard_id = ?', (legacy_id,))
        self.client.set_cookie(self.module.DASHBOARD_COOKIE, legacy_id)
        self.module.init_db()
        self.assertEqual(self.client.get('/').location, '/d/' + legacy_id)
        self.assertIn(self.link(row), self.client.get('/d/' + legacy_id).get_data(as_text=True))

    def test_invalid_dashboard_link_does_not_replace_existing_dashboard(self):
        self.create()
        path = self.dashboard_path()
        response = self.client.get('/d/not-a-real-dashboard')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.dashboard_path(), path)
        stranger = self.module.app.test_client()
        self.assertEqual(stranger.get('/d/not-a-real-dashboard').status_code, 404)
        self.assertIsNone(stranger.get_cookie(self.module.DASHBOARD_COOKIE))

    def test_dashboard_links_are_not_cached_or_sent_as_referrers(self):
        self.create()
        response = self.client.get(self.dashboard_path())
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', response.headers['Set-Cookie'])


if __name__ == '__main__':
    unittest.main()
