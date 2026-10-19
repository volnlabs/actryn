#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify v0.0.1 signed metadata and its bounded distribution receipt."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = Path("docs/development/signed-distribution-verification.json")
ARCHIVE_RECEIPT = Path("docs/development/final-distribution-archive-restore.json")
FINAL_RECEIPT = Path("docs/development/v0.0.1-release-qualification.json")
SPKI = "3bc25f592073d520c88635fca7fe1838d156428c314b34db4ebd655a18ce6735"
QUALIFICATION_SHA = "8e34b5f9a02e6d7f398c6dc8c995b883b775a9944113db7ce778fce6b1111b36"
SIGNED_RECEIPT_SHA = "4cce5096cffdde3bde8d08a8efabd484a5696717aded43ad48ba19f5003891ac"
ROLES = {
    "server": {
        "manifest_sha256": "bcc415d038820bc08c15c9f6f6a53f24d2d805d4b188f5f01b733cf8cbd985e9",
        "payload_sha256": "45829a380d9662778d53af993cc773af3d2deda434581b694345eca4540f3e82",
        "signature_sha256": "4cb1c0f4b98727453d46743719a64788e42cf70f52243bd9a61f170286f14222",
        "architecture": "amd64",
        "kernel_release": "6.12.111+deb13-amd64",
        "scope": "server-independent-D2",
    },
    "robot": {
        "manifest_sha256": "0e4e4ec9d673de73c3a3207056e88c32f4e96074e61841b00a8cc4e0bfe51d80",
        "payload_sha256": "2a2d96895e88692c6c66165e8b6bf070785fe1ac285bbf8046c6b7aeb63198e8",
        "signature_sha256": "c308dafa6575b14da481262d7577e406e3a8ad060ef199580f02591cc6bafd84",
        "architecture": "arm64",
        "kernel_release": "6.12.111+deb13-arm64",
        "scope": "robot-software-preview",
    },
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_path(root, relative):
    path = PurePosixPath(relative)
    require(not path.is_absolute() and ".." not in path.parts and bool(path.parts),
            "unsafe path: " + str(relative))
    result = root / path
    require(result.resolve().is_relative_to(root.resolve()), "path escapes root")
    require(not result.is_symlink(), "symlink refused: " + str(relative))
    return result


def verify_signature(key, manifest, signature):
    require(signature.stat().st_size == 64, "Ed25519 signature length")
    run = subprocess.run([
        "openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(key),
        "-rawin", "-in", str(manifest), "-sigfile", str(signature),
    ], capture_output=True, text=True, timeout=15)
    require(run.returncode == 0, "OpenSSL signature verification failed")


def validate_final_release(root):
    archive_path = safe_path(root, str(ARCHIVE_RECEIPT))
    final_path = safe_path(root, str(FINAL_RECEIPT))
    signed_path = safe_path(root, str(DEFAULT_RECEIPT))
    archive = decode(archive_path.read_bytes())
    final = decode(final_path.read_bytes())
    require(set(archive) == {
        "all_entries_verified", "archive_sha256", "ciphertext_sha256", "created_at",
        "decrypted_from_drive_copy", "files_verified", "filesystem_uuid", "format",
        "independent_installation", "inventory_sha256", "metadata_signatures_verified",
        "off_host", "owner", "physical_acceptance", "raw_verification",
        "safe_regular_file_extraction", "signed_distribution_receipt", "status",
    }, "archive restore receipt fields")
    require(archive["format"] == "actryn-v0.0.1-final-distribution-archive-restore-1"
            and archive["status"] == "PASS"
            and archive["owner"] == "Utkarsh Maurya <projects.utkarshMaurya@gmail.com>"
            and archive["filesystem_uuid"] == "0347-DCDB"
            and archive["off_host"] is True
            and archive["decrypted_from_drive_copy"] is True
            and archive["files_verified"] == 68
            and archive["all_entries_verified"] is True
            and archive["safe_regular_file_extraction"] is True
            and archive["metadata_signatures_verified"] == 2
            and archive["physical_acceptance"] is False
            and archive["independent_installation"] is False,
            "archive restore result/boundary")
    require(archive["ciphertext_sha256"] ==
            "23092cfa49984cb34a6f4f59636953371f8dbc01cfb632e44d8b68bd3d0ef361"
            and archive["archive_sha256"] ==
            "a0830691a8ad02734e604a3adbe40ba2e82ec385f5e7ff6c5c68f61d375bbbab"
            and archive["inventory_sha256"] ==
            "749986f3640e6120bab66d20ddde52dd6582285572c762250e22952b27b753f0",
            "archive restore identity")
    require(archive["signed_distribution_receipt"] == {
        "path": str(DEFAULT_RECEIPT), "sha256": SIGNED_RECEIPT_SHA,
    }, "archive signed-distribution binding")
    raw = archive["raw_verification"]
    require(set(raw) == {"path", "sha256"}
            and raw["path"] ==
            "artifacts/v0.0.1-final-distribution-restore01/verification.json"
            and re.fullmatch("[0-9a-f]{64}", raw["sha256"]),
            "raw restore reference")

    require(set(final) == {
        "archive_restore", "claim", "created_at", "format", "independent_installation",
        "live_motion", "merged", "original_a14", "owner", "physical_acceptance",
        "publication_performed", "qualification", "qualified_scope", "release_qualified",
        "remaining_release_checks", "roles", "signed_distribution", "signer_spki_sha256",
        "status", "tag_created",
    }, "final release receipt fields")
    require(final["format"] == "actryn-v0.0.1-software-preview-qualification-1"
            and final["status"] == "PASS_SOFTWARE_PREVIEW_QUALIFIED"
            and final["owner"] == "Utkarsh Maurya <projects.utkarshMaurya@gmail.com>"
            and final["created_at"] == archive["created_at"]
            and final["release_qualified"] is True
            and final["qualified_scope"] == "software-only external developer preview"
            and final["remaining_release_checks"] == []
            and final["independent_installation"] is False
            and final["physical_acceptance"] is False
            and final["live_motion"] is False
            and final["publication_performed"] is False
            and final["tag_created"] is False
            and final["merged"] is False
            and final["original_a14"] == "DEFERRED_UNTIL_ANOTHER_DEVELOPER_JOINS"
            and final["claim"] == ("Qualified by the sole maintainer; independent installation "
                                   "and physical qualification have not been performed."),
            "final release result/boundary")
    require(final["signer_spki_sha256"] == SPKI, "final release signer")
    qualification = final["qualification"]
    require(qualification == {
        "path": "docs/development/solo-preview-qualification-v5.json",
        "sha256": QUALIFICATION_SHA,
        "maintainer_review_path": "docs/development/solo-maintainer-review-v5.json",
        "maintainer_review_sha256":
            "73c37ca1176eed05ca0e2b08388cce8995f9f80b0b4221031f432e1b542e8750",
        "open_required_gates": [],
        "deferred_gates": ["A14"],
    }, "final qualification binding")
    require(final["signed_distribution"] == {
        "path": str(DEFAULT_RECEIPT), "sha256": SIGNED_RECEIPT_SHA, "verified": True,
    } and digest(signed_path) == SIGNED_RECEIPT_SHA, "final signed-distribution binding")
    require(final["archive_restore"] == {
        "path": str(ARCHIVE_RECEIPT), "sha256": digest(archive_path), "verified": True,
    }, "final archive-restore binding")
    require(final["roles"] == {
        role: {name: expected[name] for name in
               ("manifest_sha256", "payload_sha256", "signature_sha256")}
        for role, expected in ROLES.items()
    }, "final signed role identities")
    return final


def validate(receipt, root=ROOT, evidence_root=None):
    require(set(receipt) == {
        "bounded_workflow", "created_at", "evidence", "execution", "format",
        "fresh_guests", "independent_installation", "live_actuation", "owner",
        "physical_acceptance", "qualification", "release_qualified", "remaining",
        "roles", "signed_distribution_verified", "signer", "status", "stopped_custody",
    }, "signed distribution receipt fields")
    require(receipt["format"] == "actryn-v0.0.1-signed-distribution-verification-1"
            and receipt["status"] == "PASS"
            and receipt["owner"] == "Utkarsh Maurya <projects.utkarshMaurya@gmail.com>"
            and receipt["execution"] == "automated under maintainer authorization",
            "signed distribution receipt identity")
    require(receipt["fresh_guests"] is True
            and receipt["signed_distribution_verified"] is True
            and receipt["independent_installation"] is False
            and receipt["physical_acceptance"] is False
            and receipt["live_actuation"] is False
            and receipt["release_qualified"] is False
            and receipt["remaining"] == ["final-distribution-archive-restore"],
            "signed distribution boundary")

    qualification = receipt["qualification"]
    require(set(qualification) == {"path", "sha256", "maintainer_review_path",
                                   "maintainer_review_sha256", "deferred_gates",
                                   "open_required_gates"}, "qualification fields")
    require(qualification["sha256"] == QUALIFICATION_SHA
            and qualification["deferred_gates"] == ["A14"]
            and qualification["open_required_gates"] == [], "qualification binding")
    qualification_path = safe_path(root, qualification["path"])
    review_path = safe_path(root, qualification["maintainer_review_path"])
    require(digest(qualification_path) == QUALIFICATION_SHA
            and digest(review_path) == qualification["maintainer_review_sha256"],
            "qualification or review changed")

    signer = receipt["signer"]
    require(set(signer) == {"custody_path", "custody_sha256", "public_key_path",
                            "public_key_pem_sha256", "spki_sha256"}, "signer fields")
    require(signer["spki_sha256"] == SPKI, "unexpected release signer")
    custody_path = safe_path(root, signer["custody_path"])
    key_path = safe_path(root, signer["public_key_path"])
    require(digest(custody_path) == signer["custody_sha256"]
            and digest(key_path) == signer["public_key_pem_sha256"],
            "custody or public key changed")
    custody = decode(custody_path.read_bytes())
    require(custody["spki_sha256"] == SPKI
            and custody["recovery"]["restored_spki_sha256"] == SPKI
            and custody["recovery"]["challenge_verified"] is True
            and custody["recovery"]["tampered_challenge_rejected"] is True,
            "release key recovery binding")
    public_der = subprocess.run([
        "openssl", "pkey", "-pubin", "-in", str(key_path), "-outform", "DER",
    ], capture_output=True, timeout=15, check=True).stdout
    require(hashlib.sha256(public_der).hexdigest() == SPKI, "public key SPKI mismatch")

    require(set(receipt["roles"]) == set(ROLES), "both signed roles required")
    evidence = receipt["evidence"]
    require(isinstance(evidence, list) and 1 <= len(evidence) <= 128, "evidence count")
    references = {}
    for item in evidence:
        require(set(item) == {"path", "size", "sha256"}, "evidence fields")
        require(type(item["size"]) is int and 0 <= item["size"] <= 512 * 1024**2,
                "evidence size")
        require(isinstance(item["sha256"], str)
                and re.fullmatch("[0-9a-f]{64}", item["sha256"]), "evidence digest")
        safe_path(Path("/evidence"), item["path"])
        require(item["path"] not in references, "duplicate evidence path")
        references[item["path"]] = item

    metadata = root / "docs/development/v0.0.1-signed-metadata"
    for role, expected in ROLES.items():
        row = receipt["roles"][role]
        require(set(row) == {
            "activate_result", "active_pointer_verified", "authority_issued",
            "automatic_restart", "bootstrap_verified", "inhibitor_present",
            "manifest_sha256", "payload_sha256", "promotable", "services_inactive",
            "signature_sha256", "signature_verified", "stage_result", "target",
        }, "role receipt fields")
        require(row["manifest_sha256"] == expected["manifest_sha256"]
                and row["payload_sha256"] == expected["payload_sha256"]
                and row["signature_sha256"] == expected["signature_sha256"]
                and row["signature_verified"] is True and row["promotable"] is True
                and row["stage_result"] == "staged"
                and row["activate_result"] == "installed_inhibited"
                and row["active_pointer_verified"] is True
                and row["bootstrap_verified"] is True
                and row["inhibitor_present"] is True
                and row["services_inactive"] is True
                and row["authority_issued"] is False
                and row["automatic_restart"] is False,
                "signed role result")
        target = row["target"]
        require(target["distribution"] == "debian" and target["version"] == "13.7"
                and target["kernel_release"] == expected["kernel_release"],
                "signed target tuple")
        manifest_path = metadata / role / "manifest.json"
        signature_path = metadata / role / "signature.ed25519"
        require(digest(manifest_path) == expected["manifest_sha256"]
                and digest(signature_path) == expected["signature_sha256"],
                "signed metadata digest")
        verify_signature(key_path, manifest_path, signature_path)
        manifest_raw = manifest_path.read_bytes()
        manifest = decode(manifest_raw)
        canonical = (json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        require(manifest_raw == canonical,
                "manifest is not canonical")
        provenance = manifest["provenance"]
        attestation = provenance["custodian_attestation"]
        require(manifest["format"] == "actryn-release-1" and manifest["version"] == "0.0.1"
                and manifest["role"] == role
                and provenance["qualification"] == "software-preview-qualified"
                and provenance["evidence"]["qualification-bundle"] == QUALIFICATION_SHA
                and attestation == {"qualification_bundle_sha256": QUALIFICATION_SHA,
                                    "role": role, "scope": expected["scope"]}
                and manifest["target"]["architecture"] == expected["architecture"]
                and manifest["target"]["kernel_release"] == expected["kernel_release"],
                "signed manifest qualification/target")
        for name, expected_hash in (("manifest.json", expected["manifest_sha256"]),
                                    ("payload.tar", expected["payload_sha256"]),
                                    ("signature.ed25519", expected["signature_sha256"])):
            item = references.get(f"artifacts/v0.0.1-release-candidates01/{role}/{name}")
            require(item is not None and item["sha256"] == expected_hash,
                    "candidate evidence identity")

    workflow = receipt["bounded_workflow"]
    require(workflow["executed_on_signed_guests"] is False
            and workflow["composed_from_qualified_identical_payloads"] is True
            and workflow["qualification_bundle_sha256"] == QUALIFICATION_SHA
            and workflow["boundary"] == (
                "The final signatures change manifest provenance only. Both installed payload "
                "archives are byte-identical to the v5-qualified subjects; no operation or "
                "provider call was replayed after signing."), "bounded workflow boundary")
    custody = receipt["stopped_custody"]
    require(custody["vm_units_inactive"] is True
            and custody["forwarded_ports_free"] is True
            and all(re.fullmatch("[0-9a-f]{64}", custody[name]) for name in
                    ("server_overlay_sha256", "robot_overlay_sha256")),
            "stopped custody")

    verified = 0
    if evidence_root is not None:
        for item in evidence:
            path = safe_path(evidence_root, item["path"])
            require(path.is_file() and path.stat().st_size == item["size"]
                    and digest(path) == item["sha256"], "evidence changed: " + item["path"])
            verified += 1
    final = validate_final_release(root)
    return {
        "check": "signed-distribution-metadata-and-receipt",
        "signed_distribution_verified": True,
        "metadata_signatures_verified": 2,
        "evidence_files_verified": verified,
        "release_qualified": final["release_qualified"],
        "remaining": final["remaining_release_checks"],
        "physical_acceptance": False,
        "independent_installation": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--require-signed", action="store_true")
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    receipt_path = args.receipt if args.receipt.is_absolute() else ROOT / args.receipt
    result = validate(decode(receipt_path.read_bytes()), ROOT,
                      args.evidence_root.resolve() if args.evidence_root else None)
    print(json.dumps(result, sort_keys=True))
    if args.require_signed and not result["signed_distribution_verified"]:
        raise SystemExit(1)
    if args.require_qualified and not result["release_qualified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
