"""Pack validation: checks manifest, contracts, references, and structure."""

import json
import re
from importlib.resources import files
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


def _normalize_ref_path(p: str) -> str:
    """Platform-independent reference path normalization.

    Backslashes are converted to forward slashes explicitly, because
    Path.as_posix() only converts the OS separator and would leave a literal
    backslash untouched on POSIX. Then Path() collapses '.' components
    (leading "./"). Case is intentionally NOT normalized: on case-sensitive
    filesystems `R.md` and `r.md` are distinct files.
    """
    return Path(p.replace("\\", "/")).as_posix()


def _load_schema(name: str):
    """Load a JSON Schema bundled with the package, or None if unavailable.

    Schemas live inside the installed package (src/illuminate/schemas/) so
    schema conformance works identically in a source checkout, an editable
    install, and a built wheel.
    """
    try:
        data = files("illuminate.schemas").joinpath(name).read_text(encoding="utf-8")
        return json.loads(data)
    except Exception:
        return None


def _validate_against_schemas(pack_dir: Path, manifest: dict,
                              contracts: list, errors: List[str]) -> None:
    """Validate pack.json and every contract.json against the JSON Schemas.

    A missing schema resource is a packaging error, not a skip condition:
    it is reported explicitly so a broken wheel cannot silently disable
    schema conformance.
    """
    pack_id = manifest.get("id", "<unknown>")

    pack_schema = _load_schema("pack.schema.json")
    if pack_schema is None:
        errors.append(f"[{pack_id}] schema resource unavailable: pack.schema.json")
    else:
        schema_errors = validate_schema(manifest, pack_schema)
        for err in schema_errors:
            errors.append(f"[{pack_id}] pack.json: {err}")

    contract_schema = _load_schema("skill-contract.schema.json")
    if contract_schema is None:
        errors.append(
            f"[{pack_id}] schema resource unavailable: skill-contract.schema.json"
        )
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

    if not isinstance(manifest, dict):
        return False, ["pack.json must contain a JSON object"]

    pack_id = manifest.get("id", "<unknown>")

    # Guard the top-level collection shapes before helpers consume them, so a
    # malformed manifest yields a readable error instead of a raw
    # AttributeError/TypeError leaking out of a helper.
    skills = manifest.get("skills", [])
    if not isinstance(skills, list):
        errors.append(f"[{pack_id}] skills must be a list: {skills!r}")
        skills = []

    # 1b. Load contracts and validate manifest + contracts against JSON Schemas
    try:
        contracts = load_skill_contracts(pack_dir, manifest) if skills else []
    except Exception as e:
        errors.append(str(e))
        contracts = []
    # Guard: every contract entry must be an object. A contract.json that holds
    # a JSON array or scalar must not crash the downstream .get() calls.
    valid_contracts = []
    for contract in contracts:
        if not isinstance(contract, dict):
            errors.append(f"[{pack_id}] contract must be an object: {contract!r}")
        else:
            valid_contracts.append(contract)
    contracts = valid_contracts
    _validate_against_schemas(pack_dir, manifest, contracts, errors)

    # 2. Check required manifest fields
    for field in ("schema_version", "id", "version", "name", "skills"):
        if field not in manifest:
            errors.append(f"[{pack_id}] manifest missing required field: {field}")

    # 2b. Reject unknown top-level fields. The pack schema has no
    #     additionalProperties:false, so unknown fields pass schema; enforce
    #     the known set here. Source of truth is the schema's properties keys,
    #     which list every legal core top-level field.
    known_fields = set()
    pack_schema = _load_schema("pack.schema.json")
    if pack_schema:
        known_fields = set(pack_schema.get("properties", {}))
    if known_fields:
        for key in manifest:
            if key not in known_fields:
                errors.append(
                    f"[{pack_id}] unknown top-level field: {key}"
                )

    # 3. Validate skill entries
    skill_ids = []
    skill_dirs = []
    for entry in skills:
        if not isinstance(entry, dict):
            errors.append(f"[{pack_id}] skill entry must be an object: {entry!r}")
            continue
        sid = entry.get("id", "")
        sdir = entry.get("dir", "")
        if not sid:
            errors.append(f"[{pack_id}] skill entry missing id: {entry}")
            continue
        if not isinstance(sid, str):
            errors.append(f"[{pack_id}] skill entry id must be a string: {entry!r}")
            continue
        if not isinstance(sdir, str):
            errors.append(f"[{pack_id}] skill entry dir must be a string: {entry!r}")
            continue
        skill_ids.append(sid)
        if sdir:
            skill_dirs.append(sdir)

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

        # Check SKILL.md exists and has a legal frontmatter (name/description)
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            errors.append(f"[{pack_id}] SKILL.md not found for skill '{sid}'")
            continue
        try:
            md_text = skill_md.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"[{pack_id}] SKILL.md unreadable for skill '{sid}': {exc}")
            continue
        fm = re.match(r"^---\n(.*?)\n---", md_text, re.DOTALL)
        if not fm:
            errors.append(f"[{pack_id}] SKILL.md for skill '{sid}' lacks a frontmatter block")
        else:
            fm_body = fm.group(1)
            for key in ("name", "description"):
                if not re.search(rf"(?m)^{key}:\s*\S", fm_body):
                    errors.append(
                        f"[{pack_id}] SKILL.md for skill '{sid}' lacks non-empty '{key}'"
                    )

    # 3b. Enforce skill id and dir uniqueness.
    for sid in set(skill_ids):
        if skill_ids.count(sid) > 1:
            errors.append(f"[{pack_id}] duplicate skill id: {sid}")
    for sdir in set(skill_dirs):
        if skill_dirs.count(sdir) > 1:
            errors.append(f"[{pack_id}] duplicate skill dir: {sdir}")

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
        if not isinstance(relations, dict):
            errors.append(f"[{pack_id}] skill '{cid}' relations must be an object: {relations!r}")
            relations = {}
        for rel_name in ("recommended_previous", "recommended_next", "activation_conflicts"):
            for ref in relations.get(rel_name, []):
                if ref not in skill_ids:
                    errors.append(
                        f"[{pack_id}] skill '{cid}' {rel_name} references unknown skill: {ref}"
                    )

        # Check activation_conflicts is bidirectional
        for ref in relations.get("activation_conflicts", []):
            ref_contract = next((c for c in contracts if c.get("id") == ref), None)
            if ref_contract:
                ref_relations = ref_contract.get("relations", {})
                if not isinstance(ref_relations, dict):
                    ref_relations = {}
                if cid not in ref_relations.get("activation_conflicts", []):
                    errors.append(
                        f"[{pack_id}] activation_conflicts not bidirectional: "
                        f"'{cid}' -> '{ref}' but not back"
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
    ref_ids = []
    ref_paths = []
    refs = manifest.get("references", [])
    if not isinstance(refs, list):
        errors.append(f"[{pack_id}] references must be a list: {refs!r}")
        refs = []
    for ref_entry in refs:
        if not isinstance(ref_entry, dict):
            errors.append(f"[{pack_id}] reference entry must be an object: {ref_entry!r}")
            continue
        rid = ref_entry.get("id", "")
        rpath = ref_entry.get("path", "")
        ref_ids.append(rid)
        if not isinstance(rpath, str) or not rpath:
            errors.append(f"[{pack_id}] reference entry missing or invalid path: {ref_entry!r}")
            continue
        ref_paths.append(rpath)
        ref_path = pack_dir / rpath
        if not ref_path.exists():
            errors.append(f"[{pack_id}] reference not found: {rpath}")

    # 5b. Enforce reference id and path uniqueness.
    for rid in set(ref_ids):
        if ref_ids.count(rid) > 1:
            errors.append(f"[{pack_id}] duplicate reference id: {rid}")
    # Reference path comparison is normalized (backslashes -> forward
    # slashes, leading "./" removed) so `references/./r.md` and
    # `references/r.md` are detected as duplicates. Case is NOT normalized:
    # on case-sensitive filesystems `R.md` and `r.md` are distinct files.
    normalized_paths = [_normalize_ref_path(p) for p in ref_paths]
    for rpath in set(ref_paths):
        if normalized_paths.count(_normalize_ref_path(rpath)) > 1:
            errors.append(f"[{pack_id}] duplicate reference path: {rpath}")

    # 6. Validate policy index
    try:
        policy_index = load_policy_index(pack_dir, manifest)
    except Exception as e:
        errors.append(str(e))
        policy_index = {"policies": []}

    # The policy index may itself be a JSON array or scalar; it must be an
    # object with a "policies" list before it can be inspected.
    if not isinstance(policy_index, dict):
        errors.append(f"[{pack_id}] policy index must be an object: {policy_index!r}")
        policy_index = {"policies": []}

    # The policy index has no schema, so validate id/path uniqueness and a
    # light structure here. priority is an ordering weight used by
    # get_policy_files (sorted descending); duplicate priorities are allowed
    # and do not break ordering, so only id/path uniqueness is enforced.
    policy_ids = []
    policy_paths = []
    for policy in policy_index.get("policies", []):
        if not isinstance(policy, dict):
            errors.append(f"[{pack_id}] policy entry must be an object: {policy!r}")
            continue
        pid = policy.get("id")
        ppath = policy.get("path")
        pprio = policy.get("priority")
        if not isinstance(pid, str) or not pid:
            errors.append(f"[{pack_id}] policy entry missing or invalid id: {policy}")
        if not isinstance(ppath, str) or not ppath:
            errors.append(f"[{pack_id}] policy entry missing or invalid path: {policy}")
        if not isinstance(pprio, int) or isinstance(pprio, bool):
            errors.append(f"[{pack_id}] policy entry missing or invalid priority: {policy}")
        if isinstance(pid, str) and pid:
            policy_ids.append(pid)
        if isinstance(ppath, str) and ppath:
            policy_paths.append(ppath)
            policy_path = pack_dir / "policies" / ppath
            if not policy_path.exists():
                errors.append(f"[{pack_id}] policy file not found: {ppath}")
    for pid in set(policy_ids):
        if policy_ids.count(pid) > 1:
            errors.append(f"[{pack_id}] duplicate policy id: {pid}")
    for ppath in set(policy_paths):
        if policy_paths.count(ppath) > 1:
            errors.append(f"[{pack_id}] duplicate policy path: {ppath}")

    # 7. Validate evidence config exists
    evidence = manifest.get("evidence", {})
    if not isinstance(evidence, dict):
        errors.append(f"[{pack_id}] evidence must be an object: {evidence!r}")
        evidence_config = None
    else:
        evidence_config = get_evidence_config_path(pack_dir, manifest)
    if evidence_config and not evidence_config.exists():
        errors.append(f"[{pack_id}] evidence config not found: {evidence_config}")

    # 8. Check for absolute paths in contracts
    abs_path_re = re.compile(r"^[A-Za-z]:[/\\]|^/")
    for contract in contracts:
        permissions = contract.get("permissions", {})
        if not isinstance(permissions, dict):
            errors.append(
                f"[{pack_id}] contract '{contract.get('id')}' permissions must be an object: {permissions!r}"
            )
            continue
        for perm_list in permissions.values():
            if not isinstance(perm_list, (list, tuple)):
                errors.append(
                    f"[{pack_id}] contract '{contract.get('id')}' permission set must be a list: {perm_list!r}"
                )
                continue
            for perm in perm_list:
                if not isinstance(perm, str):
                    errors.append(
                        f"[{pack_id}] contract '{contract.get('id')}' permission must be a string: {perm!r}"
                    )
                    continue
                if abs_path_re.match(perm):
                    errors.append(
                        f"[{pack_id}] absolute path in permissions for '{contract.get('id')}': {perm}"
                    )

    # 9. Check all skill dirs have contract.json
    for entry in skills:
        if not isinstance(entry, dict):
            continue
        sid = entry.get("id")
        sdir = entry.get("dir")
        if not isinstance(sid, str) or not isinstance(sdir, str):
            continue
        skill_dir = pack_dir / sdir
        contract_path = skill_dir / "contract.json"
        if not contract_path.exists():
            errors.append(f"[{pack_id}] contract.json not found for skill '{sid}'")

    return (len(errors) == 0), errors
