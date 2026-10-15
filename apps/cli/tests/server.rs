use actryn_cli::rpc::{server_mutation, server_socket, validate_server_response};
use actryn_server::protocol::{Request, Response, CLOSURE_SOCKET};
use serde_json::json;

#[test]
fn cancellation_has_reserved_transport_and_uncertain_mutation_semantics() {
    let attempt_id = "11".repeat(16);
    for request in [
        Request::Stop {
            attempt_id: attempt_id.clone(),
        },
        Request::RobotCancel {
            attempt_id: attempt_id.clone(),
            request_key: "agent-call".into(),
        },
    ] {
        assert_eq!(server_socket(&request), CLOSURE_SOCKET);
        assert!(server_mutation(&request));
    }
    let query = Request::RobotQuery {
        attempt_id: attempt_id.clone(),
        request_key: "agent-call".into(),
    };
    assert_eq!(
        server_socket(&query),
        actryn_server::launcher::SERVER_SOCKET
    );
    assert!(!server_mutation(&query));
    assert!(server_mutation(&Request::BindRobot {
        attempt_id,
        namespace: "22".repeat(16)
    }));
}

#[test]
fn delegation_replies_cannot_substitute_attempt_namespace_or_agent_key() {
    let attempt = "11".repeat(16);
    let namespace = "22".repeat(16);
    let bind = Request::BindRobot {
        attempt_id: attempt.clone(),
        namespace: namespace.clone(),
    };
    let mut binding = json!({"result":"robot_binding","binding":{
        "attempt_id":attempt,"namespace":namespace,"principal":"preview",
        "peer_digest":format!("sha256:{}", "33".repeat(32)),
        "client_certificate_sha256":"44".repeat(32),"robot_epoch":"55".repeat(16),
        "robot_configuration_digest":"66".repeat(32),"robot_profile_digest":"77".repeat(32),
        "created_ms":1,"deadline_ms":1000}});
    assert!(
        validate_server_response(&bind, &serde_json::from_value(binding.clone()).unwrap()).is_ok()
    );
    binding["binding"]["namespace"] = json!("88".repeat(16));
    assert!(validate_server_response(&bind, &serde_json::from_value(binding).unwrap()).is_err());

    let query = Request::RobotQuery {
        attempt_id: attempt.clone(),
        request_key: "agent-call".into(),
    };
    let value = json!({"result":"robot_result","request":{
        "request_key":"agent-call","request_digest":format!("sha256:{}", "99".repeat(32)),
        "handle":{"attempt":attempt,"namespace":namespace,"key":"aa".repeat(32)},
        "robot_epoch":"55".repeat(16),"phase":"reserved","cancellation_requested":false,
        "outstanding_debit":true,"deadline_ms":1000,"observation":null,
        "observation_digest":null,"parent_digest":null,"proposal_digest":null,"last_remote":null,
        "historical_response":false,"remote_unavailable":false}});
    let response: Response = serde_json::from_value(value.clone()).unwrap();
    assert!(validate_server_response(&query, &response).is_ok());
    for (field, replacement) in [("attempt", "bb".repeat(16)), ("key", "aa".repeat(31))] {
        let mut wrong = value.clone();
        wrong["request"]["handle"][field] = json!(replacement);
        assert!(validate_server_response(&query, &serde_json::from_value(wrong).unwrap()).is_err());
    }
    let mut wrong = value;
    wrong["request"]["request_key"] = json!("another-call");
    assert!(validate_server_response(&query, &serde_json::from_value(wrong).unwrap()).is_err());
}
