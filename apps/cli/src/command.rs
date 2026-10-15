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
 "server import --layout DIRECTORY --digest sha256:DIGEST","server discard-incomplete --digest sha256:DIGEST",
 "server bind-robot --attempt ID --namespace ID","server robot-query|robot-cancel --attempt ID --key AGENT_REQUEST_KEY",
 "install inspect|stage|activate|recover|rollback|resume --role server|robot --bundle DIRECTORY --public-key FILE --key-sha256 SPKI_SHA256",
 "install preflight --role server|robot",
 "robot describe|status|doctor","robot enroll-request --dns NAME","robot enroll-install --cert FILE --ca FILE",
 "robot install-principal --epoch EPOCH --principal NAME --pin LEAF_SHA256 [--can-propose]","robot revoke-principal --epoch EPOCH --principal NAME",
 "robot pair --endpoint IP:PORT --dns NAME --pin LEAF_SHA256 --ca FILE --cert FILE --key FILE --out FILE",
 "robot handle --pair FILE --attempt ID [--namespace ID] --out FILE","robot prepare --handle FILE --principal NAME",
 "robot rearm|activate|reconcile|recover|revoke|retire --epoch EPOCH","robot grant --epoch EPOCH --duration-ms MS",
 "robot observe --pair FILE --cert FILE --key FILE --handle FILE",
 "robot propose --pair FILE --cert FILE --key FILE --handle FILE --observation ID --parent-digest HEX --left TICKS --right TICKS --duration-ms MS",
 "robot query|cancel --pair FILE --cert FILE --key FILE --handle FILE","robot query|cancel --local --handle FILE [--epoch EPOCH]"
 ,"robot export --local --handle FILE --out DIRECTORY","robot export --pair FILE --cert FILE --key FILE --handle FILE --out DIRECTORY"
 ],"rules":["All output is JSON; errors exit nonzero.","Local epoch-based commands also accept --pair FILE instead of --epoch.","A handle is durable before proposal transmission. A proposal is never retried.","After uncertainty, query or cancel the same handle. Pairing never grants or rearms.","Install delegates to the protected installed release tooling; first bootstrap uses the verified release scripts. Execution replay eligibility is never inferred."]})
}

fn installer_arguments(verb: &str, flags: &Flags) -> Result<(String, Vec<String>)> {
    ensure!(
        [
            "inspect",
            "stage",
            "activate",
            "recover",
            "rollback",
            "resume",
            "preflight"
        ]
        .contains(&verb),
        "unknown installation action"
    );
    flags.allow(if verb == "preflight" {
        &["role"]
    } else {
        &["role", "bundle", "public-key", "key-sha256"]
    })?;
    let role = flags.get("role")?;
    ensure!(
        matches!(role, "server" | "robot"),
        "invalid installation role"
    );
    let mut args = vec![verb.to_owned()];
    if verb != "inspect" {
        args.extend(["--role".into(), role.into()]);
    }
    if verb != "preflight" {
        ensure!(
            flags.yes("public-key") == flags.yes("key-sha256"),
            "supply both public key and trust pin"
        );
        if verb != "inspect" || flags.yes("key-sha256") {
            unhex(flags.get("key-sha256")?, 32)?;
            flags.get("public-key")?;
        }
        for name in ["bundle", "public-key", "key-sha256"] {
            let value = if name == "bundle" {
                Some(flags.get(name)?)
            } else {
                flags.optional(name)
            };
            if let Some(value) = value {
                ensure!(!value.is_empty(), "empty installer argument");
                // Equals form keeps a caller path beginning with '-' a value.
                args.push(format!("--{name}={value}"));
            }
        }
    }
    Ok((role.into(), args))
}

/// Main replaces itself with the existing installer, preserving its exit status
/// and interruption behavior; the CLI never retries or interprets a lost install.
pub fn installation_command(args: &[String]) -> Result<Option<std::process::Command>> {
    if args.first().map(String::as_str) != Some("install") {
        return Ok(None);
    }
    ensure!(
        args.len() <= 64 && args.iter().map(String::len).sum::<usize>() <= 16384,
        "command arguments exceed bound"
    );
    let verb = args.get(1).context("missing installation action")?;
    let (role, arguments) = installer_arguments(verb, &Flags::parse(&args[2..])?)?;
    let root = std::path::PathBuf::from(format!("/opt/actryn/{role}"));
    let script = root
        .join("current/tools/release.py")
        .canonicalize()
        .context(
            "installed release tooling absent; first bootstrap uses the verified release scripts",
        )?;
    let relative = script.strip_prefix(root.join("releases"))?;
    let parts: Vec<_> = relative.components().collect();
    ensure!(
        parts.len() == 4
            && parts[1].as_os_str() == "payload"
            && parts[2].as_os_str() == "tools"
            && parts[3].as_os_str() == "release.py",
        "installer outside immutable role slot"
    );
    unhex(
        parts[0]
            .as_os_str()
            .to_str()
            .context("invalid slot identity")?,
        32,
    )?;
    robot_rpc::read_protected(&script, 65536, false)?;
    robot_rpc::read_protected(&script.with_file_name("install.py"), 65536, false)?;
    let mut command = std::process::Command::new("/usr/bin/python3");
    command
        .args(["-B", "-E", "-s"])
        .arg(script)
        .args(arguments)
        .env_clear()
        .env("PATH", "/usr/sbin:/usr/bin:/sbin:/bin");
    Ok(Some(command))
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
        "import" => {
            flags.allow(&["layout", "digest"])?;
            let layout = flags.get("layout")?;
            let digest = flags.get("digest")?;
            ensure!(
                actryn_server::store::valid_digest(digest),
                "invalid artifact digest"
            );
            return actryn_server::artifact::import(Path::new(layout), digest);
        }
        "discard-incomplete" => {
            flags.allow(&["digest"])?;
            let digest = flags.get("digest")?;
            ensure!(
                actryn_server::store::valid_digest(digest),
                "invalid artifact digest"
            );
            return actryn_server::artifact::discard_incomplete(digest);
        }
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
        "bind-robot" => {
            flags.allow(&["attempt", "namespace"])?;
            Request::BindRobot {
                attempt_id: flags.get("attempt")?.into(),
                namespace: flags.get("namespace")?.into(),
            }
        }
        "robot-query" | "robot-cancel" => {
            flags.allow(&["attempt", "key"])?;
            let attempt_id = flags.get("attempt")?.into();
            let request_key = flags.get("key")?.into();
            if verb == "robot-cancel" {
                Request::RobotCancel {
                    attempt_id,
                    request_key,
                }
            } else {
                Request::RobotQuery {
                    attempt_id,
                    request_key,
                }
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
        let mutation = rpc::server_mutation(&request);
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
        "export" => export_robot(flags).await,
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
async fn export_robot(flags: &Flags) -> Result<Value> {
    use std::{
        fs::{self, DirBuilder, File},
        os::unix::fs::DirBuilderExt,
    };
    flags.allow(&["local", "handle", "out", "pair", "cert", "key"])?;
    ensure!(
        flags.yes("local") != flags.yes("pair"),
        "choose local export or paired endpoint"
    );
    let out = state::export_destination(Path::new(flags.get("out")?))?;
    let handle = state::load_handle(Path::new(flags.get("handle")?))?;
    let connection = if flags.yes("local") {
        ensure!(
            !flags.yes("cert") && !flags.yes("key"),
            "local export does not take network credentials"
        );
        None
    } else {
        let pair = state::load_pair(Path::new(flags.get("pair")?))?;
        let (certificate, key) = flags.credentials()?;
        Some((pair, certificate, key))
    };
    let epoch = if let Some((pair, _, _)) = &connection {
        unhex(&pair.robot_epoch, 16)?
    } else {
        let description = local(Command::Describe(wire::Empty {}), vec![]).await?;
        ensure!(
            description["result"] == "report",
            "manager description unavailable"
        );
        unhex(
            description["robot_epoch"]
                .as_str()
                .context("manager epoch missing")?,
            16,
        )?
    };
    let read = async |name: &str, offset: u64| -> Result<Value> {
        let req = request(
            Command::EvidenceRead(wire::EvidenceRead {
                handle: Some(handle.wire()?),
                file: name.into(),
                offset,
            }),
            epoch.clone(),
        )?;
        let response = match &connection {
            Some((pair, certificate, key)) => rpc::remote(pair, certificate, key, &req).await,
            None => rpc::local(&req).await,
        }
        .map_err(|e| anyhow::anyhow!(e.message))?;
        let response = rpc::robot_json(response)?;
        ensure!(
            response["result"] == "report",
            "evidence unavailable: {}",
            response
        );
        Ok(response["report"].clone())
    };
    let mut manifest = read("", 0).await?;
    let inspection = &manifest["inspection"];
    ensure!(
        inspection["live_authority"] == false
            && serde_json::from_value::<Vec<u8>>(
                inspection["prepared"]["binding"]["attempt"].clone()
            )? == unhex(&handle.attempt, 16)?
            && serde_json::from_value::<Vec<u8>>(
                inspection["prepared"]["binding"]["namespace"].clone()
            )? == unhex(&handle.namespace, 16)?,
        "export binding mismatch"
    );
    let count = manifest["file_count"]
        .as_u64()
        .filter(|n| *n <= 8192)
        .context("capture file capacity")?;
    let total = manifest["total_bytes"]
        .as_u64()
        .filter(|n| *n <= crate::export::MAX_BYTES)
        .context("capture byte capacity")?;
    let mut entries = manifest["files"]
        .as_array()
        .context("capture entries")?
        .clone();
    let mut next = manifest["next_offset"].clone();
    while !next.is_null() {
        let offset = next
            .as_u64()
            .filter(|n| *n == entries.len() as u64 && *n < count)
            .context("capture pagination")?;
        let page = read("", offset).await?;
        ensure!(
            page["file_count"] == count && page["total_bytes"] == total,
            "capture listing changed"
        );
        let files = page["files"].as_array().context("capture page")?;
        ensure!(
            !files.is_empty() && files.len() <= 32 && entries.len() + files.len() <= 8192,
            "capture page bound"
        );
        entries.extend(files.iter().cloned());
        next = page["next_offset"].clone();
    }
    ensure!(entries.len() as u64 == count, "incomplete capture listing");
    let mut seen = std::collections::BTreeSet::new();
    let mut bytes = 0u64;
    for entry in &entries {
        let name = entry["file"].as_str().context("capture filename")?;
        ensure!(
            robot_rpc::valid_capture_file(name) && seen.insert(name),
            "invalid/duplicate capture filename"
        );
        bytes = bytes
            .checked_add(entry["size"].as_u64().context("capture size")?)
            .context("capture size overflow")?;
    }
    ensure!(bytes == total, "capture total mismatch");
    DirBuilder::new().mode(0o700).create(&out)?;
    state::save_new(
        &out.join("INCOMPLETE.json"),
        &json!({"attempt":handle.attempt,"namespace":handle.namespace}),
    )?;
    DirBuilder::new().mode(0o700).create(out.join("capture"))?;
    for entry in &entries {
        let mut file = crate::export::CaptureFile::create(&out.join("capture"), entry)?;
        while file.offset < file.size {
            file.append(&read(entry["file"].as_str().unwrap(), file.offset).await?)?;
        }
        file.finish()?;
    }
    File::open(out.join("capture"))?.sync_all()?;
    manifest["files"] = json!(entries);
    manifest["next_offset"] = Value::Null;
    manifest["format"] = json!("actryn-robot-evidence-1");
    crate::export::save_manifest(&out.join("manifest.json"), &manifest)?;
    fs::remove_file(out.join("INCOMPLETE.json"))?;
    File::open(&out)?.sync_all()?;
    Ok(
        json!({"result":"exported","path":out,"attempt":handle.attempt,"namespace":handle.namespace,"files":count,"bytes":total,"execution_replay_eligible":false,"volatile_tail_unknown":true}),
    )
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

#[cfg(test)]
mod installer_tests {
    use super::*;
    #[test]
    fn fixed_installer_route_preserves_paths_and_requires_paired_trust() {
        let flags = |values: &[&str]| {
            Flags::parse(&values.iter().map(|v| (*v).into()).collect::<Vec<_>>()).unwrap()
        };
        let pin = "11".repeat(32);
        let (role, args) = installer_arguments(
            "activate",
            &flags(&[
                "--role",
                "robot",
                "--bundle",
                "-strange path",
                "--public-key",
                "key.pem",
                "--key-sha256",
                &pin,
            ]),
        )
        .unwrap();
        assert_eq!(role, "robot");
        assert!(args.contains(&"--bundle=-strange path".into()));
        assert!(
            installer_arguments("activate", &flags(&["--role", "robot", "--bundle", "x"])).is_err()
        );
        assert!(installer_arguments(
            "inspect",
            &flags(&[
                "--role",
                "server",
                "--bundle",
                "x",
                "--public-key",
                "key.pem"
            ])
        )
        .is_err());
        assert!(installer_arguments("preflight", &flags(&["--role", "../server"])).is_err());
        assert!(installer_arguments(
            "preflight",
            &flags(&["--role", "robot", "--script", "/tmp/other.py"])
        )
        .is_err());
        assert!(installer_arguments("build", &flags(&["--role", "robot"])).is_err());
    }
}
