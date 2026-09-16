"""Deploy-time adapter: the audited contracts, expressed for GenVM 0.3.

Stable Studio (61999) runs GenVM 0.2; Studio Next (61997) runs v0.3.0-rc7. The two are
not source-compatible, and a contract file cannot satisfy both: the runner is pinned by
a single `Depends` header, and each network rejects the other's runner outright
(`invalid_contract runner malformed`).

The choice was between a second copy of each contract and a mechanical transform. This
is the transform. `contracts/*.py` stays byte-identical to the source every published
number was measured against -- no shim, no version branch inside consensus-critical
code -- and the Studio Next deployment is derived from it here, where the whole diff is
one readable table and is unit-tested against the real contracts.

What GenVM 0.3 changed, all of it namespace movement rather than behaviour:

    py-genlayer:1jb45aa8...  ->  py-genlayer:5jycge4q8...   the runner itself
    gl.Contract              ->  gl.contract.Contract
    @gl.contract_interface   ->  @gl.contract.interface
    gl.vm.run_nondet_unsafe  ->  gl.vm.run_nondet
    gl.message_raw           ->  gl.message.datetime
    from genlayer import *   no longer re-exports gl, TreeMap, DynArray or the int types

`gl.public.*`, `gl.vm.UserError`, `gl.vm.Return`, `gl.vm.Result`, `gl.message.*`,
`gl.storage.inmem_allocate` and `gl.nondet.exec_prompt` are unchanged -- checked
attribute by attribute against the live 61997 runner, not assumed.

The one behavioural note: 0.2's `gl.message_raw["datetime"]` is already a string, while
0.3's `gl.message.datetime` is a datetime, so the transform wraps it in `str()`. Every
use is a display timestamp stored on a record (`ts`, `ts_opened`, `ts_locked`); none is
compared, parsed or gated on, so the formatting difference cannot change a decision.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The runner every published measurement ran against, and the one Studio Next wants.
# Both are pinned hashes: GenLayer networks reject `py-genlayer:test` and
# `py-genlayer:latest`, and a floating runner would make a report unreproducible anyway.
RUNNER_V02 = "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6"
RUNNER_V03 = "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng"

# Injected directly after `from genlayer import *`, which in 0.3 no longer carries them.
PREAMBLE = """import genlayer as gl
from genlayer.storage import TreeMap, DynArray, allow as allow_storage
from genlayer.types import *
"""

# Ordered, and every pattern is anchored so a second pass is a no-op: `gl.Contract` must
# not rewrite the `gl.contract.Contract` it just produced.
SUBSTITUTIONS: list[tuple[str, str]] = [
    (r"@gl\.contract_interface\b", "@gl.contract.interface"),
    (r"\bgl\.Contract\b", "gl.contract.Contract"),
    (r"\bgl\.vm\.run_nondet_unsafe\b", "gl.vm.run_nondet"),
    (r"""gl\.message_raw\[(?:"|')datetime(?:"|')\]""", "str(gl.message.datetime)"),
]

WILDCARD = "from genlayer import *"


def to_genvm03(source: str) -> str:
    """Rewrite a GenVM 0.2 contract into its GenVM 0.3 equivalent.

    Raises if the source does not look like one of ours, because silently returning
    unchanged text would deploy a contract that cannot run and report it as a success.
    """
    if RUNNER_V03 in source:
        return source
    if RUNNER_V02 not in source:
        raise ValueError(
            f"source does not pin {RUNNER_V02}; refusing to guess its runner")
    if WILDCARD not in source:
        raise ValueError(f"source has no {WILDCARD!r} line to anchor the 0.3 preamble")

    out = source.replace(RUNNER_V02, RUNNER_V03, 1)
    out = out.replace(WILDCARD, WILDCARD + "\n" + PREAMBLE, 1)
    for pattern, repl in SUBSTITUTIONS:
        out = re.sub(pattern, repl, out)

    # A leftover 0.2 name means the table above has fallen behind the contracts, which
    # would surface as a GenVM NameError after a deploy transaction has been paid for.
    stale = [n for n in ("gl.message_raw", "gl.contract_interface", "run_nondet_unsafe")
             if n in out]
    if stale:
        raise ValueError(f"unported GenVM 0.2 names remain: {stale}")
    return out


def source_for(network: str, path: str | Path) -> str:
    """The contract source to deploy on `network`, adapted only where required."""
    text = Path(path).read_text()
    return to_genvm03(text) if runner_for(network) == RUNNER_V03 else text


def runner_for(network: str) -> str:
    return RUNNER_V03 if network == "studio-next" else RUNNER_V02
