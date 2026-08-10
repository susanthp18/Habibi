/**
 * Rasterise public/favicon.svg into the PNG sizes browsers and OSes can't take as SVG.
 *
 *   node scripts/gen-icons.mjs        (or: npm run icons)
 *
 * Deliberately not part of `build`: the PNGs are committed artefacts, so CI never needs
 * sharp's native binaries. Re-run this by hand whenever favicon.svg changes.
 */
import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const publicDir = join(dirname(fileURLToPath(import.meta.url)), "..", "public");
const source = join(publicDir, "favicon.svg");

// Sizes, not a loop over a range: each of these exists for a specific consumer.
const TARGETS = [
  { file: "apple-touch-icon.png", size: 180 }, // iOS home screen
  { file: "icon-192.png", size: 192 }, // Android / PWA install
  { file: "icon-512.png", size: 512 }, // PWA splash
];

let sharp;
try {
  ({ default: sharp } = await import("sharp"));
} catch {
  console.error("sharp is not installed. Run `npm install` (it is a devDependency) and try again.");
  process.exit(1);
}

const svg = await readFile(source);

for (const { file, size } of TARGETS) {
  // The SVG's rounded plate leaves transparent corners. iOS composites the icon onto its
  // own rounded mask, and a transparent edge there reads as a rendering fault — so the
  // raster gets an opaque brand-navy backdrop rather than alpha.
  const png = await sharp(svg, { density: 384 })
    .resize(size, size, { fit: "contain", background: "#071A33" })
    .flatten({ background: "#071A33" })
    .png({ compressionLevel: 9 })
    .toBuffer();

  await writeFile(join(publicDir, file), png);
  console.log(`wrote public/${file} (${size}x${size}, ${png.length} bytes)`);
}
