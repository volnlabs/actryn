//! Narrow, digest-verified offline OCI profile. No image runtime hooks are interpreted.
use crate::launcher::{trusted_path, Artifact, LauncherConfig};
use anyhow::{ensure, Context, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};
pub const REGISTRY: &str = "/var/lib/actryn-artifacts";
pub const CAPACITY: usize = 8;
const MAX_LAYER: usize = 16 * 1024 * 1024;
const MAX_JSON: usize = 16 * 1024;
const MANIFEST: &str = "application/vnd.oci.image.manifest.v1+json";
const CONFIG: &str = "application/vnd.oci.image.config.v1+json";
const LAYER: &str = "application/vnd.oci.image.layer.v1.tar";
const FILES: [(&str, usize); 3] = [
    ("bin/agent", 8 * 1024 * 1024),
    ("etc/actryn/input.json", 4096),
    ("etc/actryn/input.schema.json", 8192),
];
const DIRS: [&str; 8] = [
    "bin",
    "etc",
    "etc/actryn",
    "proc",
    "dev",
    "tmp",
    "run",
    "run/actryn-broker",
];
fn digest(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}
fn bounded(path: &Path, cap: usize) -> Result<Vec<u8>> {
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)?;
    let m = file.metadata()?;
    ensure!(
        m.is_file() && m.len() <= cap as u64,
        "artifact file type/size"
    );
    let mut data = Vec::new();
    (&mut file).take(cap as u64 + 1).read_to_end(&mut data)?;
    ensure!(data.len() <= cap, "artifact grew beyond cap");
    Ok(data)
}
fn object(path: &Path) -> Result<Value> {
    Ok(serde_json::from_slice(&bounded(path, MAX_JSON)?)?)
}
fn descriptor<'a>(value: &'a Value, media: &str, cap: usize) -> Result<(&'a str, usize)> {
    ensure!(value["mediaType"] == media, "unsupported OCI media type");
    let digest = value["digest"].as_str().context("descriptor digest")?;
    ensure!(
        crate::store::valid_digest(digest),
        "invalid OCI SHA-256 digest"
    );
    let size = value["size"].as_u64().context("descriptor size")?;
    ensure!(size > 0 && size <= cap as u64, "OCI descriptor exceeds cap");
    Ok((digest, size as usize))
}
fn blob(layout: &Path, value: &Value, media: &str, cap: usize) -> Result<(String, Vec<u8>)> {
    let (hash, size) = descriptor(value, media, cap)?;
    for dir in [layout.join("blobs"), layout.join("blobs/sha256")] {
        ensure!(
            fs::symlink_metadata(dir)?.is_dir(),
            "blob path is not a directory"
        );
    }
    let bytes = bounded(&layout.join("blobs/sha256").join(&hash[7..]), cap)?;
    ensure!(
        bytes.len() == size && digest(&bytes) == hash,
        "OCI blob digest/size mismatch"
    );
    Ok((hash.into(), bytes))
}
fn static_elf(bytes: &[u8]) -> Result<()> {
    ensure!(
        bytes.len() >= 64
            && &bytes[..6] == b"\x7fELF\x02\x01"
            && bytes[18..20] == 62u16.to_le_bytes(),
        "agent must be a static Linux amd64 ELF"
    );
    let offset = u64::from_le_bytes(bytes[32..40].try_into()?) as usize;
    let size = u16::from_le_bytes(bytes[54..56].try_into()?) as usize;
    let count = u16::from_le_bytes(bytes[56..58].try_into()?) as usize;
    ensure!(
        size == 56
            && (1..=128).contains(&count)
            && offset <= bytes.len()
            && count * size <= bytes.len() - offset,
        "invalid ELF program headers"
    );
    let mut load = false;
    for n in 0..count {
        let start = offset + n * size;
        let kind = u32::from_le_bytes(bytes[start..start + 4].try_into()?);
        ensure!(kind != 3, "dynamic ELF interpreter unsupported");
        load |= kind == 1;
    }
    ensure!(load, "ELF load segment missing");
    Ok(())
}
struct Verified {
    hash: String,
    profile: String,
    blobs: BTreeMap<String, Vec<u8>>,
    files: BTreeMap<String, Vec<u8>>,
    index: Vec<u8>,
}
impl Verified {
    fn read(layout: &Path, expected: &str) -> Result<Self> {
        ensure!(
            crate::store::valid_digest(expected),
            "expected manifest digest required"
        );
        ensure!(
            object(&layout.join("oci-layout"))?["imageLayoutVersion"] == "1.0.0",
            "unsupported OCI layout"
        );
        let index = bounded(&layout.join("index.json"), MAX_JSON)?;
        let value: Value = serde_json::from_slice(&index)?;
        ensure!(value["schemaVersion"] == 2, "unsupported image index");
        let manifests = value["manifests"]
            .as_array()
            .context("manifest list missing")?;
        ensure!(
            manifests.len() == 1 && manifests[0]["digest"] == expected,
            "index must select exactly the approved manifest"
        );
        let (hash, manifest) = blob(layout, &manifests[0], MANIFEST, MAX_JSON)?;
        let value: Value = serde_json::from_slice(&manifest)?;
        ensure!(
            value["schemaVersion"] == 2 && value["mediaType"] == MANIFEST,
            "invalid OCI image manifest"
        );
        let layers = value["layers"].as_array().context("layer list missing")?;
        ensure!(layers.len() == 1, "preview requires one uncompressed layer");
        let (layer_hash, layer) = blob(layout, &layers[0], LAYER, MAX_LAYER)?;
        let (config_hash, config) = blob(layout, &value["config"], CONFIG, MAX_JSON)?;
        let value: Value = serde_json::from_slice(&config)?;
        ensure!(
            value["architecture"] == "amd64"
                && value["os"] == "linux"
                && value["rootfs"] == json!({"type":"layers","diff_ids":[layer_hash]}),
            "unsupported image platform/rootfs"
        );
        let profile = value["config"]["Labels"]["org.actryn.profile"]
            .as_str()
            .context("artifact profile missing")?
            .to_owned();
        ensure!(
            value["config"] == image_configuration(&profile)?,
            "unapproved image process configuration"
        );
        let mut archive = tar::Archive::new(layer.as_slice());
        let mut files = BTreeMap::new();
        for entry in archive.entries()?.raw(true) {
            let mut entry = entry?;
            let header = entry.header();
            ensure!(
                header.entry_type() == tar::EntryType::Regular,
                "only regular USTAR files supported"
            );
            ensure!(
                header.as_ustar().is_some()
                    && header.uid()? == 0
                    && header.gid()? == 0
                    && header.mode()? & 0o7000 == 0
                    && header.link_name()?.is_none(),
                "unsupported layer metadata"
            );
            let raw = entry.path_bytes();
            let name = std::str::from_utf8(&raw)?.to_owned();
            let cap = FILES
                .iter()
                .find(|(path, _)| *path == name)
                .context("layer path outside fixed preview profile")?
                .1;
            ensure!(
                !files.contains_key(&name) && entry.size() > 0 && entry.size() <= cap as u64,
                "duplicate or oversized layer file"
            );
            let mut bytes = Vec::new();
            entry.read_to_end(&mut bytes)?;
            ensure!(bytes.len() <= cap, "layer file exceeds cap");
            files.insert(name, bytes);
        }
        ensure!(files.len() == FILES.len(), "preview file set incomplete");
        static_elf(&files["bin/agent"])?;
        let input: Value = serde_json::from_slice(&files["etc/actryn/input.json"])?;
        let expected_mode = if profile == "live-preview-v1" {
            "live"
        } else {
            "offline"
        };
        ensure!(
            input.get("mode").unwrap_or(&json!("offline")) == expected_mode,
            "input mode differs from approved artifact profile"
        );
        let _: Value = serde_json::from_slice(&files["etc/actryn/input.schema.json"])?;
        Ok(Self {
            hash,
            profile,
            blobs: BTreeMap::from([
                (expected.into(), manifest),
                (config_hash, config),
                (layer_hash, layer),
            ]),
            files,
            index,
        })
    }
    fn install(&self, registry: &Path) -> Result<PathBuf> {
        let installed = registry.join(&self.hash[7..]);
        if installed.exists() {
            verify_installed(&installed, &self.hash, false)?;
            return Ok(installed);
        }
        available(registry, CAPACITY)?;
        let staging = registry.join(format!(".incomplete-{}", &self.hash[7..]));
        fs::create_dir(&staging)?;
        fs::set_permissions(&staging, fs::Permissions::from_mode(0o700))?;
        let root = staging.join("rootfs");
        fs::create_dir(&root)?;
        for dir in DIRS {
            fs::create_dir(root.join(dir))?;
        }
        for (name, bytes) in &self.files {
            write_new(
                &root.join(name),
                bytes,
                if name == "bin/agent" { 0o555 } else { 0o444 },
            )?;
        }
        let layout = staging.join("layout");
        fs::create_dir(&layout)?;
        fs::create_dir(layout.join("blobs"))?;
        fs::create_dir(layout.join("blobs/sha256"))?;
        for (hash, bytes) in &self.blobs {
            write_new(&layout.join("blobs/sha256").join(&hash[7..]), bytes, 0o444)?;
        }
        write_new(
            &layout.join("oci-layout"),
            b"{\"imageLayoutVersion\":\"1.0.0\"}",
            0o444,
        )?;
        write_new(&layout.join("index.json"), &self.index, 0o444)?;
        // Every child and directory is durable before the completion marker and rename.
        for dir in DIRS.into_iter().rev() {
            seal_dir(&root.join(dir))?;
        }
        seal_dir(&root)?;
        seal_dir(&layout.join("blobs/sha256"))?;
        seal_dir(&layout.join("blobs"))?;
        seal_dir(&layout)?;
        write_new(
            &staging.join("ready.json"),
            &serde_json::to_vec(&json!({"schema":1,"manifest":self.hash}))?,
            0o444,
        )?;
        seal_dir(&staging)?;
        fs::rename(&staging, &installed)?;
        File::open(registry)?.sync_all()?;
        Ok(installed)
    }
}
fn write_new(path: &Path, bytes: &[u8], mode: u32) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(mode)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
fn seal_dir(path: &Path) -> Result<()> {
    fs::set_permissions(path, fs::Permissions::from_mode(0o555))?;
    File::open(path)?.sync_all()?;
    Ok(())
}
fn available(registry: &Path, cap: usize) -> Result<()> {
    let mut count = 0;
    for entry in fs::read_dir(registry)? {
        let entry = entry?;
        if entry.file_name() == "import.lock" {
            continue;
        }
        count += 1;
        ensure!(
            count < cap,
            "artifact capacity exhausted; incomplete slots remain reserved"
        );
    }
    Ok(())
}
fn verify_installed(installed: &Path, expected: &str, trusted: bool) -> Result<Verified> {
    if trusted {
        trusted_path(installed)?;
    }
    ensure!(
        object(&installed.join("ready.json"))? == json!({"schema":1,"manifest":expected}),
        "artifact not durably complete"
    );
    let v = Verified::read(&installed.join("layout"), expected)?;
    let root = installed.join("rootfs");
    let mut queue = vec![root.clone()];
    let mut seen = 0;
    while let Some(dir) = queue.pop() {
        if trusted {
            trusted_path(&dir)?;
        }
        for entry in fs::read_dir(&dir)? {
            let entry = entry?;
            let path = entry.path();
            let m = fs::symlink_metadata(&path)?;
            seen += 1;
            ensure!(
                seen <= FILES.len() + DIRS.len(),
                "unexpected rootfs entries"
            );
            let name = path.strip_prefix(&root)?.to_str().context("rootfs UTF-8")?;
            if trusted {
                ensure!(
                    m.uid() == 0 && m.mode() & 0o022 == 0,
                    "untrusted rootfs ownership/mode"
                );
            }
            if m.is_dir() {
                ensure!(DIRS.contains(&name), "unapproved rootfs directory");
                queue.push(path);
            } else {
                let wanted = v.files.get(name).context("unapproved rootfs file")?;
                ensure!(
                    m.is_file() && m.nlink() == 1 && bounded(&path, wanted.len())? == *wanted,
                    "installed rootfs differs from OCI content"
                );
                ensure!(
                    m.mode() & 0o777 == if name == "bin/agent" { 0o555 } else { 0o444 },
                    "rootfs file mode changed"
                );
            }
        }
    }
    ensure!(
        seen == FILES.len() + DIRS.len(),
        "rootfs file set incomplete"
    );
    Ok(v)
}
/// Every prepare and start must validate the fixed installed path and its original OCI content.
pub fn validate_approved(hash: &str, artifact: &Artifact) -> Result<()> {
    ensure!(crate::store::valid_digest(hash), "invalid approved digest");
    let installed = Path::new(REGISTRY).join(&hash[7..]);
    ensure!(
        artifact.rootfs == installed.join("rootfs") && artifact.argv == ["/bin/agent"],
        "artifact must refer to the verified import registry"
    );
    verify_installed(&installed, hash, true).map(|_| ())
}
fn lock_broker(uid: u32) -> Result<File> {
    use std::os::fd::AsRawFd;
    let path = Path::new("/var/lib/actryn-server/broker/server.lock");
    let file = match OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)
    {
        Ok(file) => {
            ensure!(
                unsafe { libc::fchown(file.as_raw_fd(), uid, u32::MAX) } == 0,
                "broker lock ownership"
            );
            file
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => OpenOptions::new()
            .write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)?,
        Err(error) => return Err(error.into()),
    };
    let m = file.metadata()?;
    ensure!(
        m.is_file() && m.uid() == uid && m.mode() & 0o077 == 0,
        "broker lock identity"
    );
    ensure!(
        unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0,
        "server daemon must be stopped during import"
    );
    Ok(file)
}
pub fn methods_for_profile(profile: &str) -> Result<&'static [&'static str]> {
    match profile {
        "offline-preview-v1" => Ok(&["model.offline", "diagnostic.echo"]),
        "live-preview-v1" => Ok(&["model.propose", "diagnostic.echo"]),
        _ => anyhow::bail!("unapproved broker artifact profile"),
    }
}
pub fn image_configuration(profile: &str) -> Result<Value> {
    methods_for_profile(profile)?;
    let mut labels = json!({"org.actryn.profile":profile});
    if profile == "live-preview-v1" {
        labels["org.actryn.model"] = json!(crate::model::MODEL);
        labels["org.actryn.model-policy"] = json!(crate::model::policy_digest()?);
    }
    Ok(
        json!({"Entrypoint":["/bin/agent"],"User":"65532:65532","WorkingDir":"/tmp","Labels":labels}),
    )
}
pub fn broker_methods(hash: &str) -> Result<&'static [&'static str]> {
    ensure!(crate::store::valid_digest(hash), "invalid artifact digest");
    let installed = Path::new(REGISTRY).join(&hash[7..]);
    let verified = verify_installed(&installed, hash, true)?;
    methods_for_profile(&verified.profile)
}
/// Administrator-only, offline import. Daemons must be stopped to publish an approval map.
pub fn import(layout: &Path, expected: &str) -> Result<Value> {
    ensure!(
        unsafe { libc::geteuid() } == 0,
        "artifact import requires root"
    );
    trusted_path(layout)?;
    fs::create_dir_all(REGISTRY)?;
    trusted_path(Path::new(REGISTRY))?;
    let _lock = crate::launcher::lock_service(&Path::new(REGISTRY).join("import.lock"))?;
    let _launcher =
        crate::launcher::lock_service(Path::new("/var/lib/actryn-server/launcher.lock"))?;
    let config_path = Path::new("/etc/actryn/server.json");
    trusted_path(config_path)?;
    let mut config: LauncherConfig = serde_json::from_slice(&bounded(config_path, 65536)?)?;
    ensure!(
        config.server_uid != 0 && config.server_uid != config.operator_uid,
        "invalid service identity"
    );
    let _server = lock_broker(config.server_uid)?;
    ensure!(
        config.artifacts.len() < CAPACITY || config.artifacts.contains_key(expected),
        "approved registry full"
    );
    let v = Verified::read(layout, expected)?;
    let installed = v.install(Path::new(REGISTRY))?;
    verify_installed(&installed, expected, true)?;
    let artifact = Artifact {
        rootfs: installed.join("rootfs"),
        argv: vec!["/bin/agent".into()],
    };
    config.artifacts.insert(expected.into(), artifact);
    let temp = config_path.with_file_name(format!("server.json.importing-{}", &expected[7..]));
    write_new(&temp, &serde_json::to_vec(&config)?, 0o644)?;
    LauncherConfig::read(&temp).context("complete imported approval map validation")?;
    fs::rename(temp, config_path)?;
    File::open(config_path.parent().unwrap())?.sync_all()?;
    Ok(
        json!({"result":"imported","artifact_digest":expected,"rootfs":installed.join("rootfs"),"daemon_restart_required":true,"authority_issued":false}),
    )
}
/// Explicit administrator recovery discards only an unfinished import, never an installed slot.
pub fn discard_incomplete(expected: &str) -> Result<Value> {
    ensure!(
        unsafe { libc::geteuid() } == 0 && crate::store::valid_digest(expected),
        "root and a valid manifest digest required"
    );
    trusted_path(Path::new(REGISTRY))?;
    let _import = crate::launcher::lock_service(&Path::new(REGISTRY).join("import.lock"))?;
    let _launcher =
        crate::launcher::lock_service(Path::new("/var/lib/actryn-server/launcher.lock"))?;
    let config_path = Path::new("/etc/actryn/server.json");
    trusted_path(config_path)?;
    let config: LauncherConfig = serde_json::from_slice(&bounded(config_path, 65536)?)?;
    let _server = lock_broker(config.server_uid)?;
    let staging = Path::new(REGISTRY).join(format!(".incomplete-{}", &expected[7..]));
    if staging.exists() {
        trusted_path(&staging)?;
        ensure!(staging.is_dir(), "incomplete slot is not a directory");
        fs::remove_dir_all(&staging)?;
        File::open(REGISTRY)?.sync_all()?;
    }
    let temp = config_path.with_file_name(format!("server.json.importing-{}", &expected[7..]));
    if temp.exists() {
        trusted_path(&temp)?;
        let _ = bounded(&temp, 65536)?;
        fs::remove_file(temp)?;
        File::open(config_path.parent().unwrap())?.sync_all()?;
    }
    Ok(
        json!({"result":"incomplete_import_discarded","artifact_digest":expected,"installed_artifact_removed":false,"authority_issued":false}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn layer(entries: &[(&str, &[u8], tar::EntryType)]) -> Vec<u8> {
        let mut builder = tar::Builder::new(Vec::new());
        for (path, bytes, kind) in entries {
            let mut h = tar::Header::new_ustar();
            h.set_size(bytes.len() as u64);
            h.set_mode(0o644);
            h.set_uid(0);
            h.set_gid(0);
            h.set_mtime(0);
            h.set_entry_type(*kind);
            h.set_cksum();
            builder.append_data(&mut h, path, *bytes).unwrap();
        }
        builder.into_inner().unwrap()
    }
    fn image(dir: &std::path::Path, layer: &[u8]) -> String {
        configured_image(
            dir,
            layer,
            image_configuration("offline-preview-v1").unwrap(),
        )
    }
    fn configured_image(dir: &std::path::Path, layer: &[u8], config: Value) -> String {
        std::fs::create_dir_all(dir.join("blobs/sha256")).unwrap();
        let add = |bytes: &[u8], media: &str| {
            let digest = digest(bytes);
            std::fs::write(dir.join("blobs/sha256").join(&digest[7..]), bytes).unwrap();
            json!({"mediaType":media,"digest":digest,"size":bytes.len()})
        };
        let layer = add(layer, LAYER);
        let config = json!({"architecture":"amd64","os":"linux","config":config,"rootfs":{"type":"layers","diff_ids":[layer["digest"]]}});
        let config = add(&serde_json::to_vec(&config).unwrap(), CONFIG);
        let manifest = add(
            &serde_json::to_vec(
                &json!({"schemaVersion":2,"mediaType":MANIFEST,"config":config,"layers":[layer]}),
            )
            .unwrap(),
            MANIFEST,
        );
        std::fs::write(
            dir.join("index.json"),
            serde_json::to_vec(&json!({"schemaVersion":2,"manifests":[manifest]})).unwrap(),
        )
        .unwrap();
        std::fs::write(
            dir.join("oci-layout"),
            b"{\"imageLayoutVersion\":\"1.0.0\"}",
        )
        .unwrap();
        manifest["digest"].as_str().unwrap().into()
    }
    fn valid_layer() -> Vec<u8> {
        input_layer(b"{}")
    }
    fn input_layer(input: &[u8]) -> Vec<u8> {
        let mut elf = vec![0u8; 120];
        elf[..6].copy_from_slice(b"\x7fELF\x02\x01");
        elf[18..20].copy_from_slice(&62u16.to_le_bytes());
        elf[32..40].copy_from_slice(&64u64.to_le_bytes());
        elf[54..56].copy_from_slice(&56u16.to_le_bytes());
        elf[56..58].copy_from_slice(&1u16.to_le_bytes());
        elf[64..68].copy_from_slice(&1u32.to_le_bytes());
        layer(&[
            ("bin/agent", elf.as_slice(), tar::EntryType::Regular),
            ("etc/actryn/input.json", input, tar::EntryType::Regular),
            (
                "etc/actryn/input.schema.json",
                b"{}",
                tar::EntryType::Regular,
            ),
        ])
    }
    #[test]
    fn live_content_cannot_change_model_policy_or_claim_offline_profile() {
        let source = tempfile::tempdir().unwrap();
        let layer = input_layer(br#"{"mode":"live"}"#);
        let config = image_configuration("live-preview-v1").unwrap();
        let hash = configured_image(source.path(), &layer, config.clone());
        assert_eq!(
            Verified::read(source.path(), &hash).unwrap().profile,
            "live-preview-v1"
        );
        let mut different_policy = config;
        different_policy["Labels"]["org.actryn.model-policy"] =
            json!(format!("sha256:{}", "0".repeat(64)));
        let hash = configured_image(source.path(), &layer, different_policy);
        assert!(Verified::read(source.path(), &hash).is_err());
        let hash = image(source.path(), &layer);
        assert!(Verified::read(source.path(), &hash).is_err());
        let hash = configured_image(
            source.path(),
            &valid_layer(),
            image_configuration("live-preview-v1").unwrap(),
        );
        assert!(Verified::read(source.path(), &hash).is_err());
        let hash = image(source.path(), &input_layer(br#"{"mode":null}"#));
        assert!(Verified::read(source.path(), &hash).is_err());
    }
    #[test]
    fn digest_is_real_and_malformed_or_oversized_layers_never_publish() {
        let source = tempfile::tempdir().unwrap();
        let hash = image(source.path(), &valid_layer());
        assert!(Verified::read(source.path(), &hash).is_ok());
        assert!(Verified::read(source.path(), &format!("sha256:{}", "0".repeat(64))).is_err());
        let file = source.path().join("blobs/sha256").join(&hash[7..]);
        std::fs::write(file, b"{}").unwrap();
        assert!(Verified::read(source.path(), &hash).is_err());
        for bad in [
            layer(&[("evil", b"x", tar::EntryType::Regular)]),
            layer(&[("bin/agent", b"", tar::EntryType::Symlink)]),
            layer(&[
                ("bin/agent", b"x", tar::EntryType::Regular),
                ("bin/agent", b"x", tar::EntryType::Regular),
            ]),
            vec![0; MAX_LAYER + 1],
        ] {
            let source = tempfile::tempdir().unwrap();
            let hash = image(source.path(), &bad);
            assert!(Verified::read(source.path(), &hash).is_err());
        }
    }
    #[test]
    fn staged_slots_count_and_tampering_or_interruption_never_launches() {
        let source = tempfile::tempdir().unwrap();
        let hash = image(source.path(), &valid_layer());
        let v = Verified::read(source.path(), &hash).unwrap();
        let registry = tempfile::tempdir().unwrap();
        let staging = registry.path().join(".incomplete");
        std::fs::create_dir(&staging).unwrap();
        assert!(available(registry.path(), 1).is_err());
        assert!(verify_installed(&staging, &hash, false).is_err());
        std::fs::remove_dir(staging).unwrap();
        let root = v.install(registry.path()).unwrap();
        assert!(verify_installed(&root, &hash, false).is_ok());
        std::fs::set_permissions(
            root.join("rootfs/bin/agent"),
            std::fs::Permissions::from_mode(0o755),
        )
        .unwrap();
        std::fs::write(root.join("rootfs/bin/agent"), b"changed").unwrap();
        assert!(verify_installed(&root, &hash, false).is_err());
    }
}
