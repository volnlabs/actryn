mod enrollment;
mod export;
mod service;
mod storage;

use anyhow::{ensure, Result};
use serde::Deserialize;
use std::{
    path::{Path, PathBuf},
    sync::Arc,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    operator_uid: u32,
    gateway_uid: u32,
}

#[tokio::main(flavor = "multi_thread", worker_threads = 4)]
async fn main() -> Result<()> {
    ensure!(
        std::env::args_os().len() == 1,
        "robotd has no dynamic routes"
    );
    ensure!(
        unsafe { libc::geteuid() } == 0,
        "robotd requires local kernel administration"
    );
    let config: Config = serde_json::from_slice(&robot_rpc::read_protected(
        Path::new("/etc/actryn/robot.json"),
        4096,
        false,
    )?)?;
    ensure!(
        config.gateway_uid != 0 && config.gateway_uid != config.operator_uid,
        "gateway must have a distinct unprivileged identity"
    );
    let root = PathBuf::from("/var/lib/actryn-robot");
    storage::private_directory(&root)?;
    storage::private_directory(&root.join("identity"))?;
    storage::private_directory(&root.join("runtime"))?;
    storage::private_directory(&root.join("revoked"))?;
    let engine = Arc::new(robot_runtime::Engine::open(root.join("runtime"))?);
    let state = Arc::new(service::State::open(root, engine)?);
    service::serve(state, config.operator_uid, config.gateway_uid).await
}
