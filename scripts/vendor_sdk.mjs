/* Bundle genlayer-js into frontend/vendor/ so the dApp has no runtime CDN dependency.
 *
 * Why this exists: genlayer-js's published ESM imports `viem` as a bare specifier, so a
 * browser loading it from a CDN pulls dozens of separate module requests. One dropped
 * request breaks the wallet path — observed in testing when esm.sh closed a connection
 * mid-fetch. On a demo stage that is an unacceptable failure mode.
 *
 * The viewer still has no build step to *run*; this is a one-off vendoring step to
 * *update* the SDK, and its output is committed.
 *
 *   node scripts/vendor_sdk.mjs
 */
import { build } from "esbuild";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outdir = join(root, "frontend", "vendor");
mkdirSync(outdir, { recursive: true });

const version = JSON.parse(
  readFileSync(join(root, "node_modules/genlayer-js/package.json"), "utf8")).version;

// ONE bundle, not two. Bundling the SDK and its chains separately gives each its own
// copy of viem, and a chain object from one copy is not the object the other copy
// expects -- the client silently fails to talk to the network. A single entry that
// re-exports both keeps one shared instance.
const entryFile = join(outdir, ".entry.mjs");
writeFileSync(entryFile, [
  'export * from "genlayer-js";',
  'export * as chains from "genlayer-js/chains";',
].join("\n"));

const res = await build({
  entryPoints: [entryFile], outfile: join(outdir, "genlayer-js.js"),
  bundle: true, format: "esm", platform: "browser", target: "es2022",
  minify: true, sourcemap: false, legalComments: "none",
});
if (res.errors?.length) throw new Error(JSON.stringify(res.errors));
rmSync(entryFile, { force: true });
console.log("bundled genlayer-js + chains -> frontend/vendor/genlayer-js.js");
console.log(`genlayer-js ${version} vendored`);
