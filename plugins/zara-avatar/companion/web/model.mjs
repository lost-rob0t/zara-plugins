const LIMIT = 32 * 1024 * 1024;
function need(ok) { if (!ok) throw new Error('unsupported_or_unsafe_model'); }
function integer(value, max) { return Number.isInteger(value) && value >= 0 && value <= max; }
function array(doc, key, max) {
  const result = doc[key] ?? [];
  need(Array.isArray(result) && result.length <= max);
  return result;
}
function imageSize(bytes, mime) {
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (mime === 'image/png') {
    need(bytes.length >= 24 && v.getUint32(0) === 0x89504e47 && v.getUint32(4) === 0x0d0a1a0a
      && v.getUint32(12) === 0x49484452);
    return [v.getUint32(16), v.getUint32(20)];
  }
  need(mime === 'image/jpeg' && bytes[0] === 0xff && bytes[1] === 0xd8);
  let p = 2;
  for (let n = 0; n < 2048 && p + 4 <= bytes.length; n++) {
    need(bytes[p++] === 0xff);
    while (p < bytes.length && bytes[p] === 0xff) p++;
    const marker = bytes[p++];
    need(p + 2 <= bytes.length && marker !== 0xda && marker !== 0xd9);
    const size = v.getUint16(p);
    need(size >= 2 && p + size <= bytes.length);
    if ([0xc0, 0xc1, 0xc2].includes(marker)) {
      need(size >= 7);
      return [v.getUint16(p + 5), v.getUint16(p + 3)];
    }
    p += size;
  }
  throw new Error('unsupported_or_unsafe_model');
}

export function validateModel(data) {
  need(data instanceof ArrayBuffer && data.byteLength >= 32 && data.byteLength <= LIMIT);
  const v = new DataView(data);
  need(v.getUint32(0, true) === 0x46546c67 && v.getUint32(4, true) === 2
    && v.getUint32(8, true) === data.byteLength);
  const length = v.getUint32(12, true);
  need(length > 0 && length <= 1024 * 1024 && length % 4 === 0
    && 28 + length <= data.byteLength && v.getUint32(16, true) === 0x4e4f534a);
  const doc = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array(data, 20, length)));
  need(doc?.asset?.version === '2.0');
  const version = doc.extensions?.VRMC_vrm?.specVersion === '1.0' ? '1.0' : doc.extensions?.VRM ? '0.x' : null;
  need(version !== null);
  const bin = 28 + length, binLength = v.getUint32(20 + length, true);
  need(v.getUint32(24 + length, true) === 0x004e4942 && bin + binLength === data.byteLength);
  const required = array(doc, 'extensionsRequired', 32);
  need(!required.some(name => ['KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_texture_basisu'].includes(name)));
  const buffers = array(doc, 'buffers', 1);
  need(buffers.length === 1 && !Object.hasOwn(buffers[0], 'uri')
    && integer(buffers[0].byteLength, binLength) && binLength - buffers[0].byteLength <= 3);
  const views = array(doc, 'bufferViews', 4096);
  for (const item of views) need(item.buffer === 0 && integer(item.byteOffset ?? 0, binLength)
    && integer(item.byteLength, binLength) && (item.byteOffset ?? 0) + item.byteLength <= buffers[0].byteLength
    && !item.extensions?.EXT_meshopt_compression);
  let elements = 0;
  for (const item of array(doc, 'accessors', 4096)) {
    need(integer(item.count, 2_000_000));
    elements += item.count;
  }
  need(elements <= 2_000_000);
  for (const item of array(doc, 'meshes', 128)) {
    for (const primitive of array(item, 'primitives', 32)) {
      need(!primitive.extensions?.KHR_draco_mesh_compression);
      array(primitive, 'targets', 64);
    }
  }
  array(doc, 'materials', 128);
  for (const skin of array(doc, 'skins', 32)) array(skin, 'joints', 128);
  const nodes = array(doc, 'nodes', 1024), parents = new Set(), visiting = new Set(), depths = new Map();
  function visit(i, depth) {
    need(depth <= 64 && !visiting.has(i));
    if (depths.has(i)) return depths.get(i);
    visiting.add(i);
    let height = 0;
    for (const child of array(nodes[i], 'children', 1024)) {
      need(integer(child, nodes.length - 1) && !parents.has(child));
      parents.add(child); height = Math.max(height, 1 + visit(child, depth + 1));
    }
    need(height <= 64);
    visiting.delete(i); depths.set(i, height);
    return height;
  }
  for (let i = 0; i < nodes.length; i++) visit(i, 0);
  let pixels = 0;
  for (const image of array(doc, 'images', 64)) {
    need(!Object.hasOwn(image, 'uri') && integer(image.bufferView, views.length - 1));
    const view = views[image.bufferView];
    const [w, h] = imageSize(new Uint8Array(data, bin + (view.byteOffset ?? 0), view.byteLength), image.mimeType);
    need(integer(w, 4096) && integer(h, 4096) && w > 0 && h > 0);
    pixels += w * h;
  }
  need(pixels <= 32 * 1024 * 1024);
  return { version, bytes: data.byteLength, nodes: nodes.length };
}
