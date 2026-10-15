use actryn_cli::command::run;
fn args(values: &[&str]) -> Vec<String> {
    values.iter().map(|v| (*v).into()).collect()
}
#[tokio::test]
async fn help_is_finite_json_without_connecting_to_services() {
    let help = run(args(&["--help"])).await.unwrap();
    assert_eq!(help["result"], "help");
    assert!(serde_json::to_vec(&help).unwrap().len() < 16384);
}
#[tokio::test]
async fn invalid_mutations_fail_before_transport_or_state_change() {
    let epoch = "1".repeat(32);
    let error = run(args(&[
        "robot",
        "grant",
        "--epoch",
        &epoch,
        "--duration-ms",
        "60001",
    ]))
    .await
    .unwrap_err();
    assert!(error.to_string().contains("grant duration"));
    let error = run(args(&["robot", "rearm"])).await.unwrap_err();
    assert!(error.to_string().contains("epoch"));
    assert!(run(args(&["server", "prepare", "--artifact", "bad"]))
        .await
        .is_err());
    assert!(
        run(args(&["robot", "status", "--url", "http://example.test"]))
            .await
            .is_err()
    );
    assert!(run(args(&[
        "robot", "rearm", "--epoch", &epoch, "--epoch", &epoch
    ]))
    .await
    .is_err());
}
