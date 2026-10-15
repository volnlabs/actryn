//! Historical lookup must authenticate retained metadata before touching SQLite.
//! These tests use no kernel handle, network session or authority substitute.
use robot_runtime::{configuration_digest, Binding, Engine, Error, Prepared};
use std::{fs, os::unix::fs::PermissionsExt, path::Path};

fn fixture(root: &Path) {
    fs::set_permissions(root, fs::Permissions::from_mode(0o700)).unwrap();
    let prepared = Prepared {
        binding: Binding {
            principal: [1; 32],
            attempt: [2; 16],
            namespace: [3; 16],
            session_deadline_ns: 99,
        },
        instance: 1,
        configuration_digest: configuration_digest(),
        runtime_epoch: [4; 16],
    };
    let artifact = root.join(format!("binding-{}.json", "03".repeat(16)));
    fs::write(
        &artifact,
        serde_json::to_vec(&serde_json::json!({"version":1,"prepared":prepared})).unwrap(),
    )
    .unwrap();
    fs::set_permissions(artifact, fs::Permissions::from_mode(0o600)).unwrap();
    // Corrupt storage is deliberate: reaching SQLite must produce a different
    // error from failing the immutable principal/attempt binding.
    fs::write(root.join("intent.sqlite"), b"not a SQLite intent store").unwrap();
}

#[test]
fn wrong_principal_or_attempt_is_denied_before_history_storage() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    let original = fs::read(dir.path().join("intent.sqlite")).unwrap();
    for (principal, attempt) in [([9; 32], [2; 16]), ([1; 32], [9; 16])] {
        let result = Engine::inspect(dir.path(), principal, attempt, [3; 16], [5; 32]);
        assert!(
            matches!(
                result,
                Err(Error::Denied("retained immutable binding mismatch"))
            ),
            "{result:?}"
        );
    }
    let authorized = Engine::inspect(dir.path(), [1; 32], [2; 16], [3; 16], [5; 32]);
    assert!(
        matches!(authorized, Err(Error::Intent(_))),
        "authorized lookup must reach the deliberately corrupt SQLite store: {authorized:?}"
    );
    assert_eq!(
        fs::read(dir.path().join("intent.sqlite")).unwrap(),
        original
    );
}

#[test]
fn unavailable_binding_metadata_is_not_an_absent_key() {
    let dir = tempfile::tempdir().unwrap();
    fixture(dir.path());
    let result = Engine::inspect(dir.path(), [1; 32], [2; 16], [8; 16], [5; 32]);
    assert!(matches!(result, Err(Error::Io(_))), "{result:?}");
}
