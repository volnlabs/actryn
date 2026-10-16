//! Resolve only the manual fixed object or the release installer's exact link chain.
use anyhow::{ensure, Context, Result};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::{Path, PathBuf},
};

const FIXED: &str = "usr/lib/actryn/observer.bpf.o";
const MANAGED_LINK: &str = "/opt/actryn/server/current/lib/observer.bpf.o";
const SERVER: &str = "opt/actryn/server";
const MAX_MANIFEST: u64 = 256 * 1024;
const MAX_OBJECT: u64 = 64 * 1024 * 1024;

#[derive(Deserialize)]
struct Manifest {
    format: String,
    role: String,
    version: String,
    target: Target,
    files: Vec<Entry>,
}

#[derive(Deserialize)]
struct Target {
    architecture: String,
    kernel_release: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Entry {
    path: String,
    sha256: String,
    size: u64,
    mode: u32,
    license: String,
}

pub(super) fn resolve_object() -> Result<PathBuf> {
    resolve(Path::new("/"), 0)
}

fn hex_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn protected_directories(path: &Path, root: &Path, owner: u32) -> Result<()> {
    ensure!(path.starts_with(root), "object path outside trusted root");
    for ancestor in path.ancestors() {
        let metadata = fs::symlink_metadata(ancestor)?;
        ensure!(
            metadata.is_dir() && metadata.uid() == owner && metadata.mode() & 0o022 == 0,
            "untrusted object directory {}",
            ancestor.display()
        );
        if ancestor == root {
            return Ok(());
        }
    }
    anyhow::bail!("missing object trust root")
}

fn regular(path: &Path, root: &Path, owner: u32, limit: u64) -> Result<File> {
    protected_directories(
        path.parent().context("object file has no parent")?,
        root,
        owner,
    )?;
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)?;
    let metadata = file.metadata()?;
    ensure!(
        metadata.is_file()
            && metadata.nlink() == 1
            && metadata.uid() == owner
            && metadata.mode() & 0o022 == 0
            && metadata.len() <= limit,
        "untrusted or oversized object file {}",
        path.display()
    );
    Ok(file)
}

fn protected_link(path: &Path, root: &Path, owner: u32) -> Result<PathBuf> {
    protected_directories(
        path.parent().context("object link has no parent")?,
        root,
        owner,
    )?;
    let metadata = fs::symlink_metadata(path)?;
    ensure!(
        metadata.file_type().is_symlink() && metadata.uid() == owner && metadata.nlink() == 1,
        "untrusted object link {}",
        path.display()
    );
    Ok(fs::read_link(path)?)
}

// The trust root/owner are test seams, never daemon arguments or configuration.
// All production paths and the release link grammar are fixed here.
fn resolve(root: &Path, owner: u32) -> Result<PathBuf> {
    let fixed = root.join(FIXED);
    protected_directories(fixed.parent().unwrap(), root, owner)?;
    if !fs::symlink_metadata(&fixed)?.file_type().is_symlink() {
        regular(&fixed, root, owner, MAX_OBJECT)?;
        return Ok(fixed);
    }
    ensure!(
        protected_link(&fixed, root, owner)? == Path::new(MANAGED_LINK),
        "unexpected managed object link"
    );
    let server = root.join(SERVER);
    let current = protected_link(&server.join("current"), root, owner)?;
    let current = current.to_str().context("non-UTF8 release pointer")?;
    let slot_id = current
        .strip_prefix("releases/")
        .and_then(|value| value.strip_suffix("/payload"))
        .context("invalid release pointer")?;
    ensure!(hex_digest(slot_id), "invalid release slot identity");
    let slot = server.join("releases").join(slot_id);
    let manifest_file = regular(&slot.join("manifest.json"), root, owner, MAX_MANIFEST)?;
    let expected_size = manifest_file.metadata()?.len();
    let mut bytes = Vec::new();
    manifest_file
        .take(MAX_MANIFEST + 1)
        .read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() as u64 == expected_size && bytes.len() as u64 <= MAX_MANIFEST,
        "release manifest size changed"
    );
    ensure!(
        format!("{:x}", Sha256::digest(&bytes)) == slot_id,
        "release manifest does not match slot identity"
    );
    let manifest: Manifest = serde_json::from_slice(&bytes)?;
    ensure!(
        manifest.format == "actryn-release-1"
            && manifest.role == "server"
            && manifest.version == "0.0.1"
            && manifest.target.architecture == "amd64"
            && manifest.target.kernel_release == "6.12.111+deb13-amd64"
            && manifest.files.len() <= 64,
        "unsupported managed object release"
    );
    let mut entries = manifest
        .files
        .iter()
        .filter(|entry| entry.path == "lib/observer.bpf.o");
    let entry = entries
        .next()
        .context("BPF object missing from release manifest")?;
    ensure!(
        entries.next().is_none()
            && hex_digest(&entry.sha256)
            && (64..=MAX_OBJECT).contains(&entry.size)
            && entry.mode == 0o644
            && entry.license == "GPL-2.0-only",
        "invalid BPF object manifest entry"
    );
    let object = slot.join("payload/lib/observer.bpf.o");
    let mut file = regular(&object, root, owner, MAX_OBJECT)?;
    let metadata = file.metadata()?;
    ensure!(
        metadata.len() == entry.size && metadata.mode() & 0o7777 == entry.mode,
        "BPF object size or mode mismatch"
    );
    let mut prefix = [0_u8; 64];
    file.read_exact(&mut prefix)?;
    ensure!(
        &prefix[..6] == b"\x7fELF\x02\x01"
            && u16::from_le_bytes(prefix[16..18].try_into().unwrap()) == 1
            && u16::from_le_bytes(prefix[18..20].try_into().unwrap()) == 247,
        "managed object must be ELF64 little-endian EM_BPF ET_REL"
    );
    let mut digest = Sha256::new();
    digest.update(prefix);
    let mut consumed = 64_u64;
    let mut buffer = [0_u8; 65536];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        consumed += count as u64;
        ensure!(consumed <= entry.size, "BPF object grew during validation");
        digest.update(&buffer[..count]);
    }
    ensure!(
        consumed == entry.size && format!("{:x}", digest.finalize()) == entry.sha256,
        "BPF object SHA256 mismatch"
    );
    // Never pass current or the public symlink to libbpf after validation.
    // Installer startup preflight independently authenticates the signed tuple;
    // direct startup still binds these protected bytes to this immutable slot.
    Ok(object)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use sha2::{Digest, Sha256};
    use std::{
        fs,
        os::unix::fs::{symlink, PermissionsExt},
    };

    const FIXED: &str = "usr/lib/actryn/observer.bpf.o";
    const LINK: &str = "/opt/actryn/server/current/lib/observer.bpf.o";
    const CURRENT: &str = "opt/actryn/server/current";

    fn hash(bytes: &[u8]) -> String {
        format!("{:x}", Sha256::digest(bytes))
    }

    fn object() -> Vec<u8> {
        let mut bytes = vec![0; 64];
        bytes[..6].copy_from_slice(b"\x7fELF\x02\x01");
        bytes[16..18].copy_from_slice(&1_u16.to_le_bytes());
        bytes[18..20].copy_from_slice(&247_u16.to_le_bytes());
        bytes
    }

    fn write(path: &Path, bytes: &[u8]) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, bytes).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o644)).unwrap();
    }

    struct Fixture {
        root: tempfile::TempDir,
        object: PathBuf,
        manifest: PathBuf,
    }

    impl Fixture {
        fn managed_with(change: impl FnOnce(&mut serde_json::Value)) -> Self {
            Self::managed_object(&object(), change)
        }

        fn managed_object(
            object_bytes: &[u8],
            change: impl FnOnce(&mut serde_json::Value),
        ) -> Self {
            let root = tempfile::tempdir().unwrap();
            let mut manifest = json!({
                "format": "actryn-release-1", "role": "server", "version": "0.0.1",
                "target": {"architecture": "amd64", "kernel_release": "6.12.111+deb13-amd64"},
                "files": [{"path": "lib/observer.bpf.o", "sha256": hash(object_bytes),
                    "size": object_bytes.len(), "mode": 420, "license": "GPL-2.0-only"}]
            });
            change(&mut manifest);
            let bytes = serde_json::to_vec(&manifest).unwrap();
            let id = hash(&bytes);
            let slot = root.path().join("opt/actryn/server/releases").join(&id);
            let object_path = slot.join("payload/lib/observer.bpf.o");
            write(&object_path, object_bytes);
            let manifest_path = slot.join("manifest.json");
            write(&manifest_path, &bytes);
            fs::create_dir_all(root.path().join("usr/lib/actryn")).unwrap();
            symlink(LINK, root.path().join(FIXED)).unwrap();
            symlink(format!("releases/{id}/payload"), root.path().join(CURRENT)).unwrap();
            Self {
                root,
                object: object_path,
                manifest: manifest_path,
            }
        }

        fn managed() -> Self {
            Self::managed_with(|_| {})
        }

        fn resolve(&self) -> Result<PathBuf> {
            resolve(self.root.path(), unsafe { libc::geteuid() })
        }
    }

    #[test]
    fn managed_object_resolves_to_verified_immutable_slot() {
        let fixture = Fixture::managed();
        let resolved = fixture.resolve().unwrap();
        assert_eq!(resolved, fixture.object);
        // Loading this path cannot follow a later replacement of current.
        fs::remove_file(fixture.root.path().join(CURRENT)).unwrap();
        symlink("releases/other/payload", fixture.root.path().join(CURRENT)).unwrap();
        assert_eq!(fs::read(resolved).unwrap(), object());
    }

    #[test]
    fn protected_regular_manual_object_remains_supported() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join(FIXED);
        write(&path, &object());
        assert_eq!(
            resolve(root.path(), unsafe { libc::geteuid() }).unwrap(),
            path
        );
        fs::set_permissions(&path, fs::Permissions::from_mode(0o666)).unwrap();
        assert!(resolve(root.path(), unsafe { libc::geteuid() }).is_err());
    }

    #[test]
    fn link_redirects_and_malformed_slots_are_rejected() {
        for target in [
            "/tmp/observer.bpf.o",
            "../../../opt/actryn/server/current/lib/observer.bpf.o",
        ] {
            let fixture = Fixture::managed();
            fs::remove_file(fixture.root.path().join(FIXED)).unwrap();
            symlink(target, fixture.root.path().join(FIXED)).unwrap();
            assert!(fixture.resolve().is_err());
        }
        for target in [
            "/opt/actryn/server/releases/aaa/payload",
            "releases/../payload",
            "releases/ABC/payload",
            "releases/aaa/payload/extra",
        ] {
            let fixture = Fixture::managed();
            fs::remove_file(fixture.root.path().join(CURRENT)).unwrap();
            symlink(target, fixture.root.path().join(CURRENT)).unwrap();
            assert!(fixture.resolve().is_err());
        }
    }

    #[test]
    fn writable_parent_redirected_slot_and_wrong_owner_are_rejected() {
        for parent in [
            "usr/lib/actryn",
            "opt/actryn/server",
            "opt/actryn/server/releases",
        ] {
            let fixture = Fixture::managed();
            fs::set_permissions(
                fixture.root.path().join(parent),
                fs::Permissions::from_mode(0o777),
            )
            .unwrap();
            assert!(fixture.resolve().is_err());
        }
        let fixture = Fixture::managed();
        assert!(resolve(fixture.root.path(), unsafe { libc::geteuid() } + 1).is_err());
        let lib = fixture.object.parent().unwrap();
        let moved = lib.with_file_name("other");
        fs::rename(lib, &moved).unwrap();
        symlink("other", lib).unwrap();
        assert!(fixture.resolve().is_err());
    }

    #[test]
    fn manifest_and_object_hashes_sizes_and_pins_must_match() {
        let fixture = Fixture::managed();
        fs::write(&fixture.manifest, b"{}").unwrap();
        assert!(fixture.resolve().is_err());
        let fixture = Fixture::managed();
        let mut bytes = object();
        bytes[63] = 1;
        fs::write(&fixture.object, bytes).unwrap();
        assert!(fixture.resolve().is_err());
        for (field, value) in [
            ("sha256", json!("a".repeat(64))),
            ("size", json!(65)),
            ("mode", json!(493)),
            ("license", json!("Apache-2.0")),
        ] {
            let fixture = Fixture::managed_with(|manifest| manifest["files"][0][field] = value);
            assert!(fixture.resolve().is_err());
        }
        for (field, value) in [
            ("role", json!("robot")),
            ("format", json!("actryn-release-2")),
            ("version", json!("0.0.2")),
        ] {
            assert!(Fixture::managed_with(|manifest| manifest[field] = value)
                .resolve()
                .is_err());
        }
        assert!(Fixture::managed_with(
            |manifest| manifest["target"]["kernel_release"] = json!("other")
        )
        .resolve()
        .is_err());
        assert!(Fixture::managed_with(
            |manifest| manifest["target"]["architecture"] = json!("arm64")
        )
        .resolve()
        .is_err());
        assert!(Fixture::managed_with(|manifest| {
            let entry = manifest["files"][0].clone();
            manifest["files"].as_array_mut().unwrap().push(entry);
        })
        .resolve()
        .is_err());
    }

    #[test]
    fn protected_files_cannot_be_symlinked_hardlinked_or_wrong_elf() {
        for manifest in [false, true] {
            let fixture = Fixture::managed();
            let path = if manifest {
                &fixture.manifest
            } else {
                &fixture.object
            };
            fs::hard_link(path, path.with_extension("copy")).unwrap();
            assert!(fixture.resolve().is_err());
            fs::remove_file(path.with_extension("copy")).unwrap();
            let moved = path.with_extension("moved");
            fs::rename(path, &moved).unwrap();
            symlink(moved.file_name().unwrap(), path).unwrap();
            assert!(fixture.resolve().is_err());
        }
        for index in [0, 4, 5, 16, 18] {
            let mut bytes = object();
            bytes[index] ^= 1;
            assert!(Fixture::managed_object(&bytes, |_| {}).resolve().is_err());
        }
    }
}
