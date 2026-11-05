import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

spec = importlib.util.spec_from_file_location('convert', Path(__file__).parents[1] / 'scripts' / 'convert.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConversionTest(unittest.TestCase):
    def test_round_trip_resume_failure_and_source_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            builder = FontBuilder(1000, isTTF=True)
            builder.setupGlyphOrder(['.notdef', 'A'])
            builder.setupCharacterMap({65: 'A'})
            glyph = TTGlyphPen(None).glyph()
            builder.setupGlyf({'.notdef': glyph, 'A': glyph})
            builder.setupHorizontalMetrics({'.notdef': (500, 0), 'A': (500, 0)})
            builder.setupHorizontalHeader(ascent=800, descent=-200)
            builder.setupNameTable({'familyName': 'Test', 'styleName': 'Regular'})
            builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
            builder.setupPost()
            builder.setupMaxp()
            font_path = root / 'test.ttf'
            builder.save(font_path)
            data = font_path.read_bytes()
            license_data = b'Test fixture permission'
            source = {'id': 'test', 'name': 'Test', 'approved': True,
                      'url': 'font', 'sha256': hashlib.sha256(data).hexdigest(),
                      'source_url': 'test', 'license': 'fixture', 'license_url': 'license',
                      'license_sha256': hashlib.sha256(license_data).hexdigest()}
            (root / 'sources.json').write_text(json.dumps([source]))
            with patch.object(module, 'ROOT', root), patch.object(module, 'fetch', side_effect=[data, license_data]) as fetch:
                module.run(1, 10)
                module.run(1, 10)
                self.assertEqual(fetch.call_count, 2)
            state = json.loads((root / 'conversion-state.json').read_text())
            entry = state['test']['entry']
            self.assertTrue((root / entry['path']).is_file())
            self.assertEqual(entry['characters'], 1)
            # A changed manifest gets retried; bad data never replaces the old good entry.
            source['sha256'] = '0' * 64
            (root / 'sources.json').write_text(json.dumps([source]))
            with patch.object(module, 'ROOT', root), patch.object(module, 'fetch', return_value=data) as fetch:
                for _ in range(4):
                    module.run(1, 10)
                self.assertEqual(fetch.call_count, 3)
            state = json.loads((root / 'conversion-state.json').read_text())
            self.assertEqual(state['test']['status'], 'failed')
            self.assertEqual(json.loads((root / 'catalog.json').read_text())['fonts'][0], entry)

    def test_reject_unsafe_id_and_mutable_url(self):
        with self.assertRaises(ValueError):
            module.validate_sources([{'id': '../escape'}])
        with self.assertRaises(ValueError):
            module.fetch('https://raw.githubusercontent.com/user/repo/main/font.ttf', 100)


if __name__ == '__main__':
    unittest.main()
