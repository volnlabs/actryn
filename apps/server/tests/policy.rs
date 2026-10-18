use actryn_server::policy::{fixed_spec, verify_snapshot, Snapshot};
use actryn_server::protocol::{decode_request, Request};

#[test]
fn fixed_profile_never_inherits_host_network_mounts_or_privileges() {
    let spec = fixed_spec(
        "/trusted/rootfs",
        "/trusted/broker",
        "/actryn/a",
        &["/bin/agent".into()],
    );
    assert_eq!(spec["root"]["readonly"], true);
    assert_eq!(spec["process"]["user"]["uid"], 65532);
    assert_eq!(spec["process"]["noNewPrivileges"], true);
    assert_eq!(
        spec["process"]["capabilities"]["bounding"]
            .as_array()
            .unwrap()
            .len(),
        0
    );
    assert!(spec.get("hooks").is_none());
    let namespaces = spec["linux"]["namespaces"].as_array().unwrap();
    assert!(namespaces
        .iter()
        .any(|n| n["type"] == "network" && n.get("path").is_none()));
    assert!(!spec["mounts"]
        .as_array()
        .unwrap()
        .iter()
        .any(|m| m["source"]
            .as_str()
            .is_some_and(|s| s.contains("containerd.sock"))));
    assert_eq!(spec["linux"]["resources"]["pids"]["limit"], 64);
}

fn snapshot() -> Snapshot {
    Snapshot {
        pid: 123,
        start_ticks: 12345,
        cgroup: "/actryn/a".into(),
        uid: 65532,
        gid: 65532,
        capabilities: 0,
        no_new_privileges: true,
        seccomp_mode: 2,
        private_namespaces: true,
        network_routes: 0,
        memory_max: 268435456,
        pids_max: 64,
        cpu_max: "50000 100000".into(),
        io_max: "8:0 rbps=1048576 wbps=1048576 riops=128 wiops=128".into(),
        device_programs: vec![7],
        device_programs_direct: vec![7],
        device_attach_flags: 2,
        unexpected_mounts: vec![],
        root_readonly: true,
    }
}
#[test]
fn verification_rejects_missing_controls_or_wrong_lifetime() {
    let good = snapshot();
    verify_snapshot(&good, 123, "/actryn/a", "8:0").unwrap();
    let variants: Vec<Snapshot> = vec![
        Snapshot {
            no_new_privileges: false,
            ..snapshot()
        },
        Snapshot {
            seccomp_mode: 0,
            ..snapshot()
        },
        Snapshot {
            capabilities: 1,
            ..snapshot()
        },
        Snapshot {
            uid: 0,
            ..snapshot()
        },
        Snapshot {
            private_namespaces: false,
            ..snapshot()
        },
        Snapshot {
            network_routes: 1,
            ..snapshot()
        },
        Snapshot {
            device_programs: vec![],
            ..snapshot()
        },
        Snapshot {
            device_programs_direct: vec![],
            ..snapshot()
        },
        Snapshot {
            device_attach_flags: 0,
            ..snapshot()
        },
        Snapshot {
            device_attach_flags: 1,
            ..snapshot()
        },
        Snapshot {
            device_programs: vec![0],
            ..snapshot()
        },
        Snapshot {
            unexpected_mounts: vec!["/host".into()],
            ..snapshot()
        },
        Snapshot {
            root_readonly: false,
            ..snapshot()
        },
        Snapshot {
            memory_max: 536870912,
            ..snapshot()
        },
        Snapshot {
            io_max: String::new(),
            ..snapshot()
        },
    ];
    for bad in variants {
        assert!(verify_snapshot(&bad, 123, "/actryn/a", "8:0").is_err());
    }
    assert!(verify_snapshot(&good, 124, "/actryn/a", "8:0").is_err());
    assert!(verify_snapshot(&good, 123, "/actryn/reused", "8:0").is_err());
}
#[test]
fn protocol_rejects_unknown_authority_fields_and_caller_paths() {
    assert!(
        decode_request(br#"{"op":"prepare","artifact_digest":"sha256:abc","rootfs":"/"}"#).is_err()
    );
    assert!(decode_request(br#"{"op":"start","attempt_id":"../../host"}"#).is_err());
    assert!(decode_request(br#"{"op":"export","attempt_id":"../../etc/shadow"}"#).is_err());
    let export = format!(r#"{{"op":"export","attempt_id":"{}"}}"#, "a".repeat(32));
    assert!(matches!(
        decode_request(export.as_bytes()).unwrap(),
        Request::Export { .. }
    ));
    let path_override = export.replace('}', r#", "path":"/etc/shadow"}"#);
    assert!(decode_request(path_override.as_bytes()).is_err());
    assert!(decode_request(&vec![b' '; 65537]).is_err());
    let bytes = format!(
        r#"{{"op":"prepare","artifact_digest":"sha256:{}"}}"#,
        "a".repeat(64)
    );
    assert!(matches!(
        decode_request(bytes.as_bytes()).unwrap(),
        Request::Prepare { .. }
    ));
}
