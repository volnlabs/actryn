use crate::state::{hex, unhex, Pair};
use anyhow::{ensure, Context, Result};
use robot_rpc::wire;
use serde::Serialize;
use serde_json::{json, Value};
use std::{path::Path, sync::Arc, time::Duration};
use tokio::io::{AsyncRead, AsyncWrite};
use tokio::net::{TcpStream, UnixStream};
pub const OPERATOR_SOCKET: &str = "/run/actryn-robot/operator.sock";
pub const CLOSURE_SOCKET: &str = "/run/actryn-robot/closure.sock";
const DEADLINE: Duration = Duration::from_secs(10);
#[derive(Debug, Serialize)]
pub struct ExchangeError {
    pub message: String,
    pub outcome_unknown: bool,
}
impl ExchangeError {
    pub fn new(error: impl std::fmt::Display, outcome_unknown: bool) -> Self {
        Self {
            message: error.to_string().chars().take(2048).collect(),
            outcome_unknown,
        }
    }
    pub fn json(&self) -> Value {
        json!({"result":"error","code":if self.outcome_unknown {"outcome_unknown"}else{"transport_unavailable"},"message":self.message,"outcome_unknown":self.outcome_unknown,"automatic_retry":false,"next_action":"inspect_existing_state"})
    }
}
pub fn mutation(request: &wire::Request) -> bool {
    !matches!(
        request.command,
        Some(
            wire::request::Command::Describe(_)
                | wire::request::Command::Observe(_)
                | wire::request::Command::Query(_)
                | wire::request::Command::EvidenceRead(_)
        )
    )
}
pub async fn exchange<S: AsyncRead + AsyncWrite + Unpin>(
    stream: &mut S,
    request: &wire::Request,
) -> std::result::Result<wire::Response, ExchangeError> {
    request
        .validate()
        .map_err(|error| ExchangeError::new(error, false))?;
    let outcome_unknown = mutation(request);
    let result = tokio::time::timeout(DEADLINE, async {
        robot_rpc::write_message(stream, request).await?;
        let response: wire::Response = robot_rpc::read_message(stream).await?;
        ensure!(
            response.version == robot_rpc::VERSION
                && response.request_id == request.request_id
                && response.robot_epoch.len() == 16,
            "RPC response identity mismatch"
        );
        ensure!(
            request.robot_epoch.is_empty()
                || response.robot_epoch == request.robot_epoch
                || matches!(response.result, Some(wire::response::Result::Failure(_))),
            "RPC response epoch mismatch"
        );
        ensure!(response.result.is_some(), "RPC response missing result");
        Ok::<_, anyhow::Error>(response)
    })
    .await;
    match result {
        Ok(Ok(response)) => Ok(response),
        Ok(Err(error)) => Err(ExchangeError::new(error, outcome_unknown)),
        Err(error) => Err(ExchangeError::new(error, outcome_unknown)),
    }
}
pub async fn tls<S: AsyncRead + AsyncWrite + Unpin>(
    stream: S,
    dns: &str,
    pin: &str,
    config: Arc<rustls::ClientConfig>,
) -> Result<tokio_rustls::client::TlsStream<S>> {
    unhex(pin, 32)?;
    let name = rustls::pki_types::ServerName::try_from(dns.to_owned())?;
    ensure!(
        matches!(name, rustls::pki_types::ServerName::DnsName(_)),
        "TLS identity must be DNS"
    );
    let stream = tokio::time::timeout(
        DEADLINE,
        tokio_rustls::TlsConnector::from(config).connect(name, stream),
    )
    .await??;
    let session = stream.get_ref().1;
    ensure!(
        session.protocol_version() == Some(rustls::ProtocolVersion::TLSv1_3)
            && session.alpn_protocol() == Some(robot_rpc::ALPN),
        "unsupported TLS/RPC negotiation"
    );
    let leaf = session
        .peer_certificates()
        .and_then(|chain| chain.first())
        .context("server leaf missing")?;
    ensure!(
        robot_rpc::fingerprint(leaf.as_ref()) == pin,
        "device certificate differs from operator pin"
    );
    Ok(stream)
}
pub async fn remote(
    pair: &Pair,
    certificate: &[u8],
    key: &[u8],
    request: &wire::Request,
) -> std::result::Result<wire::Response, ExchangeError> {
    let connect = async {
        pair.validate()?;
        let config = robot_rpc::client_tls(pair.ca_pem.as_bytes(), certificate, key)?;
        let stream = tokio::time::timeout(DEADLINE, TcpStream::connect(&pair.endpoint)).await??;
        tls(
            stream,
            &pair.dns_name,
            &pair.device_certificate_sha256,
            config,
        )
        .await
    };
    let mut stream = connect
        .await
        .map_err(|error| ExchangeError::new(error, false))?;
    exchange(&mut stream, request).await
}
pub async fn local(request: &wire::Request) -> std::result::Result<wire::Response, ExchangeError> {
    let path = if matches!(
        request.command,
        Some(
            wire::request::Command::Cancel(_)
                | wire::request::Command::Revoke(_)
                | wire::request::Command::Retire(_)
                | wire::request::Command::RevokePrincipal(_)
        )
    ) {
        CLOSURE_SOCKET
    } else {
        OPERATOR_SOCKET
    };
    let connect = async {
        let stream = tokio::time::timeout(DEADLINE, UnixStream::connect(path)).await??;
        ensure!(
            stream.peer_cred()?.uid() == 0,
            "robot daemon peer is not root"
        );
        Ok::<_, anyhow::Error>(stream)
    };
    let mut stream = connect
        .await
        .map_err(|error| ExchangeError::new(error, false))?;
    exchange(&mut stream, request).await
}
pub fn robot_json(response: wire::Response) -> Result<Value> {
    let mut output =
        json!({"request_id":hex(&response.request_id),"robot_epoch":hex(&response.robot_epoch)});
    match response.result.context("missing RPC result")? {
        wire::response::Result::Report(report) => {
            output["result"] = json!("report");
            output["report"] = serde_json::from_slice(&report.json)?;
        }
        wire::response::Result::Observation(o) => {
            output["result"] = json!("observation");
            output["observation"] = json!({"id":o.id,"acquired_earliest_ns":o.acquired_earliest_ns,"acquired_latest_ns":o.acquired_latest_ns,"valid_until_ns":o.valid_until_ns,"controller_ns":o.controller_ns,"left_ticks":o.left_ticks,"right_ticks":o.right_ticks,"simulated":o.simulated,"context_revision":o.context_revision});
        }
        wire::response::Result::Failure(failure) => {
            let code =
                wire::failure::Code::try_from(failure.code).context("unknown failure code")?;
            output["result"] = json!("error");
            output["code"] = json!(code.as_str_name());
            output["message"] = json!(failure.message);
            output["outcome_unknown"] = json!(code == wire::failure::Code::OutcomeUnknown);
            output["automatic_retry"] = json!(false);
        }
    }
    Ok(output)
}
pub fn validate_server_response(
    request: &actryn_server::protocol::Request,
    response: &actryn_server::protocol::Response,
) -> Result<()> {
    use actryn_server::protocol::{Request, Response};
    match (request, response) {
        (_, Response::Error { .. }) => Ok(()),
        (Request::Prepare { artifact_digest }, Response::Ok { inspection }) => {
            ensure!(
                actryn_server::store::valid_id(&inspection.attempt.id)
                    && inspection.attempt.artifact_digest == *artifact_digest,
                "prepared attempt identity mismatch"
            );
            Ok(())
        }
        (
            Request::Start { attempt_id }
            | Request::Stop { attempt_id }
            | Request::Inspect { attempt_id },
            Response::Ok { inspection },
        ) => {
            ensure!(
                inspection.attempt.id == *attempt_id,
                "attempt response identity mismatch"
            );
            Ok(())
        }
        (Request::Result { request_key, .. }, Response::CallResult { call, .. }) => {
            ensure!(
                call.request_key == *request_key,
                "call response identity mismatch"
            );
            Ok(())
        }
        (Request::Export { attempt_id }, Response::Evidence { bundle }) => {
            ensure!(
                bundle.attempt_id == *attempt_id,
                "export response identity mismatch"
            );
            bundle.validate_bound()
        }
        _ => anyhow::bail!("server response does not match operation"),
    }
}
pub async fn server(
    request: &actryn_server::protocol::Request,
) -> std::result::Result<actryn_server::protocol::Response, ExchangeError> {
    use actryn_server::{
        launcher::SERVER_SOCKET,
        protocol::{self, Request},
    };
    let connect = async {
        let bytes = robot_rpc::read_protected(Path::new("/etc/actryn/server.json"), 65536, false)?;
        let config: Value = serde_json::from_slice(&bytes)?;
        let uid = config["server_uid"]
            .as_u64()
            .and_then(|v| u32::try_from(v).ok())
            .filter(|v| *v != 0)
            .context("configured server identity missing")?;
        let stream = tokio::time::timeout(DEADLINE, UnixStream::connect(SERVER_SOCKET)).await??;
        ensure!(
            stream.peer_cred()?.uid() == uid,
            "server daemon peer mismatch"
        );
        Ok::<_, anyhow::Error>(stream)
    };
    let mut stream = connect
        .await
        .map_err(|error| ExchangeError::new(error, false))?;
    let outcome_unknown = matches!(
        request,
        Request::Prepare { .. } | Request::Start { .. } | Request::Stop { .. }
    );
    let result = tokio::time::timeout(DEADLINE, async {
        protocol::write_frame(&mut stream, &serde_json::to_vec(request)?).await?;
        let data = protocol::read_frame(&mut stream).await?;
        let response = serde_json::from_slice(&data)?;
        validate_server_response(request, &response)?;
        Ok::<_, anyhow::Error>(response)
    })
    .await;
    match result {
        Ok(Ok(response)) => Ok(response),
        Ok(Err(error)) => Err(ExchangeError::new(error, outcome_unknown)),
        Err(error) => Err(ExchangeError::new(error, outcome_unknown)),
    }
}
