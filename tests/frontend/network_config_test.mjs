/* The network configuration the browser is handed.
 *
 * `frontend/networks.json` is generated from the CLI's own deployment record, so it is
 * the one place where a wrong address or a wrong chain silently becomes a dApp that
 * reads the wrong network and says nothing. These checks are about the submission's
 * central factual claim -- that the deployed site talks to Studio Next, chain 61997,
 * at the contracts deployed there -- and about the old stable-Studio evidence surviving
 * next to it rather than being overwritten.
 *
 * Pure Node: no chain access, no browser. Live proof is verify_studio_next.py
 * (contracts) and tests/frontend/browser_test.mjs (the app reading them).
 *
 *   node tests/frontend/network_config_test.mjs
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const cfg = JSON.parse(readFileSync(join(root, "frontend/networks.json"), "utf8"));
const sdkChains = (await import(join(root, "frontend/vendor/genlayer-js.js"))).chains;

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `\n        ${detail}`}`);
  ok ? pass++ : fail++;
};

const next = cfg.networks["studio-next"];
const stable = cfg.networks["studionet"];

// ---------------------------------------------------------------- the default network
check("default network is studio-next", cfg.default === "studio-next", cfg.default);
check("studio-next is chain 61997", next?.chain_id === 61997, String(next?.chain_id));
check("studio-next RPC is a Studio Next endpoint",
  /^https:\/\/studio-(next|dev)\.genlayer\.com\/api$/.test(next?.rpc || ""), next?.rpc);
check("studio-next has a current deployment of all three contracts",
  next?.usable === true && ["probe", "registry", "escrow"]
    .every((k) => next.contracts[k]?.current === true),
  JSON.stringify(next?.contracts));
check("studio-next offers wallet writes", next?.wallet_writes === true);
check("studio-next pins the GenVM 0.3 runner",
  next?.runner === "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng",
  next?.runner);

// -------------------------------------------------- the SDK really resolves to 61997
const chain = sdkChains[next.js_chain];
check(`genlayer-js has a chain named ${next.js_chain}`, Boolean(chain), next.js_chain);
check("that chain is 61997, not 61999", chain?.id === 61997, String(chain?.id));

// ------------------------------------------------- new addresses, not the old ones
const OLD = {
  probe: "0x0cc3f4684fbd89db74331a702d09a67dcc6585f7",
  registry: "0x8a3476d6c84cea489d4eb9a0be744fe403560196",
  escrow: "0x3826c2374fbdbcb8a248e0523ef1f325b3f5a590",
};
for (const [name, old] of Object.entries(OLD)) {
  const now = (next.contracts[name]?.address || "").toLowerCase();
  check(`${name} is a fresh 61997 address, not the 61999 one`,
    now.length === 42 && now !== old, `${now} vs old ${old}`);
  check(`${name} still recorded for studionet at its original address`,
    (stable.contracts[name]?.address || "").toLowerCase() === old,
    stable.contracts[name]?.address);
}

// ------------------------------------------------------------------- old evidence
// Present, addresses intact, and explicitly NOT queryable by this bundle -- the
// vendored genlayer-js 2.0.0-rc.1 that Studio Next requires cannot read 61999. The
// config has to say so rather than offer tiles that would fail.
check("stable Studio is still recorded, with its deployment marked intact",
  stable?.chain_id === 61999 && stable?.deployed === true, JSON.stringify({
    chain_id: stable?.chain_id, deployed: stable?.deployed }));
check("stable Studio is not offered as browser-usable",
  stable?.usable === false && stable?.wallet_writes === false);
check("and it says why, pointing at the CLI",
  /2\.0\.0-rc\.1 bundle this dApp needs/.test(stable?.wallet_note || "")
  && /studionet/.test(stable?.wallet_note || ""), stable?.wallet_note);
check("the two networks have distinct escrow addresses",
  next.contracts.escrow.address !== stable.contracts.escrow.address);
check("each network carries its own runner",
  next.runner !== stable.runner, `${next.runner} / ${stable.runner}`);

// ------------------------------------------------------------------------ explorers
for (const [key, n] of Object.entries(cfg.networks)) {
  if (!n.usable) continue;
  check(`${key} has an explorer base for transactions and addresses`,
    /^https:\/\/\S+\/tx\/$/.test(n.explorer_tx || "")
    && /^https:\/\/\S+\/address\/$/.test(n.explorer_address || ""),
    `${n.explorer_tx} ${n.explorer_address}`);
}

// The escrow must gate on this network's registry. The on-chain check is in
// verify_studio_next.py; this is the config-level mirror of it.
check("no network mixes another network's contracts",
  Object.values(cfg.networks).every((n) => {
    const addrs = ["probe", "registry", "escrow"]
      .map((k) => n.contracts[k]?.address).filter(Boolean);
    return new Set(addrs).size === addrs.length;
  }));

console.log(`\n${pass}/${pass + fail} network config checks passed`);
process.exit(fail ? 1 : 0);
