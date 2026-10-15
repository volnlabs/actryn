use actryn_server::launcher::{Artifact, LauncherConfig};
#[test]
fn administrator_registry_rejects_writable_rootfs_and_unsafe_argv() {
    let dir = tempfile::tempdir().unwrap();
    let artifact = Artifact {
        rootfs: dir.path().to_path_buf(),
        argv: vec!["relative-program".into()],
    };
    assert!(artifact.validate().is_err());
    let artifact = Artifact {
        rootfs: dir.path().to_path_buf(),
        argv: vec!["/bin/agent".into()],
    };
    assert!(artifact.validate().is_err()); // tempfile belongs to unprivileged test identity.
    let invalid = r#"{"server_uid":1000,"operator_uid":1000,"io_device":"../host","artifacts":{},"extra_runtime_options":[]}"#;
    assert!(serde_json::from_str::<LauncherConfig>(invalid).is_err());
}

#[test]
fn duplicate_service_lifetime_cannot_take_existing_store() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("service.lock");
    let first = actryn_server::launcher::lock_service(&path).unwrap();
    assert!(actryn_server::launcher::lock_service(&path).is_err());
    drop(first);
    assert!(actryn_server::launcher::lock_service(&path).is_ok());
}
#[test]
fn offline_artifact_never_enables_live_or_unknown_tools() {
    assert!(
        actryn_server::artifact::methods_for_profile("offline-preview-v1")
            .unwrap()
            .contains(&"model.offline")
    );
    assert!(
        !actryn_server::artifact::methods_for_profile("offline-preview-v1")
            .unwrap()
            .contains(&"model.propose")
    );
    assert!(actryn_server::artifact::methods_for_profile("caller-selected").is_err());
}
#[test]
fn live_profile_is_explicit_and_pins_the_model_request_policy() {
    let methods = actryn_server::artifact::methods_for_profile("live-preview-v1").unwrap();
    assert!(methods.contains(&"model.propose") && !methods.contains(&"model.offline"));
    let config = actryn_server::artifact::image_configuration("live-preview-v1").unwrap();
    assert_eq!(
        config["Labels"]["org.actryn.model"],
        actryn_server::model::MODEL
    );
    assert_eq!(
        config["Labels"]["org.actryn.model-policy"],
        actryn_server::model::policy_digest().unwrap()
    );
    assert_ne!(
        config,
        actryn_server::artifact::image_configuration("offline-preview-v1").unwrap()
    );
}
