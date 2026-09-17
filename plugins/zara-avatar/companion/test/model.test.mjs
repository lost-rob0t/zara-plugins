import test from 'node:test';
import assert from 'node:assert/strict';
import { validateModel } from '../web/model.mjs';

function glb(change = {}) {
  const json = { asset: { version: '2.0' }, extensions: { VRMC_vrm: { specVersion: '1.0' } },
    nodes: [{}], meshes: [], buffers: [{ byteLength: 4 }], ...change };
  const text = new TextEncoder().encode(JSON.stringify(json));
  const size = Math.ceil(text.length / 4) * 4;
  const data = new ArrayBuffer(12 + 8 + size + 8 + 4);
  const view = new DataView(data);
  view.setUint32(0, 0x46546c67, true); view.setUint32(4, 2, true); view.setUint32(8, data.byteLength, true);
  view.setUint32(12, size, true); view.setUint32(16, 0x4e4f534a, true);
  new Uint8Array(data, 20, size).fill(32); new Uint8Array(data, 20, text.length).set(text);
  view.setUint32(20 + size, 4, true); view.setUint32(24 + size, 0x004e4942, true);
  return data;
}

test('accepts bounded embedded VRM 1 and VRM 0 GLB containers', () => {
  assert.equal(validateModel(glb()).version, '1.0');
  assert.equal(validateModel(glb({ extensions: { VRM: { specVersion: '0.0' } } })).version, '0.x');
});

test('rejects truncation, wrong container, no VRM and external resource URLs', () => {
  for (const data of [new ArrayBuffer(4), glb().slice(0, 24), glb({ extensions: {} }),
    glb({ buffers: [{ uri: 'https://evil.invalid/a.bin', byteLength: 4 }] }),
    glb({ images: [{ uri: 'file:///private.png' }] }),
    glb({ extensionsRequired: ['KHR_draco_mesh_compression'] })]) {
    assert.throws(() => validateModel(data));
  }
});

test('rejects hostile graph and geometry budgets before GPU allocation', () => {
  assert.throws(() => validateModel(glb({ nodes: Array(1025).fill({}) })));
  assert.throws(() => validateModel(glb({ accessors: [{ count: 9_000_000 }] })));
  assert.throws(() => validateModel(glb({ nodes: [{ children: [0] }] })));
  assert.throws(() => validateModel(glb({ nodes: [{ children: [1] }, { children: [0] }] })));
  assert.throws(() => validateModel(glb({ nodes: [{ children: [99] }] })));
  assert.throws(() => validateModel(glb({ nodes: [{ children: [1, 1] }, {}] })));
  assert.throws(() => validateModel(glb({ nodes: Array.from({ length: 100 }, (_, i) => i ? { children: [i - 1] } : {}) })));
});

test('rejects oversized, unsupported and invalid image buffers before decoding', () => {
  assert.throws(() => validateModel(glb({ images: [{ bufferView: 0, mimeType: 'image/png' }],
    bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: 4 }] })));
  assert.throws(() => validateModel(glb({ images: [{ bufferView: 0, mimeType: 'image/ktx2' }] })));
});
