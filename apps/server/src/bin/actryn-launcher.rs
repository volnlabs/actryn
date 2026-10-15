use actryn_server::{
    launcher::{Launcher, LauncherConfig, LAUNCHER_SOCKET},
    protocol,
};
use anyhow::{ensure, Result};
use std::{
    fs,
    os::unix::fs::{FileTypeExt, PermissionsExt},
    path::Path,
    sync::Arc,
    time::Duration,
};
use tokio::{
    net::UnixListener,
    sync::{Mutex, Semaphore},
};
#[tokio::main]
async fn main() -> Result<()> {
    ensure!(
        std::env::args_os().len() == 1,
        "launcher accepts no caller configuration arguments"
    );
    fs::create_dir_all(actryn_server::launcher::STATE_ROOT)?;
    let _lifetime =
        actryn_server::launcher::lock_service(Path::new("/var/lib/actryn-server/launcher.lock"))?;
    let config = LauncherConfig::read(Path::new("/etc/actryn/server.json"))?;
    let allowed = config.server_uid;
    let mut launcher = Launcher::new(config).await?;
    launcher.recover().await?;
    let launcher = Arc::new(Mutex::new(launcher));
    let ticker = launcher.clone();
    tokio::spawn(async move {
        let mut timer = tokio::time::interval(Duration::from_millis(250));
        loop {
            timer.tick().await;
            if let Err(e) = ticker.lock().await.tick().await {
                eprintln!("launcher health: {e:#}");
            }
        }
    });
    if let Ok(m) = fs::symlink_metadata(LAUNCHER_SOCKET) {
        ensure!(m.file_type().is_socket(), "launcher path occupied");
        fs::remove_file(LAUNCHER_SOCKET)?;
    }
    let listener = UnixListener::bind(LAUNCHER_SOCKET)?;
    fs::set_permissions(LAUNCHER_SOCKET, fs::Permissions::from_mode(0o666))?;
    let slots = Arc::new(Semaphore::new(4));
    loop {
        let (mut stream, _) = listener.accept().await?;
        let uid = stream.peer_cred()?.uid();
        if uid != 0 && uid != allowed {
            continue;
        }
        let Ok(permit) = slots.clone().try_acquire_owned() else {
            continue;
        };
        let launcher = launcher.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let result: Result<()> = async {
                let bytes =
                    tokio::time::timeout(Duration::from_secs(1), protocol::read_frame(&mut stream))
                        .await??;
                let request = protocol::decode_request(&bytes)?;
                let response = launcher.lock().await.handle(request).await;
                tokio::time::timeout(
                    Duration::from_secs(1),
                    protocol::write_frame(&mut stream, &serde_json::to_vec(&response)?),
                )
                .await??;
                Ok(())
            }
            .await;
            if let Err(e) = result {
                eprintln!("launcher request: {e:#}");
            }
        });
    }
}
