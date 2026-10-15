//! Unprivileged encrypted-stream relay; credentials and RPC decoding stay in robotd.
use anyhow::{ensure, Result};
use std::{sync::Arc, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, UnixStream},
    sync::Semaphore,
};
const CONTROL: &str = "/run/actryn-robot/gateway-control.sock";
const RELAY: &str = "/run/actryn-robot/relay.sock";
#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() -> Result<()> {
    ensure!(
        std::env::args_os().len() == 1,
        "gateway has no dynamic routes"
    );
    let mut control = UnixStream::connect(CONTROL).await?;
    control.write_all(b"ACTRYN-GW1").await?;
    let mut accepted = [0; 1];
    tokio::time::timeout(Duration::from_secs(2), control.read_exact(&mut accepted)).await??;
    ensure!(accepted == [1], "manager refused gateway lifetime");
    let listener = TcpListener::bind("0.0.0.0:7443").await?;
    let slots = Arc::new(Semaphore::new(8));
    let mut heartbeat = tokio::time::interval(Duration::from_secs(1));
    loop {
        tokio::select! {
            result=listener.accept() => {
                let(mut incoming,_)=result?;
                let Ok(permit)=slots.clone().try_acquire_owned() else {continue};
                tokio::spawn(async move {
                    let _permit=permit;
                    if let Ok(Ok(mut outgoing))=tokio::time::timeout(Duration::from_secs(1),UnixStream::connect(RELAY)).await {
                        // Two fixed 4 KiB buffers; encrypted contents are never interpreted.
                        let _=tokio::io::copy_bidirectional_with_sizes(&mut incoming,&mut outgoing,4096,4096).await;
                    }
                });
            }
            _=heartbeat.tick() => {
                tokio::time::timeout(Duration::from_secs(1),control.write_all(b"H")).await??;
            }
            result=control.read(&mut accepted) => { result?; anyhow::bail!("manager control channel closed"); }
        }
    }
}
