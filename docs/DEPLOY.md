# Deploying the dApp

Brightline's front end is static. It reads committed report artifacts over `fetch` and
talks to GenLayer directly from the browser through the vendored genlayer-js bundle.
There is no server, no API key, no database, and nothing to keep running.

That is a deliberate property, not a convenience: a report is only worth anything if a
reader can recompute it, so the page must not sit between them and the chain.

## Build

```bash
.venv/bin/python scripts/build_static.py     # -> dist/   (~920K)
```

The script regenerates the two machine-written inputs first — `frontend/networks.json`
from the CLI's own deployment record, and `reports/index.json` from the artifacts on
disk — then copies:

```
dist/index.html          redirect to frontend/
dist/frontend/           the app, verbatim (incl. vendor/genlayer-js.js)
dist/reports/*.json|md   the published reports and the re-test diff
dist/probes/ps_*.json    frozen probe manifests
dist/docs/*.md           limitations, results, verified-vs-assumed
```

`dist/` mirrors the repository's layout rather than flattening it, because every path
in the app is relative (`../reports/index.json`). The deployed site and
`scripts/serve.py` therefore serve identical URLs and there is no rewrite step to get
wrong.

Excluded: `.brightline/` (local dev keys), `reports/raw/` and `experiments/` (5.4 MB and
4.5 MB of raw receipts — evidence, kept in the repo, not page assets), `node_modules/`.
The build fails loudly if any of those appear in the output, or if any asset the index
references is missing.

## Verify before publishing

```bash
npm run test:dist        # builds dist/, serves only dist/, drives it in Chromium
```

Nine checks: the root redirect lands on the app, a report renders from the bundled
artifacts, the vendored SDK reads live studionet state, all four panels mount, probe
manifests shipped, and **no request 404s**. That last one is the reason this test
exists — `serve.py` serves the whole repository, so a file that was never copied into
`dist/` is invisible locally and fatal in production.

To eyeball it:

```bash
.venv/bin/python scripts/build_static.py --serve 8899    # http://127.0.0.1:8899/
```

## Host

Any static host works. Two requirements only:

1. **Serve over HTTPS.** MetaMask will not inject a provider on plain HTTP for a
   non-localhost origin, so the wallet path silently disappears.
2. **Serve `.js` as `text/javascript`.** The app is ES modules; a wrong MIME type makes
   the browser refuse the module graph. Every mainstream host does this already.

No SPA fallback or rewrite rule is needed — every URL is a real file.

```bash
# GitHub Pages, from a clean checkout
.venv/bin/python scripts/build_static.py
npx gh-pages -d dist

# Netlify / Cloudflare Pages / Vercel: publish directory = dist, build command =
# .venv/bin/python scripts/build_static.py  (or upload dist/ directly)
```

`dist/` is gitignored. It is a copy of files already in the repository and rebuilds in
about a second; committing it would create a second copy of every report that can go
stale without anyone noticing.

## What the deployed page can and cannot do

| | |
|---|---|
| Without a wallet | Reads every committed report and probe manifest, hashes a rule in-browser, and reads live registry/escrow state off studionet. This is the default state, not a degraded one. |
| With MetaMask + the `npm:genlayer-wallet-plugin` Snap | Publishes a report, opens and locks an escrow deal, and runs a live single-probe quick check. Studionet only. |
| Never | Runs the full 48-transaction panel. That is a CLI job: the browser cannot pin a validator model (genlayer-js 1.1.8 has no `simConfig`), so cross-model divergence cannot be measured there at all. The page says so where it matters. |

Bradbury stays read-only in the UI: `wallet_writes` is `false` for it in
`networks.json` and the wallet header states the reason rather than failing at signing
time. genlayer-py needed an explicit gas limit to land a write there and genlayer-js is
unverified on that network.

## Updating a deployment

Re-run the build. The two generated files are rebuilt every time, so a newly published
report or a fresh deployment address propagates with no manual editing. To refresh the
vendored SDK, `node scripts/vendor_sdk.mjs` first — its output is committed on purpose,
so that the dApp has no runtime CDN dependency.
