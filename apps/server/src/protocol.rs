use crate::{
    store::{valid_digest, valid_id},
    Inspection, Reservation,
};
use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::UnixStream,
};
pub const MAX_MESSAGE: usize = 65536;
pub const CLOSURE_SOCKET: &str = "/run/actryn-server/closure.sock";
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Request {
    Prepare {
        artifact_digest: String,
    },
    Start {
        attempt_id: String,
    },
    Stop {
        attempt_id: String,
    },
    Inspect {
        attempt_id: String,
    },
    Result {
        attempt_id: String,
        request_key: String,
    },
    Export {
        attempt_id: String,
    },
    BindRobot {
        attempt_id: String,
        namespace: String,
    },
    RobotQuery {
        attempt_id: String,
        request_key: String,
    },
    RobotCancel {
        attempt_id: String,
        request_key: String,
    },
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "result", rename_all = "snake_case")]
pub enum Response {
    Ok {
        inspection: Inspection,
    },
    CallResult {
        call: Reservation,
        value: Option<serde_json::Value>,
    },
    Evidence {
        bundle: crate::evidence::Bundle,
    },
    RobotBinding {
        binding: crate::robot::Binding,
    },
    RobotResult {
        request: crate::robot::Intent,
    },
    Error {
        message: String,
    },
}
pub fn decode_request(bytes: &[u8]) -> Result<Request> {
    ensure!(bytes.len() <= MAX_MESSAGE, "request too large");
    let r: Request = serde_json::from_slice(bytes)?;
    match &r {
        Request::Prepare { artifact_digest } => {
            ensure!(valid_digest(artifact_digest), "invalid artifact digest")
        }
        Request::Start { attempt_id }
        | Request::Stop { attempt_id }
        | Request::Inspect { attempt_id }
        | Request::Export { attempt_id } => ensure!(valid_id(attempt_id), "invalid attempt id"),
        Request::Result {
            attempt_id,
            request_key,
        }
        | Request::RobotQuery {
            attempt_id,
            request_key,
        }
        | Request::RobotCancel {
            attempt_id,
            request_key,
        } => {
            ensure!(valid_id(attempt_id), "invalid attempt id");
            ensure!(
                !request_key.is_empty() && request_key.len() <= 128,
                "invalid request key"
            );
        }
        Request::BindRobot {
            attempt_id,
            namespace,
        } => {
            ensure!(
                valid_id(attempt_id) && valid_id(namespace),
                "invalid delegation identity"
            );
        }
    };
    Ok(r)
}
pub async fn read_frame(stream: &mut UnixStream) -> Result<Vec<u8>> {
    let len = stream.read_u32().await? as usize;
    ensure!(len <= MAX_MESSAGE, "frame too large");
    let mut data = vec![0; len];
    stream.read_exact(&mut data).await?;
    Ok(data)
}
pub async fn write_frame(stream: &mut UnixStream, data: &[u8]) -> Result<()> {
    ensure!(data.len() <= MAX_MESSAGE, "response too large");
    stream.write_u32(data.len() as u32).await?;
    stream.write_all(data).await?;
    Ok(())
}
pub async fn request(path: &std::path::Path, request: &Request) -> Result<Response> {
    request_as(path, 0, request).await
}
/// Operator clients must use the installed service UID; helper clients require UID zero.
pub async fn request_as(
    path: &std::path::Path,
    expected_uid: u32,
    request: &Request,
) -> Result<Response> {
    let mut socket = UnixStream::connect(path).await?;
    ensure!(
        socket.peer_cred()?.uid() == expected_uid,
        "unexpected server peer identity"
    );
    write_frame(&mut socket, &serde_json::to_vec(request)?).await?;
    let data =
        tokio::time::timeout(std::time::Duration::from_secs(10), read_frame(&mut socket)).await??;
    Ok(serde_json::from_slice(&data)?)
}
