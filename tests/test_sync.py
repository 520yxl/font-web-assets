import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from sync_sources import nearby_license, license_type


class DiscoveryTest(unittest.TestCase):
    def test_project_license_and_no_root_license(self):
        blobs = {'incoming/project/OFL.txt': {}, 'LICENSE': {}}
        self.assertEqual(nearby_license('incoming/project/ttf/font.ttf', blobs), 'incoming/project/OFL.txt')
        self.assertIsNone(nearby_license('incoming/unrelated/font.ttf', blobs))

    def test_license_detection(self):
        self.assertEqual(license_type(b'SIL OPEN FONT LICENSE Version 1.1'), 'OFL-1.1')
        self.assertIsNone(license_type(b'All rights reserved'))
