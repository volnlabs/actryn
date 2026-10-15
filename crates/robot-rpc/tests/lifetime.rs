use robot_rpc::PeerLifetime;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::UnixListener,
    process::Command,
};
#[tokio::test]
async fn peer_exit_is_detected_while_child_retains_transport_descriptor() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("relay.sock");
    let listener = UnixListener::bind(&path).unwrap();
    let script = r#"
import os,socket,sys,time
s=socket.socket(socket.AF_UNIX);s.connect(sys.argv[1]);s.recv(1)
if os.fork()==0:
 time.sleep(2)
 os._exit(0)
os._exit(0)
"#;
    let mut parent = Command::new("python3")
        .arg("-c")
        .arg(script)
        .arg(path)
        .spawn()
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let lifetime = PeerLifetime::capture(&peer, unsafe { libc::geteuid() }).unwrap();
    assert_eq!(lifetime.pid(), parent.id().unwrap());
    assert!(lifetime.matches(&peer).unwrap());
    peer.write_all(b"G").await.unwrap();
    parent.wait().await.unwrap();
    assert!(!lifetime.alive().unwrap());
    assert!(!lifetime.matches(&peer).unwrap());
    let mut one = [0; 1];
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(100), peer.read(&mut one))
            .await
            .is_err(),
        "child must still retain the stream"
    );
    assert_eq!(
        tokio::time::timeout(std::time::Duration::from_secs(3), peer.read(&mut one))
            .await
            .unwrap()
            .unwrap(),
        0
    );
}
