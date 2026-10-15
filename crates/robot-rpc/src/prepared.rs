//! Encrypt before publication; the only application write is synchronous and consuming.
use crate::{read_message, wire, ALPN, MAX_MESSAGE, VERSION};
use anyhow::{ensure, Context, Result};
use prost::Message;
use rustls::{pki_types::ServerName, ClientConfig};
use sha2::{Digest, Sha256};
use std::{
    io::{self, Cursor, Write},
    net::SocketAddr,
    sync::Arc,
    time::Duration,
};
use tokio::{
    net::TcpStream,
    time::{timeout_at, Instant},
};
use tokio_rustls::{client::TlsStream, TlsConnector};

pub const PREPARED_RPC_TIMEOUT: Duration = Duration::from_secs(5);
pub const MAX_RPC_CIPHERTEXT: usize = MAX_MESSAGE + 8192;

pub struct PreparedRpc {
    sent: SentRpc,
    ciphertext: Vec<u8>,
}
pub struct SentRpc {
    stream: TlsStream<TcpStream>,
    deadline: Instant,
    request_id: Vec<u8>,
    robot_epoch: Vec<u8>,
    describe: bool,
}

impl PreparedRpc {
    /// Authenticates and encrypts locally. No request application bytes are sent.
    /// The caller must put `try_send_once` inside its final publication fence.
    pub async fn connect(
        endpoint: SocketAddr,
        dns: String,
        config: Arc<ClientConfig>,
        leaf_sha256: [u8; 32],
        request: &wire::Request,
    ) -> Result<Self> {
        request.validate()?;
        request.remote_scope()?;
        let bytes = request.encode_to_vec();
        ensure!((1..=MAX_MESSAGE).contains(&bytes.len()), "RPC frame size");
        let deadline = Instant::now() + PREPARED_RPC_TIMEOUT;
        timeout_at(deadline, async {
            let name = ServerName::try_from(dns)?;
            ensure!(
                matches!(name, ServerName::DnsName(_)),
                "TLS DNS identity required"
            );
            let socket = TcpStream::connect(endpoint).await?;
            socket.set_nodelay(true)?;
            let mut stream = TlsConnector::from(config).connect(name, socket).await?;
            let tls = stream.get_ref().1;
            ensure!(
                tls.protocol_version() == Some(rustls::ProtocolVersion::TLSv1_3)
                    && tls.alpn_protocol() == Some(ALPN),
                "unsupported TLS/RPC negotiation"
            );
            let leaf = tls
                .peer_certificates()
                .and_then(|c| c.first())
                .context("server leaf missing")?;
            ensure!(
                Sha256::digest(leaf.as_ref()).as_slice() == leaf_sha256,
                "device certificate differs from operator pin"
            );
            let tls = stream.get_mut().1;
            ensure!(!tls.is_handshaking(), "TLS handshake incomplete");
            tls.set_buffer_limit(Some(MAX_RPC_CIPHERTEXT));
            tls.writer()
                .write_all(&(bytes.len() as u32).to_be_bytes())?;
            tls.writer().write_all(&bytes)?;
            let mut ciphertext = vec![0; MAX_RPC_CIPHERTEXT];
            let mut output = Cursor::new(ciphertext.as_mut_slice());
            while tls.wants_write() {
                ensure!(tls.write_tls(&mut output)? > 0, "TLS ciphertext capacity");
            }
            let size = output.position() as usize;
            ciphertext.truncate(size);
            ensure!(!ciphertext.is_empty(), "empty TLS request");
            stream.get_ref().0.writable().await?;
            Ok(Self {
                sent: SentRpc {
                    stream,
                    deadline,
                    request_id: request.request_id.clone(),
                    robot_epoch: request.robot_epoch.clone(),
                    describe: matches!(request.command, Some(wire::request::Command::Describe(_))),
                },
                ciphertext,
            })
        })
        .await?
    }

    /// Exactly one nonblocking write, with no allocation or async wait. A partial
    /// write or error consumes and closes the transport; delivery remains unknown.
    pub fn try_send_once(self) -> Result<SentRpc> {
        send_packet(&self.ciphertext, self.sent.deadline, |bytes| {
            self.sent.stream.get_ref().0.try_write(bytes)
        })?;
        Ok(self.sent)
    }
}

fn send_packet(
    bytes: &[u8],
    deadline: Instant,
    write: impl FnOnce(&[u8]) -> io::Result<usize>,
) -> Result<()> {
    ensure!(
        Instant::now() < deadline,
        "RPC deadline expired before publication"
    );
    ensure!(
        write(bytes)? == bytes.len(),
        "partial RPC publication; outcome unknown"
    );
    Ok(())
}

impl SentRpc {
    pub async fn read_response(mut self) -> Result<wire::Response> {
        let response: wire::Response =
            timeout_at(self.deadline, read_message(&mut self.stream)).await??;
        ensure!(
            response.version == VERSION
                && response.request_id == self.request_id
                && response.robot_epoch.len() == 16
                && response.result.is_some(),
            "RPC reply identity/result"
        );
        ensure!(
            self.describe || response.robot_epoch == self.robot_epoch,
            "Robot epoch changed; outcome unknown"
        );
        Ok(response)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn partial_zero_error_and_expired_publications_never_retry() {
        let packet = [1; 512];
        for count in 0..=packet.len() {
            let mut calls = 0;
            let result = send_packet(&packet, Instant::now() + PREPARED_RPC_TIMEOUT, |bytes| {
                calls += 1;
                assert_eq!(bytes, packet);
                Ok(count)
            });
            assert_eq!(calls, 1);
            assert_eq!(result.is_ok(), count == packet.len());
        }
        for kind in [
            io::ErrorKind::WouldBlock,
            io::ErrorKind::Interrupted,
            io::ErrorKind::BrokenPipe,
        ] {
            let mut calls = 0;
            assert!(
                send_packet(&packet, Instant::now() + PREPARED_RPC_TIMEOUT, |_| {
                    calls += 1;
                    Err(kind.into())
                })
                .is_err()
            );
            assert_eq!(calls, 1);
        }
        assert!(send_packet(&packet, Instant::now(), |_| panic!(
            "expired request wrote bytes"
        ))
        .is_err());
    }
}
