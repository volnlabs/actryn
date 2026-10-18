//! Restricted server launch and durable delegated-work accounting.
pub mod store;
pub use store::{Attempt, Inspection, Limits, Publication, Reservation, Store};
pub mod broker;
pub mod device_policy;
pub mod evidence;
pub mod launcher;
pub mod model;
pub mod observer;
pub mod policy;
pub mod protocol;
pub mod robot;
pub mod service;

/// systemd readiness notification, after recovery and the authenticated listener are ready.
pub fn notify_ready() -> anyhow::Result<()> {
    use std::os::{
        linux::net::SocketAddrExt,
        unix::net::{SocketAddr, UnixDatagram},
    };
    let Some(path) = std::env::var_os("NOTIFY_SOCKET") else {
        return Ok(());
    };
    let bytes = path.as_encoded_bytes();
    let address = if bytes.first() == Some(&b'@') {
        SocketAddr::from_abstract_name(&bytes[1..])?
    } else {
        SocketAddr::from_pathname(&path)?
    };
    let socket = UnixDatagram::unbound()?;
    socket.set_write_timeout(Some(std::time::Duration::from_secs(1)))?;
    socket.connect_addr(&address)?;
    anyhow::ensure!(
        socket.send(b"READY=1")? == 7,
        "short readiness notification"
    );
    Ok(())
}

pub mod artifact;
