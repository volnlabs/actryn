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

#[tokio::test]
async fn export_rejects_untrusted_destination_ancestors_before_loading_a_handle() {
    use std::{
        fs,
        os::unix::fs::{symlink, PermissionsExt},
    };
    let root = tempfile::tempdir().unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let unsafe_parent = root.path().join("unsafe");
    fs::create_dir(&unsafe_parent).unwrap();
    fs::set_permissions(&unsafe_parent, fs::Permissions::from_mode(0o777)).unwrap();
    let private_child = unsafe_parent.join("private");
    fs::create_dir(&private_child).unwrap();
    fs::set_permissions(&private_child, fs::Permissions::from_mode(0o700)).unwrap();
    let link = root.path().join("alias");
    symlink(&private_child, &link).unwrap();
    for parent in [&unsafe_parent, &private_child, &link] {
        let out = parent.join("export");
        let error = run(args(&[
            "robot",
            "export",
            "--local",
            "--handle",
            "/missing-handle-must-not-open",
            "--out",
            out.to_str().unwrap(),
        ]))
        .await
        .unwrap_err();
        assert!(error.to_string().contains("protected"), "{error:?}");
        assert!(!out.exists());
    }
}

#[tokio::test]
async fn offline_artifact_routes_reject_unknown_flags_and_invalid_digests_before_storage() {
    for values in [
        vec![
            "server",
            "import",
            "--layout",
            "/missing-layout",
            "--digest",
            "bad",
            "--unexpected",
            "value",
        ],
        vec![
            "server",
            "discard-incomplete",
            "--digest",
            "bad",
            "--unexpected",
            "value",
        ],
    ] {
        let error = run(args(&values)).await.unwrap_err();
        assert!(
            error.to_string().contains("unsupported option"),
            "{error:?}"
        );
    }
    for values in [
        vec![
            "server",
            "import",
            "--layout",
            "/missing-layout",
            "--digest",
            "bad",
        ],
        vec!["server", "discard-incomplete", "--digest", "bad"],
    ] {
        let error = run(args(&values)).await.unwrap_err();
        assert!(error.to_string().contains("artifact digest"), "{error:?}");
    }
}
