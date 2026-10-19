//! Local operator facade and per-attempt broker; no engine socket is held here.
use crate::{
    broker::PublicationGate,
    launcher::{self, LauncherConfig},
    model::{self, ModelInput, Proposal},
    protocol::{self, Request, Response},
    robot::{self, Binding as RobotBinding, Intent as RobotIntent, Peer as RobotPeer, RemoteReply},
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
    methods: &'static [&'static str],
    gate: PublicationGate,
    keys: Mutex<BTreeMap<String, Arc<PublicationGate>>>,
    robot_binding: Mutex<Option<RobotBinding>>,
    preparation: tokio::sync::Mutex<()>,
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
    listeners: Mutex<BTreeMap<String, Vec<tokio::task::JoinHandle<()>>>>,
    robot_closures: Arc<robot::Closures>,
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
            robot_closures: Arc::new(robot::Closures::default()),
        });
        let pending = server.database(|s| s.recover()).await?;
        let remote = server.database(|s| s.robot_pending()).await?;
        for (binding, intent) in remote {
            let captured = server.robot_closures.capture(&binding, &intent)?;
            server.queue_robot_closure(captured);
        }
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
    pub async fn finish_recovery_closures(&self) {
        let deadline = tokio::time::Instant::now() + Duration::from_secs(9);
        while self.robot_closures.any_running() && tokio::time::Instant::now() < deadline {
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        if self.robot_closures.any_running() {
            eprintln!("Robot closure still unresolved; durable debit remains held");
        }
    }
    fn close_robot_memory(&self, attempt: &str, key: Option<&str>) {
        for captured in self.robot_closures.for_attempt(attempt, key) {
            self.queue_robot_closure(captured);
        }
    }
    fn publication_key(&self, context: &ContextState, key: &str) -> Result<Arc<PublicationGate>> {
        let result = context.key(key);
        if result.is_err() && context.gate.publish(|| ()).is_err() {
            // Exhausting key retention closes the whole namespace. Queue all
            // captured handles before returning, without touching SQLite.
            self.close_robot_memory(&context.attempt_id, None);
        }
        result
    }
    fn queue_robot_closure(&self, captured: Arc<robot::Captured>) {
        let peer_capture = captured.clone();
        self.queue_robot_closure_with(captured, async move {
            RobotPeer::load()?
                .retained(&peer_capture.binding, &peer_capture.intent, true)
                .await
        });
    }
    fn queue_robot_closure_with(
        &self,
        captured: Arc<robot::Captured>,
        network: impl std::future::Future<Output = Result<RemoteReply>> + Send + 'static,
    ) {
        if !captured.begin() {
            return;
        }
        let path = self.db.clone();
        let inventory = self.robot_closures.clone();
        tokio::spawn(async move {
            // Network closure runs before acquiring any SQLite connection or lock.
            let response = network.await;
            let id = captured.intent.handle.attempt.clone();
            let key = captured.intent.request_key.clone();
            let write_id = id.clone();
            let write_key = key.clone();
            let result = tokio::task::spawn_blocking(move || -> Result<RobotIntent> {
                let mut store = Store::open(path, Limits::default())?;
                store.robot_cancel_key(&write_id, &write_key)?;
                apply_robot_reply(&mut store, &write_id, &write_key, response)
            })
            .await;
            match result {
                Ok(Ok(intent)) if !intent.outstanding_debit => inventory.settled(&id,&key),
                Ok(Ok(_)) => (),
                _ => eprintln!("Robot closure persistence unavailable; retained handle {id}/{key} remains unresolved"),
            }
            inventory.finished(&captured);
        });
    }
    async fn record_robot_reply(
        &self,
        intent: &RobotIntent,
        response: Result<RemoteReply>,
    ) -> Result<RobotIntent> {
        let id = intent.handle.attempt.clone();
        let key = intent.request_key.clone();
        let saved = self
            .database(move |s| apply_robot_reply(s, &id, &key, response))
            .await?;
        if !saved.outstanding_debit {
            self.robot_closures
                .settled(&saved.handle.attempt, &saved.request_key);
        }
        Ok(saved)
    }
    async fn begin_robot(
        &self,
        context: &Arc<ContextState>,
        key: &str,
        digest: &str,
    ) -> Result<Option<(RobotPeer, RobotBinding, RobotIntent)>> {
        let binding = context
            .robot_binding
            .lock()
            .map_err(|_| anyhow::anyhow!("binding lock poisoned"))?
            .clone();
        let Some(binding) = binding else {
            return Ok(None);
        };
        let peer = RobotPeer::load()?;
        peer.verify_binding(&binding)?;
        let id = context.attempt_id.clone();
        let saved_key = key.to_owned();
        let hash = digest.to_owned();
        let intent = self
            .database(move |s| s.robot_reserve(&id, &saved_key, &hash, launcher::now_ms()?))
            .await?;
        let captured = self.robot_closures.capture(&binding, &intent)?;
        let key_gate = self.publication_key(context, key)?;
        let observation = async {
            open_gates(context, &key_gate)?;
            let observation = peer.observe(&binding).await?;
            let id = context.attempt_id.clone();
            let key = key.to_owned();
            let intent = self
                .database(move |s| s.robot_observe(&id, &key, &observation, launcher::now_ms()?))
                .await?;
            open_gates(context, &key_gate)?;
            Ok::<_, anyhow::Error>(intent)
        }
        .await;
        match observation {
            Ok(intent) => Ok(Some((peer, binding, intent))),
            Err(error) => {
                key_gate.close();
                self.queue_robot_closure(captured);
                Err(error)
            }
        }
    }
    async fn dispatch_robot(
        &self,
        context: &Arc<ContextState>,
        key_gate: &PublicationGate,
        peer: &RobotPeer,
        binding: &RobotBinding,
        intent: &RobotIntent,
        target: &Proposal,
    ) -> Result<()> {
        use prost::Message;
        let request = peer.proposal(binding, intent, target)?;
        let digest = format!("sha256:{:x}", Sha256::digest(request.encode_to_vec()));
        let id = context.attempt_id.clone();
        let key = intent.request_key.clone();
        let saved = self
            .database(move |s| s.robot_dispatch(&id, &key, &digest, launcher::now_ms()?))
            .await?;
        // Every committed pre-send intent checks the same terminal fences again.
        open_gates(context, key_gate)?;
        let prepared = peer.prepare(&request).await?;
        let received = intent
            .execution_observation
            .as_ref()
            .or(intent.observation.as_ref())
            .context("execution observation missing")?
            .received_ms;
        let sent = context.gate.publish(|| {
            key_gate.publish(|| -> Result<robot_rpc::SentRpc> {
                let now = launcher::now_ms()?;
                ensure!(
                    now < saved.deadline_ms && now >= received && now - received < 1000,
                    "Robot execution observation/delegation expired"
                );
                prepared.try_send_once()
            })
        })???;
        let response = sent.read_response().await.and_then(RobotPeer::remote_reply);
        // Only a matching snapshot can acknowledge this proposal. Historical
        // inspection and an absent key are useful for Query/Cancel, not dispatch.
        let known = matches!(&response, Ok(RemoteReply::Snapshot(_)));
        self.record_robot_reply(&saved, response).await?;
        ensure!(
            known,
            "Robot proposal response unknown; query retained handle, never resend"
        );
        Ok(())
    }
    async fn revalidate_robot(
        &self,
        context: &Arc<ContextState>,
        key_gate: &PublicationGate,
        peer: &RobotPeer,
        binding: &RobotBinding,
        intent: &RobotIntent,
    ) -> Result<RobotIntent> {
        open_gates(context, key_gate)?;
        let observation = peer.observe(binding).await?;
        let id = context.attempt_id.clone();
        let key = intent.request_key.clone();
        let saved = self
            .database(move |s| {
                s.robot_execution_observe(&id, &key, &observation, launcher::now_ms()?)
            })
            .await?;
        open_gates(context, key_gate)?;
        Ok(saved)
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
                        if context.gate.close() {
                            self.close_robot_memory(&attempt.id, None);
                        }
                    }
                    let id = attempt.id.clone();
                    let outcome = inspection.attempt.outcome;
                    self.database(move |s| s.retire(&id, &outcome)).await?;
                    if inspection.attempt.state == "reaped" {
                        let id = attempt.id.clone();
                        self.database(move |s| s.mark_reaped(&id)).await?;
                        if let Some(listeners) = self
                            .listeners
                            .lock()
                            .map_err(|_| anyhow::anyhow!("listener lock poisoned"))?
                            .remove(&attempt.id)
                        {
                            for listener in listeners {
                                listener.abort();
                            }
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
                    if context.gate.close() {
                        self.close_robot_memory(&attempt.id, None);
                    }
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
            Request::BindRobot {
                attempt_id,
                namespace,
            } => {
                let context = self
                    .contexts
                    .lock()
                    .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                    .get(attempt_id)
                    .cloned()
                    .context("attempt not prepared in this daemon")?;
                let _transition = context
                    .preparation
                    .try_lock()
                    .context("preparation transition active")?;
                context.gate.publish(|| ())?;
                let id = attempt_id.clone();
                let inspection = self.database(move |s| s.inspect(&id)).await?;
                ensure!(
                    inspection.attempt.state == "prepared",
                    "Robot binding requires prepared attempt"
                );
                let peer = RobotPeer::load()?;
                let binding = peer
                    .bind(attempt_id, namespace, inspection.attempt.deadline_ms)
                    .await?;
                let saved = binding.clone();
                self.database(move |s| s.robot_bind(&saved, launcher::now_ms()?))
                    .await?;
                context.gate.publish(|| -> Result<()> {
                    *context
                        .robot_binding
                        .lock()
                        .map_err(|_| anyhow::anyhow!("binding lock poisoned"))? =
                        Some(binding.clone());
                    Ok(())
                })??;
                return Ok(Response::RobotBinding { binding });
            }
            Request::RobotCancel {
                attempt_id,
                request_key,
            } => {
                if let Some(context) = self
                    .contexts
                    .lock()
                    .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                    .get(attempt_id)
                {
                    self.publication_key(context, request_key)?.close();
                }
                self.close_robot_memory(attempt_id, Some(request_key));
                let id = attempt_id.clone();
                let key = request_key.clone();
                let intent = self
                    .database(move |s| {
                        s.cancel_call(&id, &key)?;
                        s.robot_cancel_key(&id, &key)?
                            .context("key cancelled locally; no remote handle exists")
                    })
                    .await?;
                return Ok(Response::RobotResult { request: intent });
            }
            Request::RobotQuery {
                attempt_id,
                request_key,
            } => {
                let id = attempt_id.clone();
                let key = request_key.clone();
                let (binding, intent) = self
                    .database(move |s| {
                        Ok((
                            s.robot_binding(&id)?.context("Robot binding missing")?,
                            s.robot_intent(&id, &key)?,
                        ))
                    })
                    .await?;
                let result = RobotPeer::load()?.retained(&binding, &intent, false).await;
                let intent = self.record_robot_reply(&intent, result).await?;
                return Ok(Response::RobotResult { request: intent });
            }
            Request::Stop { attempt_id } => {
                if let Some(context) = self
                    .contexts
                    .lock()
                    .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                    .get(attempt_id)
                {
                    context.gate.close();
                }
                self.close_robot_memory(attempt_id, None);
                let id = attempt_id.clone();
                self.database(move |s| s.cancel(&id)).await?;
            }
            Request::Start { attempt_id } => {
                let context = self
                    .contexts
                    .lock()
                    .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
                    .get(attempt_id)
                    .cloned()
                    .context("attempt not prepared in this daemon")?;
                let _transition = context
                    .preparation
                    .try_lock()
                    .context("preparation transition active")?;
                context.gate.publish(|| ())?;
                let id = attempt_id.clone();
                if let Some(binding) = self.database(move |s| s.robot_binding(&id)).await? {
                    ensure!(
                        launcher::now_ms()? < binding.deadline_ms,
                        "Robot binding expired"
                    );
                    RobotPeer::load()?.verify_binding(&binding)?;
                }
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
                    if let Some(listeners) = self
                        .listeners
                        .lock()
                        .map_err(|_| anyhow::anyhow!("listener lock poisoned"))?
                        .remove(&attempt_id)
                    {
                        for listener in listeners {
                            listener.abort();
                        }
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
            Response::CallResult { .. }
            | Response::Evidence { .. }
            | Response::RobotBinding { .. }
            | Response::RobotResult { .. } => {
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
        self.close_robot_memory(attempt_id, None);
        let id = attempt_id.to_owned();
        let outcome = outcome.to_owned();
        self.database(move |s| s.retire(&id, &outcome)).await
    }
    async fn start_broker(self: &Arc<Self>, attempt: &Attempt) -> Result<()> {
        let directory = Path::new(launcher::BROKER_ROOT).join(&attempt.id);
        let mut listeners = vec![];
        for (name, closure_only) in [("broker.sock", false), ("closure.sock", true)] {
            let path = directory.join(name);
            let listener = UnixListener::bind(&path)?;
            fs::set_permissions(&path, fs::Permissions::from_mode(0o666))?;
            listeners.push((listener, closure_only));
        }
        let context = Arc::new(ContextState {
            attempt_id: attempt.id.clone(),
            methods: crate::artifact::broker_methods(&attempt.artifact_digest)?,
            gate: PublicationGate::default(),
            keys: Mutex::new(BTreeMap::new()),
            robot_binding: Mutex::new(None),
            preparation: tokio::sync::Mutex::new(()),
        });
        self.contexts
            .lock()
            .map_err(|_| anyhow::anyhow!("context lock poisoned"))?
            .insert(attempt.id.clone(), context.clone());
        let mut handles = vec![];
        for (listener, closure_only) in listeners {
            let server = self.clone();
            let context = context.clone();
            let slots = Arc::new(Semaphore::new(if closure_only { 2 } else { 4 }));
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
                            ensure!(
                                !closure_only || matches!(request, BrokerRequest::Cancel { .. }),
                                "reserved cancellation endpoint"
                            );
                            let call_gate = match &request {
                                BrokerRequest::Call { request_key, .. }
                                | BrokerRequest::Result { request_key } => {
                                    Some(server.publication_key(&context, request_key)?)
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
                                    .or_else(|| {
                                        value.get("call").and_then(|v| v.get("deadline_ms"))
                                    })
                                    .and_then(Value::as_i64),
                                _ => None,
                            };
                            let data = framed(&serde_json::to_vec(&reply)?)?;
                            tokio::time::timeout(Duration::from_secs(1), stream.writable())
                                .await??;
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
                        if context.gate.publish(|| ()).is_err() {
                            server.close_robot_memory(&context.attempt_id, None);
                        }
                        if let Err(error) = result {
                            eprintln!("broker request {}: {error:#}", context.attempt_id);
                        }
                    });
                }
            });
            handles.push(handle);
        }
        self.listeners
            .lock()
            .map_err(|_| anyhow::anyhow!("listener lock poisoned"))?
            .insert(attempt.id.clone(), handles);
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
                self.publication_key(context, &request_key)?.close();
                self.close_robot_memory(&context.attempt_id, Some(&request_key));
                let id = context.attempt_id.clone();
                self.database(move |s| {
                    s.cancel_call(&id, &request_key)?;
                    s.robot_cancel_key(&id, &request_key)?;
                    Ok(())
                })
                .await?;
                Ok(json!({"stage":"KEY_CANCELLED_DURABLE"}))
            }
            BrokerRequest::Call {
                request_key,
                method,
                input,
            } => {
                let key_gate = self.publication_key(context, &request_key)?;
                key_gate.publish(|| ())?;
                ensure!(method.len() <= 128, "method name too large");
                if !context.methods.contains(&method.as_str()) {
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
                let result=async {
                let credential = if method == "model.propose" {
                    let credential=String::from_utf8(robot::read_credential(Path::new("/run/credentials/actryn-serverd.service/openai-api-key"),4096).context("provider credential unavailable")?)?;
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
                let mut remote=if model_input.is_some() {self.begin_robot(context,&request_key,&digest).await?}else{None};
                open_gates(context,&key_gate)?;
                let call_id = reservation.id.clone();
                self.database(move |s| s.mark_dispatched(&call_id, launcher::now_ms()?))
                    .await?;
                open_gates(context,&key_gate)?;
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
                        let (proposal, tokens) = model::live_with_observation(
                            model_input.as_ref().context("missing model input")?,
                            credential
                                .as_deref()
                                .context("missing provider credential")?
                                .trim(),
                            remote.as_ref().and_then(|(_,_,intent)|intent.observation.as_ref()),
                        )
                        .await?;
                        (serde_json::to_value(proposal)?, tokens)
                    }
                    _ => unreachable!(),
                };
                let value = json!({"attempt_id":context.attempt_id,"request_key":request_key,"request_digest":digest,
                    "deadline_ms":reservation.deadline_ms,
                    "origin":"server_attested","agent_observation_reference":model_input.as_ref().map(|v|&v.observation_id),
                    "trusted_robot_observation":remote.as_ref().and_then(|(_,_,intent)|intent.observation.as_ref()),
                    "robot_handle":remote.as_ref().map(|(_,_,intent)|&intent.handle),
                    "observation_digest":remote.as_ref().and_then(|(_,_,intent)|intent.observation_digest.as_ref()),
                    "lineage_digest":remote.as_ref().and_then(|(_,_,intent)|intent.parent_digest.as_ref()),
                    "model":if method=="model.propose"{model::MODEL}else{"offline-fixture"},"output":output});
                let bytes = serde_json::to_vec(&value)?;
                let call_id = reservation.id;
                let publication = self
                    .database(move |s| s.settle(&call_id, tokens, &bytes, launcher::now_ms()?))
                    .await?;
                context.gate.publish(|| ())?;
                key_gate.publish(|| ())?;
                let published=match publication {
                    Publication::Published(bytes) => serde_json::from_slice(&bytes)?,
                    _ => anyhow::bail!("publication closed or response too large"),
                };
                if method == "model.propose" {
                    if let Some((peer,binding,intent)) = &mut remote {
                        *intent = self.revalidate_robot(context,&key_gate,peer,binding,intent).await?;
                    }
                }
                if let Some((peer,binding,intent))=&remote {
                    let target:Proposal=serde_json::from_value(value["output"].clone())?;
                    self.dispatch_robot(context,&key_gate,peer,binding,intent,&target).await?;
                }
                open_gates(context,&key_gate)?;
                Ok(published)
                }.await;
                if result.is_err() {
                    key_gate.close();
                    self.close_robot_memory(&context.attempt_id, Some(&request_key));
                    let id = context.attempt_id.clone();
                    let key = request_key.clone();
                    // Dispatched provider work remains charged; only undelivered reservations release.
                    self.database(move |s| {
                        s.cancel_call(&id, &key)?;
                        s.robot_cancel_key(&id, &key)?;
                        Ok(())
                    })
                    .await?;
                }
                result
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
fn open_gates(context: &ContextState, key: &PublicationGate) -> Result<()> {
    context.gate.publish(|| key.publish(|| ()))??;
    Ok(())
}
fn apply_robot_reply(
    store: &mut Store,
    id: &str,
    key: &str,
    response: Result<RemoteReply>,
) -> Result<RobotIntent> {
    match response {
        Ok(RemoteReply::Snapshot(snapshot)) => store.robot_snapshot(id, key, &snapshot),
        Ok(RemoteReply::Historical(snapshot)) => {
            if let Some(snapshot) = snapshot {
                store.robot_snapshot(id, key, &snapshot)?;
            }
            store.robot_unknown(id, key, true)
        }
        Ok(RemoteReply::Absent) | Err(_) => store.robot_unknown(id, key, false),
    }
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

#[cfg(test)]
mod tests {
    fn closure_fixture() -> (
        tempfile::TempDir,
        Store,
        Arc<Server>,
        Arc<ContextState>,
        RobotBinding,
        RobotIntent,
    ) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("db");
        let mut store = Store::open(&path, Limits::default()).unwrap();
        let a = store
            .prepare(&format!("sha256:{}", "a".repeat(64)), 100)
            .unwrap();
        store.mark_prepared(&a.id, "runtime").unwrap();
        let binding = RobotBinding {
            attempt_id: a.id.clone(),
            namespace: a.id.clone(),
            principal: "server".into(),
            peer_digest: format!("sha256:{}", "c".repeat(64)),
            client_certificate_sha256: "d".repeat(64),
            robot_epoch: "e".repeat(32),
            robot_configuration_digest: "f".repeat(64),
            robot_profile_digest: "a".repeat(64),
            created_ms: 100,
            deadline_ms: 60_000,
        };
        store.robot_bind(&binding, 100).unwrap();
        store.start(&a.id, 100).unwrap();
        let intent = store.robot_reserve(&a.id, "key", "digest", 101).unwrap();
        let context = Arc::new(ContextState {
            attempt_id: a.id.clone(),
            methods: &["model.offline"],
            gate: PublicationGate::default(),
            keys: Mutex::new(BTreeMap::new()),
            robot_binding: Mutex::new(Some(binding.clone())),
            preparation: tokio::sync::Mutex::new(()),
        });
        let server = Arc::new(Server {
            db: path,
            contexts: Mutex::new(BTreeMap::from([(a.id, context.clone())])),
            listeners: Mutex::new(BTreeMap::new()),
            robot_closures: Arc::new(robot::Closures::default()),
        });
        (dir, store, server, context, binding, intent)
    }
    #[tokio::test]
    async fn query_settlement_retains_capacity_until_pending_network_worker_exits() {
        let (_dir, _store, server, _context, binding, intent) = closure_fixture();
        let captured = server.robot_closures.capture(&binding, &intent).unwrap();
        let (release, held) = tokio::sync::oneshot::channel::<()>();
        server.queue_robot_closure_with(captured, async move {
            held.await?;
            Ok(RemoteReply::Absent)
        });
        for n in 1..robot::CLOSURE_CAPACITY {
            let mut next = intent.clone();
            next.request_key = format!("fill-{n}");
            next.handle.key = format!("{n:064x}");
            assert!(server
                .robot_closures
                .capture(&binding, &next)
                .unwrap()
                .begin());
        }
        let snapshot = robot::RemoteSnapshot {
            namespace: robot::unhex(&intent.handle.namespace).unwrap(),
            key: robot::unhex(&intent.handle.key).unwrap(),
            digest: None,
            operation: None,
            revision: 1,
            durable_revision: 1,
            phase: "CancelledDurable".into(),
            terminal: true,
            closure: "NotAllocated".into(),
            cancellation_durable: true,
            persistence_failed: false,
            verdict: robot::Verdict::Pending,
            reconciled: false,
        };
        assert!(
            !server
                .record_robot_reply(&intent, Ok(RemoteReply::Snapshot(snapshot)))
                .await
                .unwrap()
                .outstanding_debit
        );
        let mut extra = intent.clone();
        extra.request_key = "overflow".into();
        extra.handle.key = "f".repeat(64);
        assert!(server.robot_closures.capture(&binding, &extra).is_err());
        release.send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(2), async {
            while server
                .robot_closures
                .for_attempt(&binding.attempt_id, None)
                .len()
                == robot::CLOSURE_CAPACITY
            {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert!(server.robot_closures.capture(&binding, &extra).is_ok());
    }
    #[tokio::test]
    async fn historical_completed_unknown_task_settles_only_its_debit_before_worker_exit() {
        let (_dir, mut store, server, context, binding, intent) = closure_fixture();
        let id = &intent.handle.attempt;
        let call = store.reserve_call(id, "key", "digest", 1, 101).unwrap();
        store.mark_dispatched(&call.id, 102).unwrap();
        let completed = robot::RemoteSnapshot {
            namespace: robot::unhex(&intent.handle.namespace).unwrap(),
            key: robot::unhex(&intent.handle.key).unwrap(),
            digest: Some([3; 32]),
            operation: Some(robot::Operation {
                device: [1; 16],
                boot: 1,
                session: 2,
                runtime_nonce: [2; 16],
                grant: 3,
                instance: 4,
                operation: 5,
                stream: 6,
            }),
            revision: 3,
            durable_revision: 3,
            phase: "Completed".into(),
            terminal: true,
            closure: "NotRequested".into(),
            cancellation_durable: false,
            persistence_failed: false,
            verdict: robot::Verdict::OutcomeUnknown,
            reconciled: true,
        };
        let mut pending = completed.clone();
        pending.reconciled = false;
        store.robot_snapshot(id, "key", &pending).unwrap();
        context.gate.close();
        store.recover().unwrap();
        store.mark_reaped(id).unwrap();
        let captured = server.robot_closures.capture(&binding, &intent).unwrap();
        let (release, held) = tokio::sync::oneshot::channel::<()>();
        let worker_reply = completed.clone();
        server.queue_robot_closure_with(captured.clone(), async move {
            held.await?;
            Ok(RemoteReply::Historical(Some(worker_reply)))
        });
        let saved = server
            .record_robot_reply(&intent, Ok(RemoteReply::Historical(Some(completed))))
            .await
            .unwrap();
        assert!(!saved.outstanding_debit);
        assert_eq!(saved.phase, robot::Phase::Settled);
        assert!(
            saved.cancellation_requested && saved.historical_response && saved.remote_unavailable
        );
        assert_eq!(
            saved.summary().remote_verdict,
            Some(robot::Verdict::OutcomeUnknown)
        );
        assert!(saved.last_remote.unwrap().reconciled);
        assert!(store.robot_pending().unwrap().is_empty());
        // A read-only query settled the debit, but the held network worker still owns its slot.
        assert!(server.robot_closures.any_running());
        assert_eq!(server.robot_closures.for_attempt(id, Some("key")).len(), 1);
        assert!(!captured.begin());
        let before_exit = store.inspect(id).unwrap();
        assert_eq!(before_exit.attempt.outcome, "unknown");
        assert_eq!(before_exit.calls[0].state, "unknown");
        assert!(before_exit.calls[0].publication_closed);
        assert_eq!(store.result(id, "key", 104).unwrap().1, None);
        assert!(context.gate.publish(|| ()).is_err());
        release.send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(2), async {
            while !server
                .robot_closures
                .for_attempt(id, Some("key"))
                .is_empty()
            {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert!(!server.robot_closures.any_running());
        assert!(!captured.begin());
        let retained = store.robot_intent(id, "key").unwrap();
        assert!(!retained.outstanding_debit && retained.historical_response);
        assert_eq!(
            retained.summary().remote_verdict,
            Some(robot::Verdict::OutcomeUnknown)
        );
        assert_eq!(
            store.settle(&call.id, 0, b"late reply", 105).unwrap(),
            Publication::Suppressed
        );
        assert_eq!(store.result(id, "key", 105).unwrap().1, None);
        assert_eq!(store.inspect(id).unwrap().attempt.outcome, "unknown");
        assert!(context.gate.publish(|| ()).is_err());
    }

    #[tokio::test]
    async fn reserved_cancel_key_exhaustion_queues_all_captured_closures_before_error() {
        let (_dir, _store, server, context, binding, intent) = closure_fixture();
        for n in 0..16 {
            context.key(&format!("key-{n}")).unwrap();
        }
        let captured = server.robot_closures.capture(&binding, &intent).unwrap();
        let result = server
            .handle_inner(Request::RobotCancel {
                attempt_id: binding.attempt_id,
                request_key: "seventeenth".into(),
            })
            .await;
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("key capacity exhausted"));
        assert!(context.gate.publish(|| ()).is_err());
        // No await follows: the production network future is queued but never polled in this test.
        assert!(
            !captured.begin(),
            "capacity closure did not queue the existing remote handle"
        );
    }
    #[tokio::test]
    async fn concurrent_preparation_transitions_reject_without_blocking_closure() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("db");
        let mut store = Store::open(&path, Limits::default()).unwrap();
        let attempt = store
            .prepare(
                &format!("sha256:{}", "a".repeat(64)),
                launcher::now_ms().unwrap(),
            )
            .unwrap();
        store.mark_prepared(&attempt.id, "test-runtime").unwrap();
        let context = Arc::new(ContextState {
            attempt_id: attempt.id.clone(),
            methods: &["model.offline"],
            gate: PublicationGate::default(),
            keys: Mutex::new(BTreeMap::new()),
            robot_binding: Mutex::new(None),
            preparation: tokio::sync::Mutex::new(()),
        });
        let server = Arc::new(Server {
            db: path,
            contexts: Mutex::new(BTreeMap::from([(attempt.id.clone(), context.clone())])),
            listeners: Mutex::new(BTreeMap::new()),
            robot_closures: Arc::new(robot::Closures::default()),
        });
        let transition = context.preparation.lock().await;
        for request in [
            Request::Start {
                attempt_id: attempt.id.clone(),
            },
            Request::BindRobot {
                attempt_id: attempt.id.clone(),
                namespace: "b".repeat(32),
            },
        ] {
            let error = server.handle_inner(request).await.unwrap_err();
            assert!(
                error.to_string().contains("preparation transition active"),
                "{error:#}"
            );
        }
        assert_eq!(
            store.inspect(&attempt.id).unwrap().attempt.state,
            "prepared"
        );
        let result = server
            .handle_inner(Request::RobotCancel {
                attempt_id: attempt.id.clone(),
                request_key: "early".into(),
            })
            .await;
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("no remote handle exists"));
        assert!(context.key("early").unwrap().publish(|| ()).is_err());
        drop(transition);
    }
    use super::*;
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn reserved_network_closure_does_not_wait_for_sqlite_writer() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("state.db");
        let mut store = Store::open(&path, Limits::default()).unwrap();
        let a = store
            .prepare(&format!("sha256:{}", "a".repeat(64)), 100)
            .unwrap();
        store.mark_prepared(&a.id, "launcher").unwrap();
        let binding = RobotBinding {
            attempt_id: a.id.clone(),
            namespace: "b".repeat(32),
            principal: "server".into(),
            peer_digest: format!("sha256:{}", "c".repeat(64)),
            client_certificate_sha256: "d".repeat(64),
            robot_epoch: "e".repeat(32),
            robot_configuration_digest: "f".repeat(64),
            robot_profile_digest: "a".repeat(64),
            created_ms: 100,
            deadline_ms: 60_000,
        };
        store.robot_bind(&binding, 100).unwrap();
        store.start(&a.id, 100).unwrap();
        let intent = store.robot_reserve(&a.id, "key", "input", 101).unwrap();
        let server = Server {
            db: path.clone(),
            contexts: Mutex::new(BTreeMap::new()),
            listeners: Mutex::new(BTreeMap::new()),
            robot_closures: Arc::new(robot::Closures::default()),
        };
        let captured = server.robot_closures.capture(&binding, &intent).unwrap();
        let writer = rusqlite::Connection::open(&path).unwrap();
        writer.execute_batch("BEGIN IMMEDIATE").unwrap();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        server.queue_robot_closure_with(captured.clone(), async move {
            let mut stream = tokio::net::TcpStream::connect(address).await?;
            stream.write_all(b"C").await?;
            Ok(RemoteReply::Absent)
        });
        let (mut stream, _) = tokio::time::timeout(Duration::from_secs(1), listener.accept())
            .await
            .unwrap()
            .unwrap();
        assert_eq!(stream.read_u8().await.unwrap(), b'C');
        writer.execute_batch("ROLLBACK").unwrap();
        tokio::time::timeout(Duration::from_secs(2), async {
            while server.robot_closures.any_running() {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        let saved = store.robot_intent(&a.id, "key").unwrap();
        assert!(saved.cancellation_requested && saved.outstanding_debit);
        assert_eq!(saved.handle, intent.handle);
    }
}
