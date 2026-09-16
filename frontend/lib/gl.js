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
 * Wallet writes go through MetaMask plus the `npm:genlayer-wallet-plugin` Snap.
 * `client.connect()` requests the Snap; the chain add/switch is done here instead, for
 * the reasons in `walletClient`. That external dependency is why `walletAvailable()`
 * and the read-only path exist.
 *
 * Vendored at 2.0.0-rc.1 because Studio Next (chain 61997) is consensus v0.6: the
 * consensus contract takes one packed tuple and refuses any transaction without a
 * quoted fee distribution, which 1.x does not send. `writeContract` resolves that quote
 * itself when `fees` is omitted, so nothing in the app has to price transactions.
 */

const SDK_VERSION = "2.0.0-rc.1";
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

/** Origin of the explorer, derived from the configured tx URL. */
function explorerOrigin(net) {
  try {
    return net.explorer_tx ? new URL(net.explorer_tx).origin : null;
  } catch { return null; }
}

/**
 * The SDK's chain object, with two fields taken from networks.json instead.
 *
 * `rpcUrls`: chain 61997 answers on two hostnames -- genlayer-js names
 * studio-dev.genlayer.com, the network is deployed as studio-next.genlayer.com, and both
 * report eth_chainId 0xf22d over shared state. Pinning the configured host means the
 * endpoint the UI displays is the endpoint it actually reads, and the browser and the
 * CLI that deployed the contracts agree.
 *
 * `blockExplorers`: genlayer-js sets this to undefined for 61997. Left that way,
 * `connect()` builds `blockExplorerUrls: [undefined]` and hands it to MetaMask, which
 * validates that field. An explorer does index 61997, so supply it.
 */
async function chainFor(net) {
  const { chains } = await sdk();
  const base = chains[net.js_chain];
  if (!base) throw new Error(`genlayer-js has no chain "${net.js_chain}"`);
  const origin = explorerOrigin(net);
  return {
    ...base,
    ...(net.rpc ? { rpcUrls: { default: { http: [net.rpc] } } } : {}),
    ...(base.blockExplorers || !origin
      ? {}
      : { blockExplorers: { default: { name: "GenLayer Explorer", url: origin } } }),
  };
}

/** The chain id the SDK will actually transact against, for display and for tests. */
export async function chainIdFor(net) {
  return (await chainFor(net)).id;
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
  const chain = await chainFor(net);
  const client = createClient({ chain, account: address, provider });

  // Add and switch the chain ourselves, before connect(). Two reasons, both about
  // `connect()` reaching for its own hardcoded chain table rather than ours: it would
  // register the chain under the SDK's RPC host instead of the configured one, and for
  // 61997 it passes `blockExplorerUrls: [undefined]` because its table has no explorer
  // for that chain. Once the wallet is already on the right chain, connect() skips that
  // branch entirely and only does the part we want it for -- requesting the Snap.
  const chainIdHex = `0x${chain.id.toString(16)}`;
  if (await provider.request({ method: "eth_chainId" }) !== chainIdHex) {
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [{
        chainId: chainIdHex,
        chainName: chain.name,
        rpcUrls: chain.rpcUrls.default.http,
        nativeCurrency: chain.nativeCurrency,
        ...(chain.blockExplorers
          ? { blockExplorerUrls: Object.values(chain.blockExplorers).map((e) => e.url) }
          : {}),
      }],
    });
    await provider.request({
      method: "wallet_switchEthereumChain", params: [{ chainId: chainIdHex }],
    });
  }
  await client.connect(net.js_chain, "npm");
  // connect() assigns its own table entry to client.chain, which would move writes onto
  // the SDK's RPC host. Put the configured chain back so every call in the session goes
  // to the endpoint the UI names.
  client.chain = chain;
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
  // Consensus v0.6 rejects a transaction whose fee deposit is zero
  // (`FeeValueMustBeNonZero`), at the EVM layer, before GenVM runs. `writeContract`
  // only prices a transaction when it is handed a fee distribution: with `fees` omitted
  // it takes the all-zero default, decides no deposit is needed, and sends 0. So quote
  // first. One extra read per write, and it returns a zero quote by itself on a chain
  // whose fee policy is disabled, so this is correct on both Studio generations.
  const fees = opts.fees
    ?? (typeof client.estimateTransactionFees === "function"
      ? await client.estimateTransactionFees()
      : undefined);
  return client.writeContract({
    address, functionName, args,
    value: opts.value ?? 0n,
    ...(fees ? { fees } : {}),
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
