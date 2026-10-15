use actryn_server::{
    launcher::{LauncherConfig, SERVER_SOCKET},
    protocol,
    service::Server,
};
use anyhow::{ensure, Result};
use std::{
    fs,
    os::unix::fs::{FileTypeExt, PermissionsExt},
    path::Path,
    sync::Arc,
    time::Duration,
};
use tokio::{net::UnixListener, sync::Semaphore};
#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let recovery_only = args.len() == 1 && args[0] == "--recover-only";
    ensure!(
        args.is_empty() || recovery_only,
        "server accepts only the fixed recovery mode"
    );
    let config = LauncherConfig::read(Path::new("/etc/actryn/server.json"))?;
    let operator = config.operator_uid;
    let _lifetime = actryn_server::launcher::lock_service(Path::new(
        "/var/lib/actryn-server/broker/server.lock",
    ))?;
    let server = Server::new(&config).await?;
    if recovery_only {
        return Ok(());
    }
    let monitor = server.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_millis(500));
        loop {
            interval.tick().await;
            if let Err(error) = monitor.tick().await {
                eprintln!("server supervision: {error:#}");
            }
        }
    });
    if let Ok(m) = fs::symlink_metadata(SERVER_SOCKET) {
        ensure!(m.file_type().is_socket(), "server socket path occupied");
        fs::remove_file(SERVER_SOCKET)?;
    }
    let listener = UnixListener::bind(SERVER_SOCKET)?;
    fs::set_permissions(SERVER_SOCKET, fs::Permissions::from_mode(0o666))?;
    actryn_server::notify_ready()?;
    let slots = Arc::new(Semaphore::new(4));
    loop {
        let (mut stream, _) = listener.accept().await?;
        let uid = stream.peer_cred()?.uid();
        if uid != 0 && uid != operator {
            continue;
        }
        let Ok(permit) = slots.clone().try_acquire_owned() else {
            continue;
        };
        let server = server.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let result: Result<()> = async {
                let bytes =
                    tokio::time::timeout(Duration::from_secs(1), protocol::read_frame(&mut stream))
                        .await??;
                let request = protocol::decode_request(&bytes)?;
                let response = server.handle(request.clone()).await;
                server
                    .send_response(&mut stream, &request, &response)
                    .await?;
                Ok(())
            }
            .await;
            if let Err(e) = result {
                eprintln!("server request: {e:#}");
            }
        });
    }
}
