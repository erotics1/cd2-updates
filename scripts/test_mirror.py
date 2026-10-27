import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('mirror', Path(__file__).with_name('mirror.py'))
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)

class MirrorTests(unittest.TestCase):
    def test_current_bt_dataset(self):
        data = {'kind':'cd20-bt-incremental-v1','targetBuildId':'cd20-bt-base-20261026-r52b',
                'targetManifestSha256':'a'*64,'available':[{'sha256':'b'*64,'size':31}]}
        self.assertEqual(mirror.validate_dataset(data), [('b'*64, 31)])
        for bad in [dict(data, kind='legacy'), dict(data, targetBuildId='../oops'),
                    dict(data, available=[{'sha256':'z'*64,'size':31}]),
                    dict(data, available=[{'sha256':'b'*64,'size':2**31}]),
                    dict(data, available=data['available']*2)]:
            with self.assertRaises(ValueError): mirror.validate_dataset(bad)

    def test_index_can_only_name_public_repository_assets(self):
        row = {'sha256':'a'*64,'size':30,'tag':'mirror-cd20-bt-base-20261026-r52b-1234'}
        self.assertTrue(mirror.valid_entry(row))
        for key, val in [('sha256','../x'),('size',-1),('tag','https://attacker.test/x'),('tag','../main')]:
            with self.subTest(key=key): self.assertFalse(mirror.valid_entry(dict(row, **{key:val})))

    def test_download_waits_while_origin_is_busy(self):
        import io, urllib.error
        calls, sleeps = [], []
        def fake_once(sha, size, path):
            calls.append(sha)
            if len(calls) < 3:
                raise urllib.error.HTTPError('u', 429, 'busy', {'Retry-After': '2'}, io.BytesIO())
            return 'ok'
        original = mirror.download_once
        mirror.download_once = fake_once
        try:
            self.assertEqual(mirror.download('a'*64, 1, None, sleep=sleeps.append, clock=lambda: 0), 'ok')
        finally:
            mirror.download_once = original
        self.assertEqual((len(calls), sleeps), (3, [2, 2]))

    def test_download_gives_up_on_other_errors_and_after_the_deadline(self):
        import io, urllib.error
        def not_found(sha, size, path):
            raise urllib.error.HTTPError('u', 404, 'missing', {}, io.BytesIO())
        def busy(sha, size, path):
            raise urllib.error.HTTPError('u', 429, 'busy', {}, io.BytesIO())
        original = mirror.download_once
        try:
            for fake, clock in [(not_found, lambda: 0), (busy, iter([0, mirror.RETRY_SECONDS + 1]).__next__)]:
                mirror.download_once = fake
                with self.assertRaises(urllib.error.HTTPError):
                    mirror.download('a'*64, 1, None, sleep=lambda s: None, clock=clock)
        finally:
            mirror.download_once = original

if __name__ == '__main__': unittest.main()
