"""Pack validation: checks manifest, contracts, references, and structure."""

import json
import re
from pathlib import Path
from typing import List, Tuple

from .jsonschema import validate as validate_schema
from .manifest import (
    load_pack_manifest,
    load_policy_index,
    load_skill_contracts,
    get_skill_dirs,
    get_reference_files,
    get_evidence_config_path,
)


class ValidationError(Exception):
    pass


def _schema_dir() -> Path:
    """Locate the schemas/ directory shipped with the repository.

    Works for both a source checkout (src layout) and an editable install.
    Returns an empty path if schemas are not available (e.g. a packaged
    install without package data); schema checks are skipped then.
    """
    candidate = Path(__file__).resolve().parents[2] / "schemas"
    if candidate.is_dir():
        return candidate
    return Path()


def _load_schema(name: str):
    """Load a JSON Schema file, returning None if unavailable."""
    schema_path = _schema_dir() / name
    if not schema_path.exists():
        return None
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _validate_against_schemas(pack_dir: Path, manifest: dict,
                              contracts: list, errors: List[str]) -> None:
    """Validate pack.json and every contract.json against the JSON Schemas."""
    pack_schema = _load_schema("pack.schema.json")
    if pack_schema is not None:
        schema_errors = validate_schema(manifest, pack_schema)
        for err in schema_errors:
            errors.append(f"[{manifest.get('id', '<unknown>')}] pack.json: {err}")

    contract_schema = _load_schema("skill-contract.schema.json")
    if contract_schema is None:
        return
    for contract in contracts:
        cid = contract.get("id", "<unknown>")
        schema_errors = validate_schema(contract, contract_schema)
        for err in schema_errors:
            errors.append(f"[{cid}] contract.json: {err}")


def validate_pack(pack_dir: Path) -> Tuple[bool, List[str]]:
    """Validate a pack directory. Returns (ok, errors)."""
    errors: List[str] = []

    # 1. Load manifest
    try:
        manifest = load_pack_manifest(pack_dir)
    except Exception as e:
        return False, [str(e)]

    pack_id = manifest.get("id", "<unknown>")

    # 1b. Load contracts and validate manifest + contracts against JSON Schemas
    try:
        contracts = load_skill_contracts(pack_dir, manifest)
    except Exception as e:
        errors.append(str(e))
        contracts = []
    _validate_against_schemas(pack_dir, manifest, contracts, errors)

    # 2. Check required manifest fields
    for field in ("schema_version", "id", "version", "name", "skills"):
        if field not in manifest:
            errors.append(f"[{pack_id}] manifest missing required field: {field}")

    # 3. Validate skill entries
    skill_ids = []
    for entry in manifest.get("skills", []):
        sid = entry.get("id", "")
        sdir = entry.get("dir", "")
        if not sid:
            errors.append(f"[{pack_id}] skill entry missing id: {entry}")
            continue
        skill_ids.append(sid)

        # Check dir name matches id suffix
        expected_dir = sid.split(".")[-1] if "." in sid else sid
        if sdir.split("/")[-1] != expected_dir:
            errors.append(
                f"[{pack_id}] skill '{sid}' dir name '{sdir}' does not match id suffix '{expected_dir}'"
            )

        # Check skill dir exists
        skill_path = pack_dir / sdir
        if not skill_path.exists():
            errors.append(f"[{pack_id}] skill dir not found: {skill_path}")
            continue

        # Check SKILL.md exists
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            errors.append(f"[{pack_id}] SKILL.md not found for skill '{sid}'")

    # 4. Validate contracts (loaded in step 1b)
    contract_ids = []
    for contract in contracts:
        cid = contract.get("id", "")
        contract_ids.append(cid)

        # Check contract id uniqueness
        if contract_ids.count(cid) > 1:
            errors.append(f"[{pack_id}] duplicate contract id: {cid}")

        # Check relation references exist
        relations = contract.get("relations", {})
        for rel_name in ("recommended_previous", "recommended_next", "conflicts"):
            for ref in relations.get(rel_name, []):
                if ref not in skill_ids:
                    errors.append(
                        f"[{pack_id}] skill '{cid}' {rel_name} references unknown skill: {ref}"
                    )

        # Check conflicts is bidirectional
        for ref in relations.get("conflicts", []):
            ref_contract = next((c for c in contracts if c.get("id") == ref), None)
            if ref_contract:
                if cid not in ref_contract.get("relations", {}).get("conflicts", []):
                    errors.append(
                        f"[{pack_id}] conflicts not bidirectional: '{cid}' -> '{ref}' but not back"
                    )

        # Check alias target exists and doesn't form a cycle
        if contract.get("kind") == "alias":
            target = contract.get("target", "")
            if target and target not in skill_ids:
                errors.append(
                    f"[{pack_id}] alias '{cid}' targets unknown skill: {target}"
                )
            if target:
                visited = {cid}
                current = target
                while current and current not in visited:
                    visited.add(current)
                    target_c = next((c for c in contracts if c.get("id") == current), None)
                    if not target_c or target_c.get("kind") != "alias":
                        break
                    current = target_c.get("target", "")
                else:
                    if current in visited:
                        errors.append(f"[{pack_id}] alias cycle detected involving '{cid}'")

    # 5. Validate references exist
    for ref_entry in manifest.get("references", []):
        ref_path = pack_dir / ref_entry["path"]
        if not ref_path.exists():
            errors.append(f"[{pack_id}] reference not found: {ref_entry['path']}")

    # 6. Validate policy index
    try:
        policy_index = load_policy_index(pack_dir, manifest)
    except Exception as e:
        errors.append(str(e))
        policy_index = {"policies": []}

    for policy in policy_index.get("policies", []):
        policy_path = pack_dir / "policies" / policy.get("path", "")
        if not policy_path.exists():
            errors.append(f"[{pack_id}] policy file not found: {policy.get('path')}")

    # 7. Validate evidence config exists
    evidence_config = get_evidence_config_path(pack_dir, manifest)
    if evidence_config and not evidence_config.exists():
        errors.append(f"[{pack_id}] evidence config not found: {evidence_config}")

    # 8. Check for absolute paths in contracts
    abs_path_re = re.compile(r"^[A-Za-z]:[/\\]|^/")
    for contract in contracts:
        for perm_list in contract.get("permissions", {}).values():
            for perm in perm_list:
                if abs_path_re.match(perm):
                    errors.append(
                        f"[{pack_id}] absolute path in permissions for '{contract.get('id')}': {perm}"
                    )

    # 9. Check all skill dirs have contract.json
    for entry in manifest.get("skills", []):
        skill_dir = pack_dir / entry["dir"]
        contract_path = skill_dir / "contract.json"
        if not contract_path.exists():
            errors.append(f"[{pack_id}] contract.json not found for skill '{entry['id']}'")

    return (len(errors) == 0), errors
