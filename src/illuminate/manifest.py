"""Pack manifest loading and validation helpers."""

import json
from pathlib import Path
from typing import List, Dict, Optional


class ManifestError(Exception):
    pass


def load_pack_manifest(pack_dir: Path) -> dict:
    """Load and return pack.json from a pack directory."""
    pack_json = pack_dir / "pack.json"
    if not pack_json.exists():
        raise ManifestError(f"pack.json not found in {pack_dir}")
    with open(pack_json, "r", encoding="utf-8") as f:
        return json.load(f)


def load_policy_index(pack_dir: Path, manifest: dict) -> dict:
    """Load the policy index referenced by the manifest."""
    policies_meta = manifest.get("policies", {})
    index_path = policies_meta.get("index")
    if not index_path:
        return {"policies": []}
    full_path = pack_dir / index_path
    if not full_path.exists():
        raise ManifestError(f"Policy index not found: {full_path}")
    with open(full_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_skill_contracts(pack_dir: Path, manifest: dict) -> List[dict]:
    """Load all skill contracts from a pack."""
    contracts = []
    for skill_entry in manifest.get("skills", []):
        skill_dir = pack_dir / skill_entry["dir"]
        contract_path = skill_dir / "contract.json"
        if not contract_path.exists():
            raise ManifestError(
                f"contract.json not found for skill {skill_entry['id']} at {contract_path}"
            )
        with open(contract_path, "r", encoding="utf-8") as f:
            contract = json.load(f)
        contracts.append(contract)
    return contracts


def get_skill_dirs(pack_dir: Path, manifest: dict) -> Dict[str, Path]:
    """Return mapping of skill id → skill directory path."""
    return {
        entry["id"]: pack_dir / entry["dir"]
        for entry in manifest.get("skills", [])
    }


def get_policy_files(pack_dir: Path, policy_index: dict) -> List[Path]:
    """Return list of policy file paths in priority order."""
    policies = sorted(
        policy_index.get("policies", []),
        key=lambda p: p.get("priority", 0),
        reverse=True,
    )
    return [pack_dir / "policies" / p["path"] for p in policies]


def get_reference_files(pack_dir: Path, manifest: dict) -> List[Path]:
    """Return list of reference file paths."""
    return [
        pack_dir / ref["path"]
        for ref in manifest.get("references", [])
    ]


def get_evidence_config_path(pack_dir: Path, manifest: dict) -> Optional[Path]:
    """Return the evidence config path if declared in the manifest."""
    evidence = manifest.get("evidence", {})
    config = evidence.get("config")
    if config:
        return pack_dir / config
    return None
