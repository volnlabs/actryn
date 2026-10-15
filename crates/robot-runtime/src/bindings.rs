use crate::{Binding, Error, Prepared, Result};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::Path,
};
#[derive(Serialize, Deserialize)]
struct Artifact {
    version: u32,
    prepared: Prepared,
}
fn name(binding: &Binding) -> String {
    format!("binding-{}.json", crate::hex(&binding.namespace))
}
pub(crate) fn persist(root: &Path, prepared: &Prepared) -> Result<()> {
    // Sixteen registry namespaces bound retained preparation artifacts; no eviction.
    let count = fs::read_dir(root)?
        .take(65)
        .collect::<std::io::Result<Vec<_>>>()?;
    if count.len() > 64
        || count
            .iter()
            .filter(|v| v.file_name().to_string_lossy().starts_with("binding-"))
            .count()
            >= 16
    {
        return Err(Error::Denied("historical binding capacity"));
    }
    let bytes = serde_json::to_vec(&Artifact {
        version: 1,
        prepared: prepared.clone(),
    })
    .map_err(|_| Error::Denied("binding encode"))?;
    if bytes.len() > 1024 {
        return Err(Error::Denied("binding byte capacity"));
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(root.join(name(&prepared.binding)))?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    fs::File::open(root)?.sync_all()?;
    Ok(())
}
pub(crate) fn load(
    root: &Path,
    principal: [u8; 32],
    attempt: [u8; 16],
    namespace: [u8; 16],
) -> Result<Prepared> {
    let binding = Binding {
        principal,
        attempt,
        namespace,
        session_deadline_ns: 0,
    };
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(root.join(name(&binding)))?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.len() > 1024
        || metadata.uid() != unsafe { libc::geteuid() }
        || metadata.mode() & 0o077 != 0
    {
        return Err(Error::Denied("invalid retained binding file"));
    }
    let mut bytes = vec![];
    Read::by_ref(&mut file).take(1025).read_to_end(&mut bytes)?;
    let artifact: Artifact =
        serde_json::from_slice(&bytes).map_err(|_| Error::Denied("malformed retained binding"))?;
    if artifact.version != 1
        || artifact.prepared.binding.principal != principal
        || artifact.prepared.binding.attempt != attempt
        || artifact.prepared.binding.namespace != namespace
        || artifact.prepared.configuration_digest != crate::configuration_digest()
        || artifact.prepared.instance == 0
        || artifact.prepared.runtime_epoch == [0; 16]
    {
        return Err(Error::Denied("retained immutable binding mismatch"));
    }
    Ok(artifact.prepared)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn durable_private_binding_rejects_forgery_and_never_recreates_corruption() {
        let dir = tempfile::tempdir().unwrap();
        let prepared = Prepared {
            binding: Binding {
                principal: [1; 32],
                attempt: [2; 16],
                namespace: [3; 16],
                session_deadline_ns: 99,
            },
            instance: 1,
            configuration_digest: crate::configuration_digest(),
            runtime_epoch: [4; 16],
        };
        persist(dir.path(), &prepared).unwrap();
        assert_eq!(
            load(dir.path(), [1; 32], [2; 16], [3; 16]).unwrap().binding,
            prepared.binding
        );
        assert!(load(dir.path(), [9; 32], [2; 16], [3; 16]).is_err());
        assert!(load(dir.path(), [1; 32], [9; 16], [3; 16]).is_err());
        fs::write(dir.path().join(name(&prepared.binding)), b"corrupt").unwrap();
        assert!(load(dir.path(), [1; 32], [2; 16], [3; 16]).is_err());
        assert!(persist(dir.path(), &prepared).is_err());
        assert_eq!(
            fs::read(dir.path().join(name(&prepared.binding))).unwrap(),
            b"corrupt"
        );
    }
}
