use actryn_server::model::{decode_completed, request_body, ModelInput};
use serde_json::json;
#[test]
fn model_request_has_fixed_destination_policy_and_finite_output() {
    let input = ModelInput {
        goal: "index forward".into(),
        observation_id: "obs1".into(),
    };
    let body = request_body(&input).unwrap();
    assert_eq!(body["model"], "gpt-5.4-mini-2026-03-17");
    assert_eq!(body["max_output_tokens"], 1024);
    assert_eq!(body["tools"], json!([]));
    assert_eq!(body["store"], false);
    assert!(request_body(&ModelInput {
        goal: "x".repeat(4097),
        observation_id: "obs1".into()
    })
    .is_err());
}
#[test]
fn invalid_incomplete_and_out_of_bounds_proposals_never_publish() {
    let mut response = json!({"model":"gpt-5.4-mini-2026-03-17","status":"completed","usage":{"output_tokens":20},
        "output":[{"type":"message","content":[{"type":"output_text","text":"{\"left_delta_ticks\":10,\"right_delta_ticks\":10,\"duration_ms\":1000}"}]}]});
    let result = decode_completed(&response).unwrap();
    assert_eq!(result.0.left_delta_ticks, 10);
    assert_eq!(result.1, 20);
    response["status"] = json!("incomplete");
    assert!(decode_completed(&response).is_err());
    response["status"] = json!("completed");
    response["output"][0]["content"][0]["text"] =
        json!("{\"left_delta_ticks\":101,\"right_delta_ticks\":10,\"duration_ms\":1000}");
    assert!(decode_completed(&response).is_err());
    response["usage"]["output_tokens"] = json!(1025);
    assert!(decode_completed(&response).is_err());
}
