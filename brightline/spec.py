"""Canonical representation, hashing, and probe-set manifests.

Two identity rules, both load-bearing:

* A rule is identified by the sha256 of its *normalized* text, so cosmetic edits
  do not create a new rule and a substantive edit always does.
* A probe is identified by the sha256 of its canonical scenario JSON, so probes are
  content-addressed. Registration is therefore idempotent, and a probe set is a
  fixed membership that survives a change to the rule under test.

That second property is what makes the re-test loop honest: rule V2 is tested
against the *same* probe ids as V1 (regression), and separately against a freshly
generated set (generalization). Without the fresh set, a rule can be tuned to pass
a known corpus and the score means nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROBE_DIR = ROOT / "probes"

# The families a probe set must cover. Chosen because the failure modes that
# actually break adjudicated agreements are procedural -- which source is
# authoritative, what happens when sources conflict, when evidence arrives, what
# partial performance means -- not adjectival.
FAMILIES = (
    "regression_after_fix",
    "conflicting_evidence",
    "late_evidence",
    "partial_completion",
    "missing_confirmation",
    "criteria_gap",
)

DEFAULT_QUOTA: dict[str, int] = {
    "regression_after_fix": 1,
    "conflicting_evidence": 2,
    "late_evidence": 1,
    "partial_completion": 2,
    "missing_confirmation": 1,
    "criteria_gap": 1,
}


def canonical(obj: Any) -> str:
    """Byte-stable JSON. sort_keys because key order varies across producers."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(text: str) -> str:
    return "0x" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_rule(text: str) -> str:
    """NFKC, collapse whitespace, strip. Cosmetic edits must not fork the identity."""
    out = unicodedata.normalize("NFKC", text)
    out = out.replace("’", "'").replace("“", '"').replace("”", '"')
    out = re.sub(r"\s+", " ", out)
    return out.strip()


@dataclass
class AgreementSpec:
    """One resolution rule under test, plus the label we show humans."""

    rule_text: str
    label: str = "v1"
    title: str = ""
    domain: str = ""
    notes: str = ""

    @property
    def normalized(self) -> str:
        return normalize_rule(self.rule_text)

    @property
    def rule_hash(self) -> str:
        return sha(self.normalized)

    def to_dict(self) -> dict:
        return {
            "schema": "brightline.spec/1",
            "label": self.label,
            "title": self.title,
            "domain": self.domain,
            "rule_text": self.rule_text,
            "normalized": self.normalized,
            "rule_hash": self.rule_hash,
            "notes": self.notes,
        }

    @classmethod
    def from_file(cls, path: str | Path) -> AgreementSpec:
        raw = Path(path).read_text()
        data = json.loads(raw) if raw.lstrip().startswith("{") else _mini_yaml(raw)
        return cls(
            rule_text=data["rule_text"],
            label=str(data.get("label", "v1")),
            title=str(data.get("title", "")),
            domain=str(data.get("domain", "")),
            notes=str(data.get("notes", "")),
        )


def _mini_yaml(text: str) -> dict:
    """Tiny key: value / key: | block reader.

    A whole YAML dependency for four scalar fields is not worth it, and the file
    format is ours.
    """
    data: dict[str, str] = {}
    key: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            if key is not None:
                data[key] = "\n".join(buf).strip() if buf else data.get(key, "")
            key, rest, buf = m.group(1), m.group(2).strip(), []
            if rest in ("|", ">", "|-", ">-"):
                data[key] = ""
            else:
                data[key] = rest.strip("'\"")
                key_done = True  # noqa: F841
        elif key is not None:
            buf.append(line.strip())
    if key is not None and buf:
        data[key] = "\n".join(buf).strip()
    return data


@dataclass
class Probe:
    index: int
    family: str
    scenario: dict

    @property
    def canonical_scenario(self) -> str:
        return canonical(self.scenario)

    @property
    def probe_id(self) -> str:
        return sha(self.canonical_scenario)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "family": self.family,
            "probe_id": self.probe_id,
            "scenario": self.scenario,
            "canonical": self.canonical_scenario,
        }


@dataclass
class ProbeSet:
    """A frozen, content-addressed set of hermetic fact patterns."""

    probes: list[Probe]
    generated_from: dict = field(default_factory=dict)
    quota: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_QUOTA))

    @property
    def probe_set_id(self) -> str:
        joined = "".join(sorted(p.probe_id for p in self.probes))
        return "ps_" + hashlib.sha256(joined.encode()).hexdigest()[:16]

    def family_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self.probes:
            out[p.family] = out.get(p.family, 0) + 1
        return dict(sorted(out.items()))

    def validate(self) -> list[str]:
        """Structural problems that would invalidate a measurement."""
        problems: list[str] = []
        ids = [p.probe_id for p in self.probes]
        if len(set(ids)) != len(ids):
            problems.append("duplicate probe_id: scenarios are not distinct")
        for p in self.probes:
            if p.family not in FAMILIES:
                problems.append(f"probe {p.index}: unknown family {p.family!r}")
            blob = p.canonical_scenario
            if "http://" in blob or "https://" in blob:
                problems.append(f"probe {p.index}: contains a URL; probes must be hermetic")
            if len(blob) > 6000:
                problems.append(f"probe {p.index}: scenario exceeds contract cap (6000 chars)")
            if not p.scenario.get("narrative"):
                problems.append(f"probe {p.index}: missing narrative")
        counts = self.family_counts()
        for fam, want in self.quota.items():
            if counts.get(fam, 0) < want:
                problems.append(f"family {fam}: {counts.get(fam, 0)} probes, quota {want}")
        return problems

    def to_dict(self) -> dict:
        return {
            "schema": "brightline.probeset/1",
            "probe_set_id": self.probe_set_id,
            "generated_from": self.generated_from,
            "n_probes": len(self.probes),
            "family_quota": self.quota,
            "family_counts": self.family_counts(),
            "probes": [p.to_dict() for p in self.probes],
        }

    def save(self, directory: str | Path = PROBE_DIR) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.probe_set_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return path

    @classmethod
    def load(cls, path: str | Path) -> ProbeSet:
        data = json.loads(Path(path).read_text())
        probes = [Probe(index=int(p["index"]), family=str(p["family"]),
                        scenario=p["scenario"]) for p in data["probes"]]
        ps = cls(probes=probes, generated_from=data.get("generated_from", {}),
                 quota=data.get("family_quota", dict(DEFAULT_QUOTA)))
        if ps.probe_set_id != data["probe_set_id"]:
            raise ValueError(
                f"probe set id mismatch: file says {data['probe_set_id']}, "
                f"contents hash to {ps.probe_set_id} -- manifest was edited"
            )
        for probe, stored in zip(ps.probes, data["probes"]):
            if probe.probe_id != stored["probe_id"]:
                raise ValueError(f"probe {probe.index} id mismatch; manifest was edited")
        return ps
