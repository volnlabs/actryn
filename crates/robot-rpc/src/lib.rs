//! Bounded wire format and TLS identity; no method here issues an authority grant.
mod identity;
mod transport;
pub use identity::*;
pub use transport::*;
pub mod wire {
    include!(concat!(env!("OUT_DIR"), "/actryn.robot.v1.rs"));
}
use anyhow::{bail, ensure, Result};
use prost::Message;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
pub const VERSION: u32 = 1;
pub const MAX_MESSAGE: usize = 65_536;
pub const ALPN: &[u8] = b"actryn-rpc/1";

pub async fn read_message<M: Message + Default>(
    stream: &mut (impl AsyncRead + Unpin),
) -> Result<M> {
    let size = stream.read_u32().await? as usize;
    ensure!((1..=MAX_MESSAGE).contains(&size), "RPC frame size");
    let mut bytes = vec![0; size];
    stream.read_exact(&mut bytes).await?;
    let message = M::decode(bytes.as_slice())?;
    ensure!(
        message.encode_to_vec() == bytes,
        "noncanonical or unknown RPC fields"
    );
    Ok(message)
}
pub async fn write_message<M: Message>(
    stream: &mut (impl AsyncWrite + Unpin),
    message: &M,
) -> Result<()> {
    let bytes = message.encode_to_vec();
    ensure!((1..=MAX_MESSAGE).contains(&bytes.len()), "RPC frame size");
    stream.write_u32(bytes.len() as u32).await?;
    stream.write_all(&bytes).await?;
    stream.flush().await?;
    Ok(())
}
impl wire::Request {
    pub fn validate(&self) -> Result<()> {
        use wire::request::Command::*;
        ensure!(
            self.version == VERSION && self.request_id.len() == 16,
            "RPC version/correlation"
        );
        let command = self
            .command
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("missing command"))?;
        ensure!(
            self.robot_epoch.len() == 16
                || (self.robot_epoch.is_empty()
                    && matches!(command, Describe(_) | EnrollRequest(_) | EnrollInstall(_))),
            "robot epoch required"
        );
        let handle = |h: &wire::Handle, has_key: bool| -> Result<()> {
            ensure!(
                h.namespace.len() == 16 && h.key.len() == if has_key { 32 } else { 0 },
                "invalid stable handle"
            );
            Ok(())
        };
        match command {
            Observe(h) => handle(h, false)?,
            Query(h) | Cancel(h) => handle(h, true)?,
            Propose(p) => {
                handle(
                    p.handle
                        .as_ref()
                        .ok_or_else(|| anyhow::anyhow!("missing handle"))?,
                    true,
                )?;
                ensure!(
                    p.observation_id != 0 && p.parent_digest.len() == 32,
                    "invalid proposal lineage"
                );
                let t = p
                    .target
                    .as_ref()
                    .ok_or_else(|| anyhow::anyhow!("missing target"))?;
                ensure!(
                    (-100..=100).contains(&t.left_delta_ticks)
                        && (-100..=100).contains(&t.right_delta_ticks)
                        && (1..=10000).contains(&t.duration_ms),
                    "target outside fixed skill envelope"
                );
            }
            Prepare(p) => ensure!(
                p.attempt.len() == 16 && p.namespace.len() == 16 && valid_principal(&p.principal),
                "invalid prepared binding"
            ),
            Grant(g) => ensure!((1..=60_000).contains(&g.duration_ms), "grant duration"),
            EnrollRequest(e) => ensure!(
                !e.dns_name.is_empty()
                    && e.dns_name.len() <= 253
                    && e.dns_name
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'.'),
                "invalid device DNS name"
            ),
            EnrollInstall(e) => ensure!(
                !e.certificate_pem.is_empty()
                    && e.certificate_pem.len() <= 24_576
                    && !e.ca_pem.is_empty()
                    && e.ca_pem.len() <= 24_576,
                "enrollment material size"
            ),
            RevokePrincipal(p) => ensure!(valid_principal(&p.principal), "invalid principal"),
            _ => (),
        }
        Ok(())
    }
    pub fn remote_scope(&self) -> Result<Scope> {
        use wire::request::Command::*;
        match self.command.as_ref() {
            Some(Describe(_) | Observe(_) | Query(_)) => Ok(Scope::Read),
            Some(Propose(_) | Cancel(_)) => Ok(Scope::Propose),
            _ => bail!("local operator method"),
        }
    }
}
pub fn valid_principal(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
}
