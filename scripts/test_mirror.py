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

if __name__ == '__main__': unittest.main()
