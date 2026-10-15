use crate::{valid_principal, ALPN};
use anyhow::{ensure, Context, Result};
use rustls::{
    pki_types::{CertificateDer, PrivateKeyDer},
    RootCertStore,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
use x509_parser::prelude::{FromDer, X509Certificate};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Scope {
    Read,
    Propose,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PrincipalPolicy {
    pub principal: String,
    pub scopes: Vec<Scope>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    /// Leaf-certificate SHA-256 fingerprints. Only local installation changes this map.
    pub certificates: BTreeMap<String, PrincipalPolicy>,
    pub revoked: BTreeSet<String>,
}
impl Policy {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.certificates.len() <= 128 && self.revoked.len() <= 128,
            "principal capacity"
        );
        for (fingerprint, p) in &self.certificates {
            ensure!(
                fingerprint.len() == 64
                    && fingerprint
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
                "invalid certificate fingerprint"
            );
            ensure!(
                valid_principal(&p.principal) && !p.scopes.is_empty() && p.scopes.len() <= 2,
                "invalid principal policy"
            );
        }
        ensure!(
            self.revoked.iter().all(|p| valid_principal(p)),
            "invalid revocation policy"
        );
        Ok(())
    }
    /// Call only after rustls has authenticated the complete client chain.
    pub fn authenticated(&self, leaf: &[u8], wall_ns: u64, boot_ns: u64) -> Result<Session> {
        self.validate()?;
        ensure!(leaf.len() <= 24_576, "certificate size");
        let fingerprint = fingerprint(leaf);
        let policy = self
            .certificates
            .get(&fingerprint)
            .context("uninstalled certificate")?;
        ensure!(
            !self.revoked.contains(&policy.principal),
            "principal revoked"
        );
        let after = certificate_valid_until(leaf, wall_ns)?;
        let remaining = (after - wall_ns).min(300_000_000_000);
        Ok(Session {
            principal: policy.principal.clone(),
            fingerprint,
            principal_id: Sha256::digest(policy.principal.as_bytes()).into(),
            deadline_ns: boot_ns
                .checked_add(remaining)
                .context("session time overflow")?,
            scopes: policy.scopes.clone(),
        })
    }
}
#[derive(Clone, Debug)]
pub struct Session {
    pub principal: String,
    pub principal_id: [u8; 32],
    pub fingerprint: String,
    pub deadline_ns: u64,
    pub scopes: Vec<Scope>,
}
impl Session {
    pub fn authorize(&self, policy: &Policy, scope: Scope, boot_ns: u64) -> Result<()> {
        let current = policy
            .certificates
            .get(&self.fingerprint)
            .context("certificate removed")?;
        ensure!(
            boot_ns < self.deadline_ns
                && current.principal == self.principal
                && !policy.revoked.contains(&self.principal)
                && current.scopes.contains(&scope)
                && self.scopes.contains(&scope),
            "expired/revoked/forbidden session"
        );
        Ok(())
    }
}
pub fn certificate_valid_until(leaf: &[u8], wall_ns: u64) -> Result<u64> {
    ensure!(leaf.len() <= 24_576, "certificate size");
    let (remaining, cert) =
        X509Certificate::from_der(leaf).map_err(|_| anyhow::anyhow!("certificate structure"))?;
    ensure!(remaining.is_empty(), "trailing certificate data");
    let before = u64::try_from(cert.validity().not_before.timestamp())?
        .checked_mul(1_000_000_000)
        .context("certificate time overflow")?;
    let after = u64::try_from(cert.validity().not_after.timestamp())?
        .checked_mul(1_000_000_000)
        .context("certificate time overflow")?;
    ensure!(
        before <= wall_ns && wall_ns < after,
        "certificate outside validity"
    );
    Ok(after)
}
pub fn fingerprint(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub fn certificates(pem: &[u8]) -> Result<Vec<CertificateDer<'static>>> {
    ensure!(pem.len() <= 24_576, "certificate bundle size");
    let certs = rustls_pemfile::certs(&mut &*pem).collect::<std::io::Result<Vec<_>>>()?;
    ensure!(
        !certs.is_empty() && certs.len() <= 4,
        "certificate chain length"
    );
    Ok(certs)
}
pub fn private_key(pem: &[u8]) -> Result<PrivateKeyDer<'static>> {
    ensure!(pem.len() <= 8192, "private key size");
    rustls_pemfile::private_key(&mut &*pem)?.context("private key missing")
}
fn roots(pem: &[u8]) -> Result<RootCertStore> {
    let mut roots = RootCertStore::empty();
    for c in certificates(pem)? {
        roots.add(c)?;
    }
    Ok(roots)
}
pub fn server_tls(ca: &[u8], certificate: &[u8], key: &[u8]) -> Result<Arc<rustls::ServerConfig>> {
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let verifier = rustls::server::WebPkiClientVerifier::builder_with_provider(
        Arc::new(roots(ca)?),
        provider.clone(),
    )
    .build()?;
    let mut config = rustls::ServerConfig::builder_with_provider(provider)
        .with_protocol_versions(&[&rustls::version::TLS13])?
        .with_client_cert_verifier(verifier)
        .with_single_cert(certificates(certificate)?, private_key(key)?)?;
    config.alpn_protocols = vec![ALPN.to_vec()];
    config.max_early_data_size = 0;
    config.send_tls13_tickets = 0;
    config.session_storage = Arc::new(rustls::server::NoServerSessionStorage {});
    config.max_fragment_size = Some(4096);
    Ok(Arc::new(config))
}
pub fn client_tls(ca: &[u8], certificate: &[u8], key: &[u8]) -> Result<Arc<rustls::ClientConfig>> {
    let mut config = rustls::ClientConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_protocol_versions(&[&rustls::version::TLS13])?
    .with_root_certificates(roots(ca)?)
    .with_client_auth_cert(certificates(certificate)?, private_key(key)?)?;
    config.alpn_protocols = vec![ALPN.to_vec()];
    config.enable_early_data = false;
    config.resumption = rustls::client::Resumption::disabled();
    config.max_fragment_size = Some(4096);
    Ok(Arc::new(config))
}

/// Wall time may advance with BOOTTIME, but a discontinuity latches closed until
/// explicit local clock recovery. The caller persists the last trusted wall floor.
pub struct ClockGuard {
    wall_ns: u64,
    boot_ns: u64,
    last_boot_ns: u64,
    faulted: bool,
}
impl ClockGuard {
    pub fn new(wall_ns: u64, boot_ns: u64, persisted_wall_floor: u64) -> Result<Self> {
        ensure!(
            wall_ns >= persisted_wall_floor,
            "wall clock rollback since durable checkpoint"
        );
        Ok(Self {
            wall_ns,
            boot_ns,
            last_boot_ns: boot_ns,
            faulted: false,
        })
    }
    pub fn check(&mut self, wall_ns: u64, boot_ns: u64) -> Result<()> {
        let expected = boot_ns
            .checked_sub(self.boot_ns)
            .and_then(|delta| self.wall_ns.checked_add(delta));
        // One second is a conservative administrative uncertainty bound, not robot timing.
        if boot_ns < self.last_boot_ns
            || expected.is_none_or(|value| value.abs_diff(wall_ns) > 1_000_000_000)
        {
            self.faulted = true;
        }
        ensure!(!self.faulted, "wall/boot clock discontinuity");
        self.last_boot_ns = boot_ns;
        Ok(())
    }
}
