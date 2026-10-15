use prost::Message;
use robot_rpc::{
    wire::{self, request::Command},
    *,
};
use tokio::io::AsyncWriteExt;
fn proposal() -> wire::Request {
    wire::Request {
        version: 1,
        request_id: vec![1; 16],
        robot_epoch: vec![2; 16],
        command: Some(Command::Propose(wire::Proposal {
            handle: Some(wire::Handle {
                namespace: vec![3; 16],
                key: vec![4; 32],
                attempt: vec![6; 16],
            }),
            observation_id: 1,
            target: Some(wire::Target {
                left_delta_ticks: 10,
                right_delta_ticks: 10,
                duration_ms: 1000,
            }),
            parent_digest: vec![5; 32],
        })),
    }
}
#[tokio::test]
async fn canonical_typed_frames_reject_unknown_duplicate_and_oversize() {
    let request = proposal();
    request.validate().unwrap();
    let bytes = request.encode_to_vec();
    for suffix in [vec![0x08, 1], vec![0xf8, 0x07, 0x01]] {
        let (mut sender, mut receiver) = tokio::io::duplex(1024);
        let mut bad = bytes.clone();
        bad.extend(suffix);
        sender.write_u32(bad.len() as u32).await.unwrap();
        sender.write_all(&bad).await.unwrap();
        assert!(read_message::<wire::Request>(&mut receiver).await.is_err());
    }
    let (mut sender, mut receiver) = tokio::io::duplex(1024);
    sender.write_u32(65537).await.unwrap();
    assert!(read_message::<wire::Request>(&mut receiver).await.is_err());
    let (mut sender, mut receiver) = tokio::io::duplex(1024);
    sender.write_u32(4097).await.unwrap();
    assert!(read_message_limit::<wire::Request>(&mut receiver, 4096)
        .await
        .is_err());
    let (mut sender, mut receiver) = tokio::io::duplex(1024);
    write_message(&mut sender, &request).await.unwrap();
    assert_eq!(
        read_message::<wire::Request>(&mut receiver).await.unwrap(),
        request
    );
}
#[test]
fn scope_and_envelope_do_not_accept_authority_in_caller_fields() {
    let mut r = proposal();
    assert_eq!(r.remote_scope().unwrap(), Scope::Propose);
    if let Some(Command::Propose(p)) = &mut r.command {
        p.target.as_mut().unwrap().left_delta_ticks = i64::MIN;
    }
    assert!(r.validate().is_err());
    r.command = Some(Command::Grant(wire::Grant { duration_ms: 1000 }));
    r.validate().unwrap();
    assert!(r.remote_scope().is_err());
    r.robot_epoch.clear();
    assert!(r.validate().is_err());
    r.robot_epoch = vec![2; 16];
    r.command = Some(Command::InstallPrincipal(wire::PrincipalInstall {
        principal: "workload".into(),
        certificate_sha256: "ab".repeat(32),
        can_propose: true,
    }));
    r.validate().unwrap();
    assert!(r.remote_scope().is_err());
    if let Some(Command::InstallPrincipal(p)) = &mut r.command {
        p.certificate_sha256 = "../../policy".into();
    }
    assert!(r.validate().is_err());
}
#[test]
fn clock_discontinuity_is_sticky_and_restart_floor_is_enforced() {
    assert!(ClockGuard::new(99, 0, 100).is_err());
    let mut guard = ClockGuard::new(10_000_000_000, 1, 0).unwrap();
    guard.check(10_100_000_000, 100_000_001).unwrap();
    assert!(guard.check(8_000_000_000, 200_000_001).is_err());
    assert!(guard.check(10_300_000_000, 300_000_001).is_err());
    let mut guard = ClockGuard::new(10_000_000_000, 1_000_000_000, 0).unwrap();
    guard.check(10_500_000_000, 1_500_000_000).unwrap();
    assert!(guard.check(10_500_000_000, 1_400_000_000).is_err());
    assert!(guard.check(10_600_000_000, 1_600_000_000).is_err());
}

#[test]
fn evidence_reads_are_scoped_bounded_and_cannot_select_private_paths() {
    let mut request = proposal();
    request.command = Some(Command::EvidenceRead(wire::EvidenceRead {
        handle: Some(wire::Handle {
            attempt: vec![1; 16],
            namespace: vec![2; 16],
            key: vec![3; 32],
        }),
        file: "checkpoints.sqlite".into(),
        offset: 0,
    }));
    request.validate().unwrap();
    assert_eq!(request.remote_scope().unwrap(), Scope::Read);
    assert!(valid_capture_file("batch-00000000000000000001.mcap"));
    assert!(!valid_capture_file("../identity/key.pem"));
    if let Some(Command::EvidenceRead(e)) = request.command.as_mut() {
        e.offset = 67_108_865;
    }
    assert!(request.validate().is_err());
    if let Some(Command::EvidenceRead(e)) = request.command.as_mut() {
        e.offset = 0;
        e.file = "../key.pem".into();
    }
    assert!(request.validate().is_err());
}
