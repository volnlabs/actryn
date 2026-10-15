//! Local operator facade and per-attempt broker; no engine socket is held here.
use crate::{
    broker::PublicationGate,
    launcher::{self, LauncherConfig},
    model::{self, ModelInput, Proposal},
    protocol::{self, Request, Response},
    Attempt, Limits, Publication, Store,
};
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{
    net::{UnixListener, UnixStream},
    sync::Semaphore,
};

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum BrokerRequest {
    Call {
        request_key: String,
        method: String,
        input: Value,
    },
    Cancel {
        request_key: String,
    },
    Result {
        request_key: String,
    },
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "result", rename_all = "snake_case")]
pub enum BrokerResponse {
    Ok { value: Value },
    Error { reason: String },
}
struct ContextState {
    attempt_id: String,
    gate: PublicationGate,
    keys: Mutex<BTreeMap<String, Arc<PublicationGate>>>,
}
impl ContextState {
    fn key(&self, key: &str) -> Result<Arc<PublicationGate>> {
        ensure!(!key.is_empty() && key.len() <= 128, "invalid request key");
        let mut keys = self
            .keys
            .lock()
            .map_err(|_| anyhow::anyhow!("key registry poisoned"))?;
        if let Some(gate) = keys.get(key) {
            return Ok(gate.clone());
        }
        if keys.len() >= 16 {
            self.gate.close();
            anyhow::bail!("key capacity exhausted; namespace closed");
        }
        let gate = Arc::new(PublicationGate::default());
        keys.insert(key.into(), gate.clone());
        Ok(gate)
    }
}
pub struct Server {
    db: PathBuf,
    contexts: Mutex<BTreeMap<String, Arc<ContextState>>>,
    listeners: Mutex<BTreeMap<String, tokio::task::JoinHandle<()>>>,
}
impl Server {
    pub async fn new(config: &LauncherConfig) -> Result<Arc<Self>> {
        ensure!(
            unsafe { libc::geteuid() } == config.server_uid,
            "server must use configured unprivileged identity"
        );
        let db = Path::new(launcher::STATE_ROOT).join("broker/state.sqlite");
        let server = Arc::new(Self {
            db,
            contexts: Mutex::new(BTreeMap::new()),
            listeners: Mutex::new(BTreeMap::new()),
        });
        let pending = server.database(|s| s.recover()).await?;
        for id in pending {
            let reply = protocol::request(
                Path::new(launcher::LAUNCHER_SOCKET),
                &Request::Stop {
                    attempt_id: id.clone(),
                },
            )
            .await;
            if matches!(reply, Ok(Response::Ok { .. })) {
                server.database(move |s| s.mark_reaped(&id)).await?;
            }
        }
        Ok(server)
    }
    async fn database<T: Send + 'static>(
        &self,
        f: impl FnOnce(&mut Store) -> Result<T> + Send + 'static,
    ) -> Result<T> {
        let path = self.db.clone();
        tokio::task::spawn_blocking(move || f(&mut Store::open(path, Limits::default())?)).await?
    }
    pub async fn tick(&self) -> Result<()> {
        let attempts = self.database(|s| s.attempts()).await?;
        for attempt in attempts {
            if attempt.state == "reaped" {
                continue;
            }
            let result = protocol::request(
                Path::new(launcher::LAUNCHER_SOCKET),
                &if attempt.state == "retiring" {
                    Request::Stop {
                        attempt_id: attempt.id.clone(),
                    }
                } else {
                    Request::Inspect {
                        attempt_id: attempt.id.clone(),
                    }
                },
            )
            .await;
            if let Ok(Response::Ok { inspection }) = result {
                if !inspection.evidence_gaps.is_empty() {
                    let id = attempt.id.clone();
                    let gaps = inspection.evidence_gaps;
                    self.database(move |s| {
                        for gap in gaps {
                            s.record_gap(&id, &gap)?;
                        }
                        Ok(())
                    })
                    .await?;
                }
                if inspection.attempt.state == "retiring" || inspection.attempt.state == "reaped" {
                    if let Some(context) = self
                        .contexts
                        .lock()
                        .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                        .get(&attempt.id)
                    {
                        context.gate.close();
                    }
                    let id = attempt.id.clone();
                    let outcome = inspection.attempt.outcome;
                    self.database(move |s| s.retire(&id, &outcome)).await?;
                    if inspection.attempt.state == "reaped" {
                        let id = attempt.id.clone();
                        self.database(move |s| s.mark_reaped(&id)).await?;
                        if let Some(listener) = self
                            .listeners
                            .lock()
                            .map_err(|_| anyhow::anyhow!("listener lock poisoned"))?
                            .remove(&attempt.id)
                        {
                            listener.abort();
                        }
                        self.contexts
                            .lock()
                            .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                            .remove(&attempt.id);
                    }
                }
            } else {
                if let Some(context) = self
                    .contexts
                    .lock()
                    .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                    .get(&attempt.id)
                {
                    context.gate.close();
                }
                let id = attempt.id;
                self.database(move |s| s.retire(&id, "launcher_unavailable"))
                    .await?;
            }
        }
        Ok(())
    }
    pub async fn handle(self: &Arc<Self>, request: Request) -> Response {
        match self.handle_inner(request).await {
            Ok(response) => response,
            Err(error) => Response::Error {
                message: format!("{error:#}"),
            },
        }
    }
    /// Hold the in-memory cancellation fences at the actual nonblocking publication point.
    pub async fn send_response(
        &self,
        stream: &mut UnixStream,
        request: &Request,
        response: &Response,
    ) -> Result<()> {
        let data = framed(&serde_json::to_vec(response)?)?;
        tokio::time::timeout(Duration::from_secs(1), stream.writable()).await??;
        let send = || -> Result<()> {
            ensure!(
                stream.try_write(&data)? == data.len(),
                "partial operator reply; query existing result"
            );
            Ok(())
        };
        if let (
            Request::Result {
                attempt_id,
                request_key,
            },
            Response::CallResult {
                value: Some(_),
                call,
            },
        ) = (request, response)
        {
            let context = self
                .contexts
                .lock()
                .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                .get(attempt_id)
                .cloned()
                .context("result publication closed")?;
            let gate = context
                .keys
                .lock()
                .map_err(|_| anyhow::anyhow!("key lock poisoned"))?
                .get(request_key)
                .cloned()
                .context("result key closed")?;
            context.gate.publish(|| {
                gate.publish(|| -> Result<()> {
                    ensure!(
                        launcher::now_ms()? < call.deadline_ms,
                        "result publication expired"
                    );
                    send()
                })
            })???;
        } else {
            send()?;
        }
        Ok(())
    }
    async fn handle_inner(self: &Arc<Self>, request: Request) -> Result<Response> {
        if let Request::Export { attempt_id } = &request {
            let id = attempt_id.clone();
            let inspection = self.database(move |s| s.inspect(&id)).await?;
            let response =
                protocol::request(Path::new(launcher::LAUNCHER_SOCKET), &request).await?;
            return match response {
                Response::Evidence { mut bundle } => {
                    ensure!(
                        bundle.attempt_id == *attempt_id,
                        "evidence attempt mismatch"
                    );
                    bundle.add_broker(inspection)?;
                    Ok(Response::Evidence { bundle })
                }
                Response::Error { .. } => Ok(response),
                _ => anyhow::bail!("unexpected launcher evidence response"),
            };
        }
        match &request {
            Request::Stop { attempt_id } => {
                if let Some(context) = self
                    .contexts
                    .lock()
                    .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                    .get(attempt_id)
                {
                    context.gate.close();
                }
                let id = attempt_id.clone();
                self.database(move |s| s.cancel(&id)).await?;
            }
            Request::Start { attempt_id } => {
                let id = attempt_id.clone();
                self.database(move |s| s.start(&id, launcher::now_ms()?))
                    .await?;
            }
            Request::Inspect { attempt_id } => {
                let id = attempt_id.clone();
                return Ok(Response::Ok {
                    inspection: self.database(move |s| s.inspect(&id)).await?,
                });
            }
            Request::Result {
                attempt_id,
                request_key,
            } => {
                let id = attempt_id.clone();
                let key = request_key.clone();
                let (call, bytes) = self
                    .database(move |s| s.result(&id, &key, launcher::now_ms()?))
                    .await?;
                let value = bytes.map(|v| serde_json::from_slice(&v)).transpose()?;
                return Ok(Response::CallResult { call, value });
            }
            _ => {}
        }
        let response = match protocol::request(Path::new(launcher::LAUNCHER_SOCKET), &request).await
        {
            Ok(response) => response,
            Err(error) => {
                if let Request::Start { attempt_id } = &request {
                    self.close_attempt(attempt_id, "unknown").await?;
                }
                return Err(error).context("restricted launcher exchange");
            }
        };
        match &response {
            Response::Ok { inspection } => match request {
                Request::Prepare { .. } => {
                    let attempt = inspection.attempt.clone();
                    self.database(move |s| s.adopt_prepared(&attempt)).await?;
                    if let Err(error) = self.start_broker(&inspection.attempt).await {
                        let _ = protocol::request(
                            Path::new(launcher::LAUNCHER_SOCKET),
                            &Request::Stop {
                                attempt_id: inspection.attempt.id.clone(),
                            },
                        )
                        .await;
                        return Err(error);
                    }
                }
                Request::Stop { attempt_id } => {
                    let id = attempt_id.clone();
                    self.database(move |s| s.mark_reaped(&id)).await?;
                    if let Some(listener) = self
                        .listeners
                        .lock()
                        .map_err(|_| anyhow::anyhow!("listener lock poisoned"))?
                        .remove(&attempt_id)
                    {
                        listener.abort();
                    }
                    self.contexts
                        .lock()
                        .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                        .remove(&attempt_id);
                }
                _ => {}
            },
            Response::Error { .. } => {
                if let Request::Start { attempt_id } = request {
                    self.close_attempt(&attempt_id, "start_rejected").await?;
                }
            }
            Response::CallResult { .. } | Response::Evidence { .. } => {
                anyhow::bail!("unexpected launcher response")
            }
        }
        Ok(response)
    }
    async fn close_attempt(&self, attempt_id: &str, outcome: &str) -> Result<()> {
        if let Some(context) = self
            .contexts
            .lock()
            .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
            .get(attempt_id)
        {
            context.gate.close();
        }
        let id = attempt_id.to_owned();
        let outcome = outcome.to_owned();
        self.database(move |s| s.retire(&id, &outcome)).await
    }
    async fn start_broker(self: &Arc<Self>, attempt: &Attempt) -> Result<()> {
        let path = Path::new(launcher::BROKER_ROOT)
            .join(&attempt.id)
            .join("broker.sock");
        let listener = UnixListener::bind(&path)?;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o666))?;
        let context = Arc::new(ContextState {
            attempt_id: attempt.id.clone(),
            gate: PublicationGate::default(),
            keys: Mutex::new(BTreeMap::new()),
        });
        self.contexts
            .lock()
            .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
            .insert(attempt.id.clone(), context.clone());
        let server = self.clone();
        let slots = Arc::new(Semaphore::new(4));
        let handle = tokio::spawn(async move {
            loop {
                let Ok((mut stream, _)) = listener.accept().await else {
                    break;
                };
                if verify_agent_peer(&stream, &context.attempt_id).is_err() {
                    continue;
                }
                let Ok(permit) = slots.clone().try_acquire_owned() else {
                    continue;
                };
                let context = context.clone();
                let server = server.clone();
                tokio::spawn(async move {
                    let _permit = permit;
                    let result: Result<()> = async {
                        let frame = tokio::time::timeout(
                            Duration::from_secs(1),
                            protocol::read_frame(&mut stream),
                        )
                        .await??;
                        let request: BrokerRequest = serde_json::from_slice(&frame)?;
                        let call_gate = match &request {
                            BrokerRequest::Call { request_key, .. }
                            | BrokerRequest::Result { request_key } => {
                                Some(context.key(request_key)?)
                            }
                            _ => None,
                        };
                        let result = server.broker_request(&context, request).await;
                        let call_gate = if result.is_ok() { call_gate } else { None };
                        let reply = match result {
                            Ok(value) => BrokerResponse::Ok { value },
                            Err(error) => BrokerResponse::Error {
                                reason: format!("{error:#}"),
                            },
                        };
                        let deadline = match &reply {
                            BrokerResponse::Ok { value } => value
                                .get("deadline_ms")
                                .or_else(|| value.get("call").and_then(|v| v.get("deadline_ms")))
                                .and_then(Value::as_i64),
                            _ => None,
                        };
                        let data = framed(&serde_json::to_vec(&reply)?)?;
                        tokio::time::timeout(Duration::from_secs(1), stream.writable()).await??;
                        // Publication linearizes at the bounded nonblocking write, before a closing fence.
                        context.gate.publish(|| -> Result<()> {
                            let send = || -> Result<()> {
                                if let Some(deadline) = deadline {
                                    ensure!(
                                        launcher::now_ms()? < deadline,
                                        "result publication expired"
                                    );
                                }
                                ensure!(
                                    stream.try_write(&data)? == data.len(),
                                    "partial broker reply; query existing request"
                                );
                                Ok(())
                            };
                            match call_gate {
                                Some(gate) => gate.publish(send)?,
                                None => send(),
                            }
                        })??;
                        Ok(())
                    }
                    .await;
                    if let Err(error) = result {
                        eprintln!("broker request {}: {error:#}", context.attempt_id);
                    }
                });
            }
        });
        self.listeners
            .lock()
            .map_err(|_| anyhow::anyhow!("listener lock poisoned"))?
            .insert(attempt.id.clone(), handle);
        Ok(())
    }
    async fn broker_request(
        &self,
        context: &Arc<ContextState>,
        request: BrokerRequest,
    ) -> Result<Value> {
        context.gate.publish(|| ())?;
        match request {
            BrokerRequest::Result { request_key } => {
                let id = context.attempt_id.clone();
                let (call, bytes) = self
                    .database(move |s| s.result(&id, &request_key, launcher::now_ms()?))
                    .await?;
                let value: Option<Value> = bytes.map(|v| serde_json::from_slice(&v)).transpose()?;
                Ok(json!({"call":call,"value":value}))
            }
            BrokerRequest::Cancel { request_key } => {
                context.key(&request_key)?.close();
                let id = context.attempt_id.clone();
                self.database(move |s| s.cancel_call(&id, &request_key))
                    .await?;
                Ok(json!({"stage":"KEY_CANCELLED_DURABLE"}))
            }
            BrokerRequest::Call {
                request_key,
                method,
                input,
            } => {
                let key_gate = context.key(&request_key)?;
                key_gate.publish(|| ())?;
                ensure!(method.len() <= 128, "method name too large");
                if !["diagnostic.echo", "model.offline", "model.propose"].contains(&method.as_str())
                {
                    let id = context.attempt_id.clone();
                    let key = request_key.clone();
                    let denied = method.clone();
                    self.database(move |s| s.record_denial(&id, &key, &denied))
                        .await?;
                    anyhow::bail!("policy_denied: method_not_allowed");
                }
                let model_input = if method.starts_with("model.") {
                    let value: ModelInput = serde_json::from_value(input.clone())?;
                    model::request_body(&value)?;
                    Some(value)
                } else {
                    None
                };
                let credential = if method == "model.propose" {
                    use std::io::Read;
                    let mut credential = String::new();
                    fs::File::open("/run/credentials/actryn-serverd.service/openai-api-key")
                        .context("provider credential unavailable")?
                        .take(4097)
                        .read_to_string(&mut credential)?;
                    ensure!(
                        !credential.trim().is_empty() && credential.len() <= 4096,
                        "invalid provider credential length"
                    );
                    Some(credential)
                } else {
                    None
                };
                let bytes = serde_json::to_vec(&json!({"method":method,"input":input}))?;
                ensure!(bytes.len() <= 65536, "request too large");
                let digest = format!("sha256:{:x}", Sha256::digest(&bytes));
                let id = context.attempt_id.clone();
                let key = request_key.clone();
                let hash = digest.clone();
                let length = bytes.len() as i64;
                let reservation = self
                    .database(move |s| {
                        s.reserve_call(&id, &key, &hash, length, launcher::now_ms()?)
                    })
                    .await?;
                ensure!(
                    reservation.state == "reserved",
                    "request already dispatched; query its existing outcome"
                );
                let call_id = reservation.id.clone();
                self.database(move |s| s.mark_dispatched(&call_id, launcher::now_ms()?))
                    .await?;
                let (output, tokens) = match method.as_str() {
                    "diagnostic.echo" => (input, 0),
                    "model.offline" => (
                        serde_json::to_value(Proposal {
                            left_delta_ticks: 10,
                            right_delta_ticks: 10,
                            duration_ms: 1000,
                        })?,
                        0,
                    ),
                    "model.propose" => {
                        // Credentials are delivered only to this service via systemd LoadCredential.
                        let (proposal, tokens) = model::live(
                            model_input.as_ref().context("missing model input")?,
                            credential
                                .as_deref()
                                .context("missing provider credential")?
                                .trim(),
                        )
                        .await?;
                        (serde_json::to_value(proposal)?, tokens)
                    }
                    _ => unreachable!(),
                };
                let value = json!({"attempt_id":context.attempt_id,"request_key":request_key,"request_digest":digest,
                    "deadline_ms":reservation.deadline_ms,
                    "origin":"server_attested","observation_id":model_input.map(|v|v.observation_id),"model":if method=="model.propose"{model::MODEL}else{"offline-fixture"},"output":output});
                let bytes = serde_json::to_vec(&value)?;
                let call_id = reservation.id;
                let publication = self
                    .database(move |s| s.settle(&call_id, tokens, &bytes, launcher::now_ms()?))
                    .await?;
                context.gate.publish(|| ())?;
                key_gate.publish(|| ())?;
                match publication {
                    Publication::Published(bytes) => Ok(serde_json::from_slice(&bytes)?),
                    _ => anyhow::bail!("publication closed or response too large"),
                }
            }
        }
    }
}
fn framed(data: &[u8]) -> std::io::Result<Vec<u8>> {
    if data.len() > protocol::MAX_MESSAGE {
        return Err(std::io::Error::other("response too large"));
    }
    let mut frame = (data.len() as u32).to_be_bytes().to_vec();
    frame.extend_from_slice(data);
    Ok(frame)
}
fn verify_agent_peer(stream: &UnixStream, attempt: &str) -> Result<()> {
    let peer = stream.peer_cred()?;
    ensure!(peer.uid() == 65532, "broker accepts only sandbox identity");
    let pid = peer.pid().context("peer process missing")?;
    let membership = fs::read_to_string(format!("/proc/{pid}/cgroup"))?;
    ensure!(
        membership
            .lines()
            .any(|line| line == format!("0::/actryn/{attempt}")),
        "peer is not in bound attempt cgroup"
    );
    Ok(())
}
