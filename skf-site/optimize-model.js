/**
 * Optimize GLB: Draco compress meshes + smart texture compression
 * - Body skin & normal maps: keep PNG, resize to 2048px max
 * - Other color textures: JPEG q92, resize to 2048px max
 * - Tiny/flat textures (<10KB): keep as-is
 * Usage: node optimize-model.js
 */
const fs = require('fs');
const path = require('path');
const sharp = require('sharp');
const { processGlb } = require('gltf-pipeline');

const INPUT  = path.join(__dirname, 'acc-bmw-m4-gt3-evo/source/ACC BMW M4 GT3 EVO/ACC BMW M4 GT3 EVO.glb');
const OUTPUT = path.join(__dirname, 'public/models/acc-bmw-m4-gt3-evo/car-optimized.glb');
const MAX_SKIN_SIZE = 2048;     // body paint / livery textures
const MAX_OTHER_SIZE = 1024;    // detail, interior, normal maps
const JPEG_QUALITY = 90;

async function optimizeGlb() {
  console.log('Reading model...');
  const glb = fs.readFileSync(INPUT);
  console.log(`Original: ${(glb.length / 1024 / 1024).toFixed(2)} MB`);

  // ── Parse GLB structure ──
  const jsonChunkLength = glb.readUInt32LE(12);
  const jsonStr = glb.slice(20, 20 + jsonChunkLength).toString('utf8');
  const gltf = JSON.parse(jsonStr);

  const binOffset = 20 + jsonChunkLength;
  const binChunkLength = glb.readUInt32LE(binOffset);
  const binData = Buffer.from(glb.slice(binOffset + 8, binOffset + 8 + binChunkLength));

  if (!gltf.images || !gltf.images.length) {
    console.log('No images found, just applying Draco...');
    const result = await processGlb(glb, { dracoOptions: { compressionLevel: 7 } });
    fs.writeFileSync(OUTPUT, result.glb);
    console.log(`Done: ${(result.glb.length / 1024 / 1024).toFixed(2)} MB`);
    return;
  }

  console.log(`\nProcessing ${gltf.images.length} textures...`);

  // ── Compress each texture ──
  const newBuffers = []; // collect new buffer segments
  let newBinParts = [];
  let currentOffset = 0;

  // Copy non-image bufferViews first
  const imageBufferViewIndices = new Set(
    gltf.images.filter(i => i.bufferView !== undefined).map(i => i.bufferView)
  );

  // Build new binary: first copy all non-image buffer views
  const bvRemapping = {}; // old index → { newOffset, newLength }
  const newBufferViews = [];

  // Process non-image buffer views (keep as-is)
  for (let i = 0; i < gltf.bufferViews.length; i++) {
    if (imageBufferViewIndices.has(i)) continue;
    const bv = gltf.bufferViews[i];
    const data = binData.slice(bv.byteOffset, bv.byteOffset + bv.byteLength);

    // Align to 4 bytes
    const padding = (4 - (currentOffset % 4)) % 4;
    if (padding > 0) {
      newBinParts.push(Buffer.alloc(padding));
      currentOffset += padding;
    }

    bvRemapping[i] = { newIndex: newBufferViews.length, newOffset: currentOffset };
    const newBv = { ...bv, byteOffset: currentOffset };
    newBufferViews.push(newBv);
    newBinParts.push(data);
    currentOffset += data.length;
  }

  // ── Identify texture types from materials ──
  const normalMapTextureIndices = new Set();
  const metallicTextureIndices = new Set();
  const skinTextureIndices = new Set(); // body paint / main diffuse
  for (const mat of (gltf.materials || [])) {
    if (mat.normalTexture?.index !== undefined) normalMapTextureIndices.add(mat.normalTexture.index);
    const pbr = mat.pbrMetallicRoughness;
    if (pbr?.metallicRoughnessTexture?.index !== undefined) metallicTextureIndices.add(pbr.metallicRoughnessTexture.index);
    if (mat.occlusionTexture?.index !== undefined) metallicTextureIndices.add(mat.occlusionTexture.index);
    // Base color textures of the exterior are the "skin"
    if (pbr?.baseColorTexture?.index !== undefined) skinTextureIndices.add(pbr.baseColorTexture.index);
  }
  const normalMapImageIndices = new Set();
  const metallicImageIndices = new Set();
  const skinImageIndices = new Set();
  for (const texIdx of normalMapTextureIndices) {
    const tex = gltf.textures?.[texIdx];
    if (tex?.source !== undefined) normalMapImageIndices.add(tex.source);
  }
  for (const texIdx of metallicTextureIndices) {
    const tex = gltf.textures?.[texIdx];
    if (tex?.source !== undefined) metallicImageIndices.add(tex.source);
  }
  for (const texIdx of skinTextureIndices) {
    const tex = gltf.textures?.[texIdx];
    if (tex?.source !== undefined) skinImageIndices.add(tex.source);
  }
  console.log(`  ${normalMapImageIndices.size} normal maps, ${metallicImageIndices.size} metallic/AO, ${skinImageIndices.size} base color`);

  // Process image buffer views — smart compression per texture type
  let savedBytes = 0;
  for (let imgIdx = 0; imgIdx < gltf.images.length; imgIdx++) {
    const img = gltf.images[imgIdx];
    if (img.bufferView === undefined) continue;

    const bv = gltf.bufferViews[img.bufferView];
    const origData = binData.slice(bv.byteOffset, bv.byteOffset + bv.byteLength);
    const origSize = origData.length;

    // Skip tiny textures (<5KB) — already negligible
    if (origSize < 5120) {
      const padding = (4 - (currentOffset % 4)) % 4;
      if (padding > 0) { newBinParts.push(Buffer.alloc(padding)); currentOffset += padding; }
      bvRemapping[img.bufferView] = { newIndex: newBufferViews.length, newOffset: currentOffset };
      newBufferViews.push({ buffer: 0, byteOffset: currentOffset, byteLength: origData.length });
      img.bufferView = newBufferViews.length - 1;
      newBinParts.push(origData);
      currentOffset += origData.length;
      continue;
    }

    // Determine max size: body skin textures get 2048, everything else 1024
    const isSkin = skinImageIndices.has(imgIdx) && !normalMapImageIndices.has(imgIdx) && !metallicImageIndices.has(imgIdx);
    const maxSize = isSkin ? MAX_SKIN_SIZE : MAX_OTHER_SIZE;

    let compressed;
    try {
      let pipeline = sharp(origData);
      const meta = await pipeline.metadata();

      if (meta.width > maxSize || meta.height > maxSize) {
        pipeline = pipeline.resize(maxSize, maxSize, { fit: 'inside', withoutEnlargement: true });
      }

      if (meta.hasAlpha && meta.channels === 4) {
        // Keep alpha textures as optimized PNG
        compressed = await pipeline.png({ compressionLevel: 9 }).toBuffer();
        img.mimeType = 'image/png';
      } else {
        // Everything else: high-quality JPEG
        compressed = await pipeline.jpeg({ quality: JPEG_QUALITY, mozjpeg: true }).toBuffer();
        img.mimeType = 'image/jpeg';
      }
    } catch (e) {
      compressed = origData;
    }

    // Align to 4 bytes
    const padding = (4 - (currentOffset % 4)) % 4;
    if (padding > 0) {
      newBinParts.push(Buffer.alloc(padding));
      currentOffset += padding;
    }

    bvRemapping[img.bufferView] = { newIndex: newBufferViews.length, newOffset: currentOffset };
    newBufferViews.push({
      buffer: 0,
      byteOffset: currentOffset,
      byteLength: compressed.length,
    });
    img.bufferView = newBufferViews.length - 1;
    newBinParts.push(compressed);

    const saving = origSize - compressed.length;
    savedBytes += saving;
    const pct = ((saving / origSize) * 100).toFixed(0);
    if (origSize > 50000) {
      console.log(`  [${imgIdx}] ${(origSize/1024).toFixed(0)}KB → ${(compressed.length/1024).toFixed(0)}KB (${pct}% smaller)`);
    }

    currentOffset += compressed.length;
  }

  console.log(`\nTexture compression saved: ${(savedBytes / 1024 / 1024).toFixed(2)} MB`);

  // Remap all accessor/bufferView references
  for (const accessor of (gltf.accessors || [])) {
    if (accessor.bufferView !== undefined && bvRemapping[accessor.bufferView]) {
      accessor.bufferView = bvRemapping[accessor.bufferView].newIndex;
    }
  }
  // Remap sparse accessors
  for (const accessor of (gltf.accessors || [])) {
    if (accessor.sparse) {
      const si = accessor.sparse.indices;
      if (si && si.bufferView !== undefined && bvRemapping[si.bufferView]) {
        si.bufferView = bvRemapping[si.bufferView].newIndex;
      }
      const sv = accessor.sparse.values;
      if (sv && sv.bufferView !== undefined && bvRemapping[sv.bufferView]) {
        sv.bufferView = bvRemapping[sv.bufferView].newIndex;
      }
    }
  }

  // Update gltf structure
  gltf.bufferViews = newBufferViews;
  const newBin = Buffer.concat(newBinParts);
  gltf.buffers = [{ byteLength: newBin.length }];

  // ── Rebuild GLB ──
  const newJsonStr = JSON.stringify(gltf);
  const jsonBuf = Buffer.from(newJsonStr, 'utf8');
  // Pad JSON to 4-byte alignment
  const jsonPadding = (4 - (jsonBuf.length % 4)) % 4;
  const paddedJson = Buffer.concat([jsonBuf, Buffer.alloc(jsonPadding, 0x20)]);
  // Pad bin to 4-byte alignment
  const binPadding = (4 - (newBin.length % 4)) % 4;
  const paddedBin = Buffer.concat([newBin, Buffer.alloc(binPadding, 0x00)]);

  const totalSize = 12 + 8 + paddedJson.length + 8 + paddedBin.length;
  const result = Buffer.alloc(totalSize);

  // Header
  result.writeUInt32LE(0x46546C67, 0); // 'glTF'
  result.writeUInt32LE(2, 4);          // version
  result.writeUInt32LE(totalSize, 8);

  // JSON chunk
  result.writeUInt32LE(paddedJson.length, 12);
  result.writeUInt32LE(0x4E4F534A, 16); // 'JSON'
  paddedJson.copy(result, 20);

  // BIN chunk
  const binStart = 20 + paddedJson.length;
  result.writeUInt32LE(paddedBin.length, binStart);
  result.writeUInt32LE(0x004E4942, binStart + 4); // 'BIN\0'
  paddedBin.copy(result, binStart + 8);

  fs.writeFileSync(OUTPUT, result);
  console.log(`\nFinal size: ${(result.length / 1024 / 1024).toFixed(2)} MB`);
  console.log(`Saved to: ${OUTPUT}`);
}

optimizeGlb().catch(console.error);
