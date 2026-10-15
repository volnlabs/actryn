use crate::{
    rpc,
    state::{self, hex, unhex, Pair, SavedHandle, SavedProposal},
};
use anyhow::{bail, ensure, Context, Result};
use robot_rpc::wire::{self, request::Command};
use serde_json::{json, Value};
use std::{collections::BTreeMap, path::Path};

struct Flags(BTreeMap<String, String>);
impl Flags {
    fn parse(args: &[String]) -> Result<Self> {
        let mut flags = BTreeMap::new();
        let mut offset = 0;
        while offset < args.len() {
            let name = args[offset]
                .strip_prefix("--")
                .filter(|v| !v.is_empty())
                .context("expected named --option")?;
            let value = if matches!(name, "local" | "can-propose") {
                "true".to_owned()
            } else {
                offset += 1;
                args.get(offset).context("option needs a value")?.clone()
            };
            ensure!(
                flags.insert(name.into(), value).is_none(),
                "duplicate option --{name}"
            );
            offset += 1;
        }
        Ok(Self(flags))
    }
    fn allow(&self, names: &[&str]) -> Result<()> {
        for name in self.0.keys() {
            ensure!(
                names.contains(&name.as_str()),
                "unsupported option --{name}"
            );
        }
        Ok(())
    }
    fn get(&self, name: &str) -> Result<&str> {
        self.0
            .get(name)
            .map(String::as_str)
            .with_context(|| format!("missing --{name}"))
    }
    fn optional(&self, name: &str) -> Option<&str> {
        self.0.get(name).map(String::as_str)
    }
    fn yes(&self, name: &str) -> bool {
        self.0.contains_key(name)
    }
    fn epoch(&self) -> Result<Vec<u8>> {
        ensure!(
            !(self.yes("epoch") && self.yes("pair")),
            "select --epoch or --pair"
        );
        if let Some(pair) = self.optional("pair") {
            unhex(&state::load_pair(Path::new(pair))?.robot_epoch, 16)
        } else {
            unhex(self.get("epoch")?, 16)
        }
    }
    fn credentials(&self) -> Result<(Vec<u8>, Vec<u8>)> {
        Ok((
            state::read_file(Path::new(self.get("cert")?), 24576, false)?,
            state::read_file(Path::new(self.get("key")?), 8192, true)?,
        ))
    }
}
fn request(command: Command, epoch: Vec<u8>) -> Result<wire::Request> {
    let request = wire::Request {
        version: robot_rpc::VERSION,
        request_id: robot_rpc::random_id::<16>()?.to_vec(),
        robot_epoch: epoch,
        command: Some(command),
    };
    request.validate()?;
    Ok(request)
}
fn rendered(
    response: std::result::Result<wire::Response, rpc::ExchangeError>,
    request: &wire::Request,
) -> Value {
    let mut output = match response {
        Ok(response) => match rpc::robot_json(response) {
            Ok(value) => value,
            Err(error) => rpc::ExchangeError::new(error, rpc::mutation(request)).json(),
        },
        Err(error) => error.json(),
    };
    output["request_id"] = json!(hex(&request.request_id));
    output
}
async fn local(command: Command, epoch: Vec<u8>) -> Result<Value> {
    let request = request(command, epoch)?;
    Ok(rendered(rpc::local(&request).await, &request))
}
fn help() -> Value {
    json!({"result":"help","version":env!("CARGO_PKG_VERSION"),"commands":[
 "server status --attempt ID","server prepare --artifact sha256:DIGEST","server launch --attempt ID","server cancel --attempt ID","server result --attempt ID --key KEY","server export --attempt ID --out FILE",
 "robot describe|status|doctor","robot enroll-request --dns NAME","robot enroll-install --cert FILE --ca FILE",
 "robot install-principal --epoch EPOCH --principal NAME --pin LEAF_SHA256 [--can-propose]","robot revoke-principal --epoch EPOCH --principal NAME",
 "robot pair --endpoint IP:PORT --dns NAME --pin LEAF_SHA256 --ca FILE --cert FILE --key FILE --out FILE",
 "robot handle --pair FILE --attempt ID [--namespace ID] --out FILE","robot prepare --handle FILE --principal NAME",
 "robot rearm|activate|reconcile|recover|revoke|retire --epoch EPOCH","robot grant --epoch EPOCH --duration-ms MS",
 "robot observe --pair FILE --cert FILE --key FILE --handle FILE",
 "robot propose --pair FILE --cert FILE --key FILE --handle FILE --observation ID --parent-digest HEX --left TICKS --right TICKS --duration-ms MS",
 "robot query|cancel --pair FILE --cert FILE --key FILE --handle FILE","robot query|cancel --local --handle FILE [--epoch EPOCH]"
 ],"rules":["All output is JSON; errors exit nonzero.","Local epoch-based commands also accept --pair FILE instead of --epoch.","A handle is durable before proposal transmission. A proposal is never retried.","After uncertainty, query or cancel the same handle. Pairing never grants or rearms.","Installation and execution replay are separate release tooling; this CLI does not infer replay eligibility."]})
}
pub async fn run(args: Vec<String>) -> Result<Value> {
    ensure!(
        args.len() <= 64 && args.iter().map(String::len).sum::<usize>() <= 16384,
        "command arguments exceed bound"
    );
    if args.is_empty() || args == ["--help"] || args == ["help"] {
        return Ok(help());
    }
    ensure!(args.len() >= 2, "expected server or robot command");
    let flags = Flags::parse(&args[2..])?;
    match args[0].as_str() {
        "server" => server(&args[1], &flags).await,
        "robot" => robot(&args[1], &flags).await,
        _ => bail!("unknown command group"),
    }
}
async fn server(verb: &str, flags: &Flags) -> Result<Value> {
    use actryn_server::protocol::{Request, Response};
    let request = match verb {
        "status" => {
            flags.allow(&["attempt"])?;
            Request::Inspect {
                attempt_id: flags.get("attempt")?.into(),
            }
        }
        "prepare" => {
            flags.allow(&["artifact"])?;
            Request::Prepare {
                artifact_digest: flags.get("artifact")?.into(),
            }
        }
        "launch" => {
            flags.allow(&["attempt"])?;
            Request::Start {
                attempt_id: flags.get("attempt")?.into(),
            }
        }
        "cancel" => {
            flags.allow(&["attempt"])?;
            Request::Stop {
                attempt_id: flags.get("attempt")?.into(),
            }
        }
        "result" => {
            flags.allow(&["attempt", "key"])?;
            Request::Result {
                attempt_id: flags.get("attempt")?.into(),
                request_key: flags.get("key")?.into(),
            }
        }
        "export" => {
            flags.allow(&["attempt", "out"])?;
            flags.get("out")?;
            Request::Export {
                attempt_id: flags.get("attempt")?.into(),
            }
        }
        _ => bail!("unknown server command"),
    };
    actryn_server::protocol::decode_request(&serde_json::to_vec(&request)?)?;
    let response = match rpc::server(&request).await {
        Ok(response) => response,
        Err(error) => return Ok(error.json()),
    };
    if let Response::Error { message } = &response {
        let mutation = matches!(
            request,
            Request::Prepare { .. } | Request::Start { .. } | Request::Stop { .. }
        );
        return Ok(
            json!({"result":"error","code":"server_error","message":message,"outcome_unknown":mutation,"automatic_retry":false,"next_action":"inspect_existing_attempt"}),
        );
    }
    if let (Request::Export { attempt_id }, Response::Evidence { bundle }) = (&request, &response) {
        ensure!(bundle.attempt_id == *attempt_id, "export attempt mismatch");
        bundle.validate_bound()?;
        let path = Path::new(flags.get("out")?);
        state::save_new(path, bundle)?;
        return Ok(
            json!({"result":"exported","attempt_id":attempt_id,"path":path,"execution_replay_eligible":bundle.execution_replay_eligible,"bytes":serde_json::to_vec(bundle)?.len()}),
        );
    }
    Ok(serde_json::to_value(response)?)
}
async fn robot(verb: &str, flags: &Flags) -> Result<Value> {
    match verb {
        "pair" => pair(flags).await,
        "handle" => {
            flags.allow(&["pair", "attempt", "namespace", "out"])?;
            let pair = state::load_pair(Path::new(flags.get("pair")?))?;
            let namespace = match flags.optional("namespace") {
                Some(value) => {
                    unhex(value, 16)?;
                    value.to_owned()
                }
                None => hex(&robot_rpc::random_id::<16>()?),
            };
            let handle = SavedHandle {
                robot_epoch: pair.robot_epoch,
                namespace,
                attempt: flags.get("attempt")?.into(),
                key: hex(&robot_rpc::random_id::<32>()?),
                state: "ready".into(),
                proposal: None,
            };
            handle.validate()?;
            let path = Path::new(flags.get("out")?);
            state::save_new(path, &handle)?;
            Ok(
                json!({"result":"handle_saved","path":path,"handle":handle,"authority_issued":false}),
            )
        }
        "observe" | "propose" | "query" | "cancel" => remote_operation(verb, flags).await,
        "describe" | "status" | "doctor" => {
            flags.allow(&[])?;
            let mut report = local(Command::Describe(wire::Empty {}), vec![]).await?;
            if verb == "doctor" {
                report["client"] = json!({"version":env!("CARGO_PKG_VERSION"),"rpc_version":robot_rpc::VERSION,"uapi_version":authority_client::VERSION});
            }
            Ok(report)
        }
        "prepare" => {
            flags.allow(&["handle", "principal"])?;
            let handle = state::load_handle(Path::new(flags.get("handle")?))?;
            ensure!(handle.state == "ready", "prepare needs an unused handle");
            local(
                Command::Prepare(wire::Prepare {
                    attempt: unhex(&handle.attempt, 16)?,
                    namespace: unhex(&handle.namespace, 16)?,
                    principal: flags.get("principal")?.into(),
                }),
                unhex(&handle.robot_epoch, 16)?,
            )
            .await
        }
        "enroll-request" => {
            flags.allow(&["dns"])?;
            local(
                Command::EnrollRequest(wire::EnrollmentRequest {
                    dns_name: flags.get("dns")?.into(),
                }),
                vec![],
            )
            .await
        }
        "enroll-install" => {
            flags.allow(&["cert", "ca"])?;
            local(
                Command::EnrollInstall(wire::EnrollmentInstall {
                    certificate_pem: state::read_file(Path::new(flags.get("cert")?), 24576, false)?,
                    ca_pem: state::read_file(Path::new(flags.get("ca")?), 24576, false)?,
                }),
                vec![],
            )
            .await
        }
        "install-principal" => {
            flags.allow(&["epoch", "pair", "principal", "pin", "can-propose"])?;
            local(
                Command::InstallPrincipal(wire::PrincipalInstall {
                    principal: flags.get("principal")?.into(),
                    certificate_sha256: flags.get("pin")?.into(),
                    can_propose: flags.yes("can-propose"),
                }),
                flags.epoch()?,
            )
            .await
        }
        "revoke-principal" => {
            flags.allow(&["epoch", "pair", "principal"])?;
            local(
                Command::RevokePrincipal(wire::PrincipalRevoke {
                    principal: flags.get("principal")?.into(),
                }),
                flags.epoch()?,
            )
            .await
        }
        "grant" => {
            flags.allow(&["epoch", "pair", "duration-ms"])?;
            local(
                Command::Grant(wire::Grant {
                    duration_ms: flags.get("duration-ms")?.parse()?,
                }),
                flags.epoch()?,
            )
            .await
        }
        "rearm" | "activate" | "reconcile" | "recover" | "revoke" | "retire" => {
            flags.allow(&["epoch", "pair"])?;
            let empty = wire::Empty {};
            let command = match verb {
                "rearm" => Command::Rearm(empty),
                "activate" => Command::Activate(empty),
                "reconcile" => Command::Reconcile(empty),
                "recover" => Command::Recover(empty),
                "revoke" => Command::Revoke(empty),
                _ => Command::Retire(empty),
            };
            local(command, flags.epoch()?).await
        }
        _ => bail!("unknown robot command"),
    }
}
async fn pair(flags: &Flags) -> Result<Value> {
    flags.allow(&["endpoint", "dns", "pin", "ca", "cert", "key", "out"])?;
    let mut pair = Pair {
        schema: 1,
        endpoint: flags.get("endpoint")?.into(),
        dns_name: flags.get("dns")?.into(),
        device_certificate_sha256: flags.get("pin")?.into(),
        ca_pem: String::from_utf8(state::read_file(Path::new(flags.get("ca")?), 24576, false)?)?,
        robot_epoch: "00".repeat(16),
    };
    pair.validate()?;
    let path = Path::new(flags.get("out")?);
    ensure!(!path.exists(), "pairing output already exists");
    let (certificate, key) = flags.credentials()?;
    let request = request(Command::Describe(wire::Empty {}), vec![])?;
    let response = match rpc::remote(&pair, &certificate, &key, &request).await {
        Ok(response) => response,
        Err(error) => return Ok(error.json()),
    };
    let epoch = hex(&response.robot_epoch);
    let report = rpc::robot_json(response)?;
    if report["result"] == "error" {
        return Ok(report);
    }
    ensure!(
        report["result"] == "report",
        "pairing requires device description"
    );
    if let Some(pin) = report["report"]["identity"]["device_certificate_sha256"].as_str() {
        ensure!(
            pin == pair.device_certificate_sha256,
            "device report disagrees with authenticated certificate"
        );
    }
    pair.robot_epoch = epoch;
    state::save_new(path, &pair)?;
    Ok(
        json!({"result":"paired","path":path,"device_certificate_sha256":pair.device_certificate_sha256,"robot_epoch":pair.robot_epoch,"authority_issued":false}),
    )
}
async fn remote_operation(verb: &str, flags: &Flags) -> Result<Value> {
    let local_only = flags.yes("local");
    if local_only {
        ensure!(
            matches!(verb, "query" | "cancel"),
            "only query/cancel have this local route"
        );
        flags.allow(&["local", "handle", "epoch"])?;
    } else if verb == "propose" {
        flags.allow(&[
            "pair",
            "cert",
            "key",
            "handle",
            "observation",
            "parent-digest",
            "left",
            "right",
            "duration-ms",
        ])?;
    } else {
        flags.allow(&["pair", "cert", "key", "handle"])?;
    }
    let path = Path::new(flags.get("handle")?);
    let mut handle = state::load_handle(path)?;
    let pair = if local_only {
        None
    } else {
        Some(state::load_pair(Path::new(flags.get("pair")?))?)
    };
    if matches!(verb, "observe" | "propose") {
        ensure!(
            pair.as_ref()
                .is_some_and(|pair| pair.robot_epoch == handle.robot_epoch),
            "retired handle cannot observe or propose in a new epoch"
        );
    }
    let credentials = if local_only {
        None
    } else {
        Some(flags.credentials()?)
    };
    let command = match verb {
        "observe" => {
            let mut wire = handle.wire()?;
            wire.key.clear();
            Command::Observe(wire)
        }
        "propose" => {
            let proposal = SavedProposal {
                observation_id: flags.get("observation")?.parse()?,
                parent_digest: flags.get("parent-digest")?.into(),
                left_delta_ticks: flags.get("left")?.parse()?,
                right_delta_ticks: flags.get("right")?.parse()?,
                duration_ms: flags.get("duration-ms")?.parse()?,
            };
            proposal.validate()?;
            handle = state::begin_proposal(path, proposal.clone())?;
            Command::Propose(proposal.wire(&handle)?)
        }
        "query" => Command::Query(handle.wire()?),
        "cancel" => {
            handle = state::close_handle(path)?;
            Command::Cancel(handle.wire()?)
        }
        _ => unreachable!(),
    };
    let epoch = if let Some(pair) = &pair {
        unhex(&pair.robot_epoch, 16)?
    } else {
        unhex(flags.optional("epoch").unwrap_or(&handle.robot_epoch), 16)?
    };
    let request = request(command, epoch)?;
    let response = if let (Some(pair), Some((certificate, key))) = (pair, credentials) {
        rpc::remote(&pair, &certificate, &key, &request).await
    } else {
        rpc::local(&request).await
    };
    let mut result = rendered(response, &request);
    result["handle_path"] = json!(path);
    result["handle_state"] = json!(handle.state);
    result["handle"] =
        json!({"namespace":handle.namespace,"attempt":handle.attempt,"key":handle.key});
    Ok(result)
}
