"""Generate the original, texture-free Zara Test Bot VRM 1.0 fixture offline.

The generated model and this generator are CC0-1.0. It is a functional geometric
humanoid test asset, not the pixiv sample or a production character illustration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

PRESETS = ('happy', 'sad', 'angry', 'relaxed', 'surprised', 'blink', 'aa', 'ih', 'ou', 'ee', 'oh')


def face_geometry(expression: str = 'neutral') -> tuple[list[list[float]], list[int]]:
    positions: list[list[float]] = []
    indices: list[int] = []
    for side in (-1, 1):
        cx, cy, rx, ry = side * 0.079, 0.16, 0.032, 0.038
        slope = 0.0
        if expression in ('happy', 'relaxed', 'blink'):
            ry = {'happy': 0.011, 'relaxed': 0.006, 'blink': 0.001}[expression]
        if expression == 'angry':
            slope, ry = side * 0.5, 0.016
        if expression == 'sad':
            slope, ry = -side * 0.45, 0.022
        if expression == 'surprised':
            rx, ry = 0.038, 0.047
        start = len(positions)
        positions.append([cx, cy, 0.174])
        for i in range(32):
            angle = 2 * math.pi * i / 32
            x = rx * math.cos(angle)
            positions.append([cx + x, cy + ry * math.sin(angle) + slope * x, 0.174])
        for i in range(32):
            indices.extend([start, start + 1 + i, start + 1 + (i + 1) % 32])
    start = len(positions)
    opened = expression in ('surprised', 'aa', 'oh', 'ou', 'ih', 'ee')
    for i in range(33):
        a = 2 * math.pi * i / 32
        if opened:
            rx, ry = (0.023, 0.034) if expression in ('oh', 'ou', 'surprised') else (0.053, 0.028)
            if expression in ('ih', 'ee'):
                ry = 0.015
            for thickness in (-0.0035, 0.0035):
                positions.append([(rx + thickness) * math.cos(a), 0.07 + (ry + thickness) * math.sin(a), 0.174])
        else:
            x = (i / 32 - 0.5) * 0.13
            curve = -0.023 if expression == 'happy' else 0.023 if expression == 'sad' else 0.0
            y = 0.065 + curve * (1 - (x / 0.065) ** 2)
            for thickness in (-0.004, 0.004):
                positions.append([x, y + thickness, 0.174])
        if i < 32:
            j = start + i * 2
            indices.extend([j, j + 2, j + 1, j + 1, j + 2, j + 3])
    return positions, indices


def build_vrm() -> bytes:
    binary = bytearray()
    doc: dict = {
        'asset': {'version': '2.0', 'generator': 'Zara Test Bot generator 1.0.0'},
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'name': 'Zara Test Bot', 'children': []}],
        'meshes': [], 'bufferViews': [], 'accessors': [],
        'materials': [
            {'name': 'Shell', 'pbrMetallicRoughness': {'baseColorFactor': [0.69, 0.75, 0.8, 1], 'metallicFactor': 0.25, 'roughnessFactor': 0.6}},
            {'name': 'Joints', 'pbrMetallicRoughness': {'baseColorFactor': [0.075, 0.10, 0.17, 1], 'metallicFactor': 0.1, 'roughnessFactor': 0.8}},
            {'name': 'Accent', 'pbrMetallicRoughness': {'baseColorFactor': [0.8, 0.08, 0.17, 1], 'metallicFactor': 0.1, 'roughnessFactor': 0.7}},
            {'name': 'Face', 'doubleSided': True, 'pbrMetallicRoughness': {'baseColorFactor': [0.012, 0.04, 0.08, 1], 'metallicFactor': 0, 'roughnessFactor': 1}},
        ],
        'extensionsUsed': ['VRMC_vrm'],
    }

    def accessor(rows: list, kind: str, integer: bool = False) -> int:
        assert rows and kind in ('VEC3', 'SCALAR')
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        flat = rows if kind == 'SCALAR' else [v for row in rows for v in row]
        fmt = 'H' if integer else 'f'
        binary.extend(struct.pack('<' + str(len(flat)) + fmt, *flat))
        view = len(doc['bufferViews'])
        doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(binary) - offset})
        item = {'bufferView': view, 'componentType': 5123 if integer else 5126, 'count': len(rows), 'type': kind}
        if kind == 'VEC3':
            item['min'] = [min(row[d] for row in rows) for d in range(3)]
            item['max'] = [max(row[d] for row in rows) for d in range(3)]
        doc['accessors'].append(item)
        return len(doc['accessors']) - 1

    def node(name: str, parent: int, translation: tuple = (0, 0, 0)) -> int:
        result = len(doc['nodes'])
        doc['nodes'].append({'name': name, 'translation': list(translation), 'children': []})
        doc['nodes'][parent]['children'].append(result)
        return result

    def box(name: str, parent: int, center: tuple, size: tuple, material: int = 0) -> None:
        positions, normals, indices = [], [], []
        for axis, sign in ((0, -1), (0, 1), (1, -1), (1, 1), (2, -1), (2, 1)):
            u, v = (axis + 1) % 3, (axis + 2) % 3
            start = len(positions)
            for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                p = list(center)
                p[axis] += sign * size[axis] / 2
                p[u] += a * size[u] / 2
                p[v] += b * size[v] / 2
                positions.append(p)
                normal = [0, 0, 0]
                normal[axis] = sign
                normals.append(normal)
            order = (0, 1, 2, 0, 2, 3) if sign > 0 else (0, 2, 1, 0, 3, 2)
            indices.extend(start + i for i in order)
        mesh = len(doc['meshes'])
        doc['meshes'].append({'name': name, 'primitives': [{
            'attributes': {'POSITION': accessor(positions, 'VEC3'), 'NORMAL': accessor(normals, 'VEC3')},
            'indices': accessor(indices, 'SCALAR', True), 'material': material,
        }]})
        doc['nodes'][node(name, parent)]['mesh'] = mesh

    bones: dict[str, dict[str, int]] = {}

    def bone(name: str, parent: int, offset: tuple) -> int:
        result = node(name, parent, offset)
        bones[name] = {'node': result}
        return result

    hips = bone('hips', 0, (0, 0.94, 0))
    spine = bone('spine', hips, (0, 0.16, 0))
    chest = bone('chest', spine, (0, 0.20, 0))
    neck = bone('neck', chest, (0, 0.18, 0))
    head = bone('head', neck, (0, 0.10, 0))
    box('pelvis', hips, (0, 0.025, 0), (0.29, 0.16, 0.20), 1)
    box('torso', spine, (0, 0.085, 0), (0.36, 0.29, 0.21))
    box('chest light', chest, (0, 0.045, 0.115), (0.15, 0.09, 0.022), 2)
    box('neck joint', neck, (0, 0.01, 0), (0.12, 0.10, 0.12), 1)
    box('head shell', head, (0, 0.12, 0), (0.35, 0.30, 0.34))
    for side, direction in (('left', 1), ('right', -1)):
        upper = bone(side + 'UpperArm', chest, (direction * 0.22, 0.045, 0))
        lower = bone(side + 'LowerArm', upper, (direction * 0.27, 0, 0))
        hand = bone(side + 'Hand', lower, (direction * 0.24, 0, 0))
        box(side + 'upper arm', upper, (direction * 0.13, 0, 0), (0.23, 0.105, 0.11))
        box(side + 'elbow', lower, (0, 0, 0), (0.085, 0.095, 0.10), 1)
        box(side + 'forearm', lower, (direction * 0.13, 0, 0), (0.18, 0.11, 0.12))
        box(side + 'hand', hand, (direction * 0.07, 0, 0), (0.12, 0.12, 0.085), 2)
        thigh = bone(side + 'UpperLeg', hips, (direction * 0.105, -0.055, 0))
        shin = bone(side + 'LowerLeg', thigh, (0, -0.405, 0))
        foot = bone(side + 'Foot', shin, (0, -0.40, 0))
        bone(side + 'Toes', foot, (0, -0.02, 0.14))
        box(side + 'thigh', thigh, (0, -0.21, 0), (0.13, 0.32, 0.15))
        box(side + 'knee', shin, (0, 0, 0), (0.12, 0.095, 0.12), 1)
        box(side + 'shin', shin, (0, -0.205, 0), (0.12, 0.32, 0.14))
        box(side + 'foot', foot, (0, -0.025, 0.07), (0.15, 0.095, 0.27), 2)
    neutral, indices = face_geometry()
    targets = []
    for preset in PRESETS:
        shape, _ = face_geometry(preset)
        delta = [[a - b for a, b in zip(new, old)] for new, old in zip(shape, neutral)]
        targets.append({'POSITION': accessor(delta, 'VEC3')})
    mesh = len(doc['meshes'])
    doc['meshes'].append({'name': 'expressive face', 'weights': [0] * len(PRESETS),
        'extras': {'targetNames': list(PRESETS)}, 'primitives': [{
        'attributes': {'POSITION': accessor(neutral, 'VEC3'), 'NORMAL': accessor([[0, 0, 1]] * len(neutral), 'VEC3')},
        'indices': accessor(indices, 'SCALAR', True), 'material': 3, 'targets': targets}]})
    face = node('face morphs', head)
    doc['nodes'][face]['mesh'] = mesh
    doc['extensions'] = {'VRMC_vrm': {
        'specVersion': '1.0',
        'meta': {'name': 'Zara Test Bot', 'version': '1.0.0', 'authors': ['Zara Companion contributors'],
                 'copyrightInformation': 'Original generated test geometry, CC0-1.0.',
                 'licenseUrl': 'https://vrm.dev/licenses/1.0/', 'avatarPermission': 'everyone',
                 'commercialUsage': 'corporation', 'creditNotation': 'unnecessary',
                 'allowExcessivelyViolentUsage': True, 'allowExcessivelySexualUsage': True,
                 'allowPoliticalOrReligiousUsage': True, 'allowAntisocialOrHateUsage': True,
                 'allowRedistribution': True, 'modification': 'allowModificationRedistribution',
                 'otherLicenseUrl': 'https://creativecommons.org/publicdomain/zero/1.0/'},
        'humanoid': {'humanBones': bones},
        'firstPerson': {'meshAnnotations': []},
        'expressions': {'preset': {name: {'morphTargetBinds': [{'node': face, 'index': i, 'weight': 1}],
            'isBinary': False} for i, name in enumerate(PRESETS)}},
    }}
    doc['buffers'] = [{'byteLength': len(binary)}]
    payload = json.dumps(doc, separators=(',', ':'), allow_nan=False).encode()
    payload += b' ' * (-len(payload) % 4)
    binary.extend(b'\0' * (-len(binary) % 4))
    length = 12 + 8 + len(payload) + 8 + len(binary)
    return (struct.pack('<5I', 0x46546c67, 2, length, len(payload), 0x4e4f534a) + payload
            + struct.pack('<2I', len(binary), 0x004e4942) + binary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    data = build_vrm()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    receipt = {'name': 'Zara Test Bot', 'version': '1.0.0', 'vrm_version': '1.0',
               'license': 'CC0-1.0', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
               'origin': 'Original deterministic geometry; no downloaded model, textures, or motions.',
               'expressions': list(PRESETS)}
    args.output.with_suffix('.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
