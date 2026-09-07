/* GenLayer client layer for the browser.
 *
 * Two clients by design, per the SDK's own guidance: an account-free client for reads
 * and a provider-backed client for writes. Reads must work with no wallet at all --
 * that is what makes the read-only/demo mode real rather than a degraded error state.
 *
 * genlayer-js is vendored into frontend/vendor/ rather than pulled from a CDN. Its
 * published ESM imports `viem` as a bare specifier, so a CDN load fans out into dozens
 * of module requests -- and one dropped request breaks the wallet path, which was
 * observed in testing when esm.sh closed a connection mid-fetch. The dApp still has no
 * build step to *run*; `node scripts/vendor_sdk.mjs` is a one-off step to *update* the
 * SDK, and its output is committed.
 *
 * Wallet writes go through MetaMask plus the `npm:genlayer-wallet-plugin` Snap --
 * `client.connect()` requests the Snap and issues wallet_addEthereumChain /
 * wallet_switchEthereumChain itself. That external dependency is the reason
 * `walletAvailable()` and the read-only path exist.
 */

const SDK_VERSION = "1.1.8";
// One bundle for the SDK and its chains: two bundles means two copies of viem, and a
// chain object from one is not the object the other expects.
const SDK_URL = "../vendor/genlayer-js.js";

let _sdk = null;
let _chains = null;
let _networks = null;

async function sdk() {
  if (!_sdk) {
    _sdk = await import(SDK_URL);
    _chains = _sdk.chains;
  }
  return { ..._sdk, chains: _chains };
}

/** Network + deployment config, exported from the CLI's own record. */
export async function loadNetworks(base = "..") {
  if (!_networks) {
    const res = await fetch(`${base}/frontend/networks.json`);
    if (!res.ok) throw new Error(`networks.json ${res.status}`);
    _networks = await res.json();
  }
  return _networks;
}

export function networkConfig(cfg, key) {
  const n = cfg.networks[key];
  if (!n) throw new Error(`unknown network ${key}`);
  return n;
}

/** Networks with a current deployment of all three contracts. */
export function usableNetworks(cfg) {
  return Object.entries(cfg.networks)
    .filter(([, n]) => n.usable)
    .map(([key, n]) => ({ key, ...n }));
}

export function explorerTx(net, hash) {
  return net.explorer_tx ? `${net.explorer_tx}${hash}` : null;
}

export function walletAvailable() {
  return typeof globalThis.ethereum !== "undefined";
}

async function chainFor(net) {
  const { chains } = await sdk();
  const chain = chains[net.js_chain];
  if (!chain) throw new Error(`genlayer-js has no chain "${net.js_chain}"`);
  return chain;
}

/** Account-free client. Every read in the app goes through this. */
export async function readClient(net) {
  const { createClient } = await sdk();
  return createClient({ chain: await chainFor(net) });
}

/**
 * Provider-backed client for writes.
 *
 * Order matters: the SDK's `connect()` performs the Snap request and the chain
 * add/switch, so it must run before any signature is attempted, and it must be given
 * the same network the client was built with.
 */
export async function walletClient(net) {
  if (!net.wallet_writes) {
    throw new Error(
      `wallet writes are not enabled for ${net.label}` +
      (net.wallet_note ? ` -- ${net.wallet_note}` : ""));
  }
  if (!walletAvailable()) throw new Error("no EIP-1193 provider found (MetaMask)");

  const provider = globalThis.ethereum;
  const accounts = await provider.request({ method: "eth_requestAccounts" });
  const address = Array.isArray(accounts) ? accounts[0] : accounts;
  if (!address) throw new Error("wallet returned no account");

  const { createClient } = await sdk();
  const client = createClient({
    chain: await chainFor(net), account: address, provider,
  });
  await client.connect(net.js_chain, "npm");
  return { client, address };
}

/**
 * Read a view method. Never needs a wallet.
 *
 * Retried with backoff: the hosted endpoint intermittently rejects browser reads under
 * load (observed as a CORS-less rate-limit response), and a demo should not show an
 * empty tile because one of several reads lost a race.
 */
export async function read(client, address, functionName, args = [], attempts = 3) {
  let last;
  for (let i = 0; i < attempts; i++) {
    try {
      return await client.readContract({ address, functionName, args });
    } catch (e) {
      last = e;
      if (i < attempts - 1) await new Promise((r) => setTimeout(r, 400 * (i + 1)));
    }
  }
  throw last;
}

/**
 * Submit a write and hand back the hash immediately, so the caller can render a
 * pending row before consensus finishes. Waiting is a separate concern.
 */
export async function write(client, address, functionName, args = [], opts = {}) {
  return client.writeContract({
    address, functionName, args,
    value: opts.value ?? 0n,
    ...(opts.consensusMaxRotations !== undefined
      ? { consensusMaxRotations: opts.consensusMaxRotations } : {}),
    ...(opts.leaderOnly ? { leaderOnly: true } : {}),
    ...(opts.simConfig ? { simConfig: opts.simConfig } : {}),
  });
}

export async function getTransaction(client, hash) {
  return client.getTransaction({ hash });
}

export function sdkVersion() {
  return SDK_VERSION;
}
