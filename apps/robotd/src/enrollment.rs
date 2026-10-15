use crate::storage::{private_directory, replace};
use anyhow::{ensure, Context, Result};
use rcgen::{CertificateParams, KeyPair, PublicKeyData};
use robot_rpc::{certificates, fingerprint, read_protected, server_tls};
use rustls::{
    client::danger::ServerCertVerifier,
    pki_types::{ServerName, UnixTime},
    RootCertStore,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Pending {
    dns_name: String,
    generation: String,
    csr_pem: String,
    csr_spki_sha256: String,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Active {
    dns_name: String,
    generation: String,
}
pub struct Identity {
    pub tls: Arc<rustls::ServerConfig>,
    pub dns_name: String,
    pub device_certificate_sha256: String,
    pub valid_until_wall_ns: u64,
}
fn generation(root: &Path, name: &str) -> Result<PathBuf> {
    ensure!(
        name.len() == 32
            && name
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "invalid identity generation"
    );
    Ok(root.join(name))
}
pub fn request(root: &Path, dns_name: String) -> Result<Value> {
    // Pending enrollment is stable across a lost reply; rotation needs installation first.
    if root.join("request.json").exists() {
        let p: Pending =
            serde_json::from_slice(&read_protected(&root.join("request.json"), 8192, true)?)?;
        ensure!(
            p.dns_name == dns_name,
            "pending enrollment has another DNS name"
        );
        return Ok(serde_json::to_value(p)?);
    }
    ensure!(
        fs::read_dir(root)?.take(12).count() < 10,
        "retained identity generation capacity"
    );
    let name = robot_rpc::random_id::<16>()?
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    let dir = generation(root, &name)?;
    private_directory(&dir)?;
    let key = KeyPair::generate()?;
    let params = CertificateParams::new(vec![dns_name.clone()])?;
    let csr_pem = params.serialize_request(&key)?.pem()?;
    replace(&dir.join("key.pem"), key.serialize_pem().as_bytes())?;
    let pending = Pending {
        dns_name,
        generation: name,
        csr_pem,
        csr_spki_sha256: fingerprint(&key.subject_public_key_info()),
    };
    replace(&root.join("request.json"), &serde_json::to_vec(&pending)?)?;
    Ok(serde_json::to_value(pending)?)
}
fn validate(ca: &[u8], chain: &[u8], key: &[u8], dns: &str, wall_ns: u64) -> Result<Identity> {
    let certs = certificates(chain)?;
    let mut roots = RootCertStore::empty();
    for cert in certificates(ca)? {
        roots.add(cert)?;
    }
    let verifier = rustls::client::WebPkiServerVerifier::builder_with_provider(
        Arc::new(roots),
        Arc::new(rustls::crypto::ring::default_provider()),
    )
    .build()?;
    verifier.verify_server_cert(
        &certs[0],
        &certs[1..],
        &ServerName::try_from(dns.to_owned())?,
        &[],
        UnixTime::since_unix_epoch(Duration::from_nanos(wall_ns)),
    )?;
    Ok(Identity {
        tls: server_tls(ca, chain, key)?,
        dns_name: dns.to_owned(),
        device_certificate_sha256: fingerprint(&certs[0]),
        valid_until_wall_ns: certs
            .iter()
            .map(|c| robot_rpc::certificate_valid_until(c, wall_ns))
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .min()
            .context("empty chain")?,
    })
}
pub fn install(root: &Path, chain: &[u8], ca: &[u8], wall_ns: u64) -> Result<Identity> {
    let pending: Pending =
        serde_json::from_slice(&read_protected(&root.join("request.json"), 8192, true)?)?;
    let dir = generation(root, &pending.generation)?;
    let key = read_protected(&dir.join("key.pem"), 8192, true)?;
    let identity = validate(ca, chain, &key, &pending.dns_name, wall_ns)?;
    replace(&dir.join("certificate.pem"), chain)?;
    replace(&dir.join("ca.pem"), ca)?;
    replace(
        &root.join("active.json"),
        &serde_json::to_vec(&Active {
            dns_name: pending.dns_name,
            generation: pending.generation,
        })?,
    )?;
    fs::remove_file(root.join("request.json"))?;
    fs::File::open(root)?.sync_all()?;
    Ok(identity)
}
pub fn load(root: &Path, wall_ns: u64) -> Result<Option<Identity>> {
    if !root.join("active.json").try_exists()? {
        return Ok(None);
    }
    let a: Active =
        serde_json::from_slice(&read_protected(&root.join("active.json"), 1024, true)?)?;
    let dir = generation(root, &a.generation)?;
    validate(
        &read_protected(&dir.join("ca.pem"), 24576, false)?,
        &read_protected(&dir.join("certificate.pem"), 24576, false)?,
        &read_protected(&dir.join("key.pem"), 8192, true)?,
        &a.dns_name,
        wall_ns,
    )
    .context("installed device identity")
    .map(Some)
}
pub fn report(identity: &Identity) -> Value {
    json!({"dns_name": identity.dns_name, "device_certificate_sha256": identity.device_certificate_sha256, "rearmed": false})
}

#[cfg(test)]
mod tests {
    use super::*;
    use rcgen::{BasicConstraints, ExtendedKeyUsagePurpose, IsCa, Issuer, KeyUsagePurpose};
    #[test]
    fn installation_requires_current_chain_dns_and_matching_local_key() {
        let mut params = CertificateParams::default();
        params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
        params.key_usages = vec![
            KeyUsagePurpose::KeyCertSign,
            KeyUsagePurpose::DigitalSignature,
        ];
        let key = KeyPair::generate().unwrap();
        let ca = params.self_signed(&key).unwrap();
        let issuer = Issuer::new(params, key);
        let mut leaf = CertificateParams::new(vec!["robot.test".to_owned()]).unwrap();
        leaf.not_before = std::time::SystemTime::now().into();
        leaf.not_after = leaf.not_before + Duration::from_secs(120);
        leaf.extended_key_usages = vec![ExtendedKeyUsagePurpose::ServerAuth];
        let key = KeyPair::generate().unwrap();
        let cert = leaf.signed_by(&key, &issuer).unwrap();
        let wall = crate::service::wall_ns().unwrap();
        let installed = validate(
            ca.pem().as_bytes(),
            cert.pem().as_bytes(),
            key.serialize_pem().as_bytes(),
            "robot.test",
            wall,
        )
        .unwrap();
        assert_eq!(installed.device_certificate_sha256, fingerprint(cert.der()));
        assert!(installed.valid_until_wall_ns > wall);
        assert!(validate(
            ca.pem().as_bytes(),
            cert.pem().as_bytes(),
            key.serialize_pem().as_bytes(),
            "alien.test",
            wall
        )
        .is_err());
        assert!(validate(
            ca.pem().as_bytes(),
            cert.pem().as_bytes(),
            KeyPair::generate().unwrap().serialize_pem().as_bytes(),
            "robot.test",
            wall
        )
        .is_err());
        assert!(validate(
            ca.pem().as_bytes(),
            cert.pem().as_bytes(),
            key.serialize_pem().as_bytes(),
            "robot.test",
            wall + 121_000_000_000
        )
        .is_err());
    }
    #[test]
    fn generation_cannot_escape_the_protected_identity_root() {
        for invalid in [
            "../key",
            "/etc/passwd",
            "",
            "................................",
        ] {
            assert!(generation(Path::new("/identity"), invalid).is_err());
        }
        assert_eq!(
            generation(Path::new("/identity"), &"a".repeat(32)).unwrap(),
            Path::new("/identity").join("a".repeat(32))
        );
    }
}
