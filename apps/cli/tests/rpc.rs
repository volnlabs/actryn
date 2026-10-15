use actryn_cli::rpc;
use robot_rpc::{read_message, wire, write_message};
use wire::request::Command;
fn request(command: Command) -> wire::Request {
    wire::Request {
        version: 1,
        request_id: vec![1; 16],
        robot_epoch: vec![2; 16],
        command: Some(command),
    }
}
#[tokio::test]
async fn lost_or_mismatched_mutation_reply_stays_unknown_without_resend() {
    for mismatch in [false, true] {
        let (mut client, mut server) = tokio::io::duplex(65536);
        let req = request(Command::Rearm(wire::Empty {}));
        let worker = tokio::spawn(async move {
            let r: wire::Request = read_message(&mut server).await.unwrap();
            assert!(matches!(r.command, Some(Command::Rearm(_))));
            if mismatch {
                write_message(
                    &mut server,
                    &wire::Response {
                        version: 1,
                        request_id: vec![9; 16],
                        robot_epoch: vec![2; 16],
                        result: Some(wire::response::Result::Report(wire::Report {
                            json: b"{}".to_vec(),
                        })),
                    },
                )
                .await
                .unwrap();
            }
        });
        let result = rpc::exchange(&mut client, &req).await.unwrap_err();
        assert!(result.outcome_unknown);
        worker.await.unwrap();
    }
}
#[tokio::test]
async fn readonly_failure_and_invalid_request_never_claim_mutation() {
    let (mut client, server) = tokio::io::duplex(65536);
    drop(server);
    assert!(
        !rpc::exchange(&mut client, &request(Command::Describe(wire::Empty {})))
            .await
            .unwrap_err()
            .outcome_unknown
    );
    let mut invalid = request(Command::Grant(wire::Grant { duration_ms: 60001 }));
    invalid.request_id.clear();
    assert!(
        !rpc::exchange(&mut client, &invalid)
            .await
            .unwrap_err()
            .outcome_unknown
    );
}
#[test]
fn native_reply_must_match_requested_operation_and_identity() {
    use actryn_server::{
        protocol::{Request, Response},
        Attempt, Inspection,
    };
    let id = "11".repeat(16);
    let inspection = || Inspection {
        attempt: Attempt {
            id: id.clone(),
            artifact_digest: format!("sha256:{}", "22".repeat(32)),
            state: "active".into(),
            deadline_ms: 1,
            binding: None,
            outcome: "pending".into(),
        },
        calls: vec![],
        evidence_gaps: vec![],
        denials: vec![],
        denials_omitted: 0,
        robot_binding: None,
        robot_requests: vec![],
    };
    let response = Response::Ok {
        inspection: inspection(),
    };
    assert!(rpc::validate_server_response(
        &Request::Start {
            attempt_id: id.clone()
        },
        &response
    )
    .is_ok());
    assert!(rpc::validate_server_response(
        &Request::Start {
            attempt_id: "33".repeat(16)
        },
        &response
    )
    .is_err());
    assert!(rpc::validate_server_response(
        &Request::Export {
            attempt_id: id.clone()
        },
        &response
    )
    .is_err());
    assert!(rpc::validate_server_response(
        &Request::Prepare {
            artifact_digest: format!("sha256:{}", "44".repeat(32))
        },
        &response
    )
    .is_err());
}
