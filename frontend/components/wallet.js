/* Wallet header: network selection, connection, and a live proof-of-read.
 *
 * Three states, and none of them is an error:
 *
 *   read-only   no EIP-1193 provider present. Everything that does not need a
 *               signature still works. This is a first-class mode, not a fallback --
 *               wallet writes depend on MetaMask plus the GenLayer Snap, and a viewer
 *               that dies without them would be useless on most machines.
 *   available   a provider exists but is not connected yet.
 *   connected   address in hand, writes possible on this network.
 *
 * The live `ruling_count` read is deliberate: it proves the read client is talking to
 * the real deployment before any wallet is involved, so a failure here is
 * unambiguously a network problem rather than a wallet problem.
 */

import {
  explorerTx, loadNetworks, read, readClient, usableNetworks, walletAvailable,
  walletClient, sdkVersion,
} from "../lib/gl.js";

const state = {
  cfg: null,
  netKey: null,
  net: null,
  reader: null,
  writer: null,
  address: null,
  status: "read-only",
  error: null,
  rulingCount: null,
};

const listeners = new Set();
export function onWalletChange(fn) { listeners.add(fn); }
function emit() { for (const fn of listeners) fn({ ...state }); }

export function walletState() { return { ...state }; }

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const short = (a) => (a ? `${a.slice(0, 6)}…${a.slice(-4)}` : "");

function render(host) {
  const n = state.net;
  const nets = usableNetworks(state.cfg);
  const options = nets.map(({ key, label }) =>
    `<option value="${esc(key)}"${key === state.netKey ? " selected" : ""}>${esc(label)}</option>`
  ).join("");

  const unusable = Object.entries(state.cfg.networks)
    .filter(([, x]) => !x.usable).map(([k]) => k);

  const badge = state.status === "connected"
    ? `<span class="pill ok" title="${esc(state.address)}">${esc(short(state.address))}</span>`
    : state.status === "available"
      ? `<button id="w-connect" type="button">Connect wallet</button>`
      : `<span class="pill" title="No EIP-1193 provider. Reads and reports still work.">read-only</span>`;

  const writeNote = n && !n.wallet_writes
    ? `<span class="note">wallet writes off on ${esc(n.label)}${n.wallet_note ? ` — ${esc(n.wallet_note)}` : ""}</span>`
    : "";

  host.innerHTML = `
    <div class="bar">
      <label class="sr">Network</label>
      <select id="w-net">${options}</select>
      ${badge}
      ${state.status === "connected" && n.faucet === "sim"
        ? `<button id="w-fund" type="button">Faucet</button>` : ""}
      <span class="grow"></span>
      <span class="note mono">chain ${esc(n?.chain_id ?? "?")} · genlayer-js ${esc(sdkVersion())}</span>
    </div>
    <div class="bar sub">
      <span class="note">probe <a href="#" data-c="probe">${esc(short(n?.contracts?.probe?.address))}</a></span>
      <span class="note">registry <a href="#" data-c="registry">${esc(short(n?.contracts?.registry?.address))}</a></span>
      <span class="note">escrow <a href="#" data-c="escrow">${esc(short(n?.contracts?.escrow?.address))}</a></span>
      <span class="note">rulings on chain: <b>${state.rulingCount ?? "…"}</b></span>
      ${writeNote}
      ${unusable.length ? `<span class="note">no deployment: ${esc(unusable.join(", "))}</span>` : ""}
    </div>
    ${state.error ? `<div class="bar err-line">${esc(state.error)}</div>` : ""}`;

  host.querySelector("#w-net").addEventListener("change", async (e) => {
    await selectNetwork(host, e.target.value);
  });
  const btn = host.querySelector("#w-connect");
  if (btn) btn.addEventListener("click", () => connect(host));
  const fund = host.querySelector("#w-fund");
  if (fund) fund.addEventListener("click", () => fundAccount(host));
}

async function refreshReads(host) {
  state.rulingCount = null;
  try {
    const probe = state.net.contracts.probe;
    if (probe) {
      const n = await read(state.reader, probe.address, "ruling_count", []);
      state.rulingCount = Number(n);
    }
  } catch (e) {
    state.error = `read failed on ${state.netKey}: ${e.message}`;
  }
  render(host);
  emit();
}

async function selectNetwork(host, key) {
  state.netKey = key;
  state.net = state.cfg.networks[key];
  state.error = null;
  state.writer = null;
  state.address = null;
  state.status = walletAvailable() ? "available" : "read-only";
  try {
    state.reader = await readClient(state.net);
  } catch (e) {
    state.error = `client init failed: ${e.message}`;
  }
  render(host);
  emit();
  await refreshReads(host);
}

async function connect(host) {
  state.error = null;
  render(host);
  try {
    const { client, address } = await walletClient(state.net);
    state.writer = client;
    state.address = address;
    state.status = "connected";
  } catch (e) {
    // Rejection, a missing Snap, or a wrong network all land here. Stay usable.
    state.error = `connect failed: ${e.message}`;
    state.status = walletAvailable() ? "available" : "read-only";
  }
  render(host);
  emit();
}

async function fundAccount(host) {
  state.error = null;
  try {
    await state.writer.fundAccount({ address: state.address, amount: 10n ** 20n });
  } catch (e) {
    state.error = `faucet failed: ${e.message}`;
  }
  render(host);
  emit();
}

export async function mountWallet(host, { base = ".." } = {}) {
  state.cfg = await loadNetworks(base);
  const usable = usableNetworks(state.cfg);
  const preferred = usable.find((n) => n.key === state.cfg.default) || usable[0];
  if (!preferred) {
    host.innerHTML = `<div class="bar err-line">No network has a current deployment.
      Run <code>python scripts/export_frontend_config.py</code> after deploying.</div>`;
    return walletState();
  }
  await selectNetwork(host, preferred.key);
  return walletState();
}

export { explorerTx };
