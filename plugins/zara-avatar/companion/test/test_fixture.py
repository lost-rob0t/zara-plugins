import importlib.util
import json
from pathlib import Path
import struct
import unittest

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixture', BASE / 'tools' / 'make_test_vrm.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class TestFixture(unittest.TestCase):
    def test_deterministic_valid_glb(self):
        a = fixture.build_vrm()
        self.assertEqual(a, fixture.build_vrm())
        magic, version, length, json_length, kind = struct.unpack_from('<5I', a)
        self.assertEqual((magic, version, length, kind), (0x46546c67, 2, len(a), 0x4e4f534a))
        self.assertEqual(json_length % 4, 0)
        self.assertLess(len(a), 1024 * 1024)

    def test_model_has_real_humanoid_and_expressions(self):
        data = fixture.build_vrm()
        n = struct.unpack_from('<I', data, 12)[0]
        doc = json.loads(data[20:20+n])
        vrm = doc['extensions']['VRMC_vrm']
        self.assertEqual(vrm['specVersion'], '1.0')
        self.assertTrue(vrm['meta']['allowRedistribution'])
        for bone in ['hips', 'spine', 'head', 'leftUpperArm', 'rightUpperArm',
                     'leftLowerLeg', 'rightLowerLeg', 'leftFoot', 'rightFoot',
                     'leftHand', 'rightHand']:
            self.assertIn(bone, vrm['humanoid']['humanBones'])
        for name in ['happy', 'sad', 'angry', 'relaxed', 'surprised', 'blink', 'aa', 'oh']:
            bind = vrm['expressions']['preset'][name]['morphTargetBinds'][0]
            node = doc['nodes'][bind['node']]
            target = doc['meshes'][node['mesh']]['primitives'][0]['targets'][bind['index']]
            self.assertIn('POSITION', target)
        self.assertGreater(len(doc['meshes']), 10)
        self.assertTrue(all('uri' not in b for b in doc['buffers']))
        self.assertEqual(doc.get('images', []), [])


if __name__ == '__main__':
    unittest.main()
