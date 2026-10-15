use actryn_cli::state::*;
fn handle() -> SavedHandle {
    SavedHandle {
        robot_epoch: "11".repeat(16),
        namespace: "22".repeat(16),
        attempt: "33".repeat(16),
        key: "44".repeat(32),
        state: "ready".into(),
        proposal: None,
    }
}
fn proposal() -> SavedProposal {
    SavedProposal {
        observation_id: 7,
        parent_digest: "55".repeat(32),
        left_delta_ticks: -10,
        right_delta_ticks: 10,
        duration_ms: 1000,
    }
}
#[test]
fn durable_handle_precedes_send_and_cannot_be_resubmitted() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("handle.json");
    save_new(&path, &handle()).unwrap();
    assert!(save_new(&path, &handle()).is_err());
    let sent = begin_proposal(&path, proposal()).unwrap();
    assert_eq!(sent.state, "proposal_attempted");
    assert_eq!(
        load_handle(&path).unwrap().proposal.unwrap().observation_id,
        7
    );
    assert!(begin_proposal(&path, proposal()).is_err());
    assert_eq!(close_handle(&path).unwrap().state, "cancel_requested");
    assert_eq!(load_handle(&path).unwrap().key, handle().key);
}
#[test]
fn cancellation_before_proposal_and_competing_senders_close_publication() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("handle.json");
    save_new(&path, &handle()).unwrap();
    close_handle(&path).unwrap();
    assert!(begin_proposal(&path, proposal()).is_err());
    let concurrent = dir.path().join("concurrent.json");
    save_new(&concurrent, &handle()).unwrap();
    let workers: Vec<_> = (0..8)
        .map(|_| {
            let path = concurrent.clone();
            std::thread::spawn(move || begin_proposal(&path, proposal()).is_ok())
        })
        .collect();
    assert_eq!(
        workers
            .into_iter()
            .filter_map(|w| w.join().unwrap().then_some(()))
            .count(),
        1
    );
}
#[test]
fn malformed_or_symlinked_handle_never_becomes_a_proposal() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("handle.json");
    let mut malformed = handle();
    malformed.attempt = "../host".into();
    save_new(&path, &malformed).unwrap();
    assert!(load_handle(&path).is_err());
    let link = dir.path().join("link.json");
    std::os::unix::fs::symlink(&path, &link).unwrap();
    assert!(load_handle(&link).is_err());
}
