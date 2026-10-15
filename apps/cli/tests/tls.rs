use actryn_cli::rpc;
use rcgen::{
    BasicConstraints, CertificateParams, ExtendedKeyUsagePurpose, IsCa, Issuer, KeyPair,
    KeyUsagePurpose,
};
struct Pki {
    ca: String,
    server: String,
    server_key: String,
    client: String,
    client_key: String,
    pin: String,
}
fn pki() -> Pki {
    let mut params = CertificateParams::default();
    params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
    params.key_usages = vec![
        KeyUsagePurpose::KeyCertSign,
        KeyUsagePurpose::DigitalSignature,
    ];
    let key = KeyPair::generate().unwrap();
    let ca = params.self_signed(&key).unwrap();
    let issuer = Issuer::new(params, key);
    let leaf = |purpose| {
        let mut params = CertificateParams::new(vec!["robot.test".into()]).unwrap();
        params.extended_key_usages = vec![purpose];
        let key = KeyPair::generate().unwrap();
        let cert = params.signed_by(&key, &issuer).unwrap();
        (cert, key.serialize_pem())
    };
    let (server, server_key) = leaf(ExtendedKeyUsagePurpose::ServerAuth);
    let (client, client_key) = leaf(ExtendedKeyUsagePurpose::ClientAuth);
    Pki {
        ca: ca.pem(),
        server: server.pem(),
        server_key,
        client: client.pem(),
        client_key,
        pin: robot_rpc::fingerprint(server.der()),
    }
}
#[tokio::test]
async fn actual_tls_requires_ca_dns_and_operator_leaf_pin_before_rpc() {
    let p = pki();
    let alien = pki();
    for mode in 0..4 {
        let server = robot_rpc::server_tls(
            p.ca.as_bytes(),
            p.server.as_bytes(),
            p.server_key.as_bytes(),
        )
        .unwrap();
        let ca = if mode == 3 { &alien.ca } else { &p.ca };
        let client =
            robot_rpc::client_tls(ca.as_bytes(), p.client.as_bytes(), p.client_key.as_bytes())
                .unwrap();
        let (s, c) = tokio::io::duplex(65536);
        let acceptor = tokio_rustls::TlsAcceptor::from(server);
        let bad_pin = "0".repeat(64);
        let pin = if mode == 1 { &bad_pin } else { &p.pin };
        let dns = if mode == 2 {
            "wrong.test"
        } else {
            "robot.test"
        };
        let (server, client) = tokio::join!(acceptor.accept(s), rpc::tls(c, dns, pin, client));
        if mode == 0 {
            let client = client.unwrap();
            assert_eq!(
                client.get_ref().1.protocol_version(),
                Some(rustls::ProtocolVersion::TLSv1_3)
            );
            assert_eq!(client.get_ref().1.alpn_protocol(), Some(robot_rpc::ALPN));
            assert!(server.is_ok());
        } else {
            assert!(client.is_err());
        }
    }
}

async fn epoch_case(command: robot_rpc::wire::request::Command, refresh: bool, lose_reply: bool) {
    use actryn_cli::state::Pair;
    use robot_rpc::wire::{self, request::Command, response::Result as Reply};
    use tokio::{io::AsyncReadExt, net::TcpListener};
    let p = pki();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let pair = Pair {
        schema: 1,
        endpoint: listener.local_addr().unwrap().to_string(),
        dns_name: "robot.test".into(),
        device_certificate_sha256: p.pin.clone(),
        ca_pem: p.ca.clone(),
        robot_epoch: "11".repeat(16),
    };
    let request = wire::Request {
        version: 1,
        request_id: vec![3; 16],
        robot_epoch: vec![0x11; 16],
        command: Some(command),
    };
    request.validate().unwrap();
    let mut expected = request.clone();
    if refresh {
        expected.robot_epoch = vec![0x22; 16];
    }
    let server = robot_rpc::server_tls(
        p.ca.as_bytes(),
        p.server.as_bytes(),
        p.server_key.as_bytes(),
    )
    .unwrap();
    let worker = tokio::spawn(async move {
        let (socket, _) = listener.accept().await.unwrap();
        let mut stream = tokio_rustls::TlsAcceptor::from(server)
            .accept(socket)
            .await
            .unwrap();
        let first: wire::Request = robot_rpc::read_message(&mut stream).await.unwrap();
        let actual = if refresh {
            assert!(
                matches!(first.command, Some(Command::Describe(_))),
                "retained request must refresh before sending: {first:?}"
            );
            assert!(first.robot_epoch.is_empty());
            assert_ne!(first.request_id, expected.request_id);
            robot_rpc::write_message(
                &mut stream,
                &wire::Response {
                    version: 1,
                    request_id: first.request_id,
                    robot_epoch: vec![0x22; 16],
                    result: Some(Reply::Report(wire::Report {
                        json: b"{}".to_vec(),
                    })),
                },
            )
            .await
            .unwrap();
            robot_rpc::read_message::<wire::Request>(&mut stream)
                .await
                .unwrap()
        } else {
            first
        };
        // Full equality checks immutable command/handle, lineage and correlation.
        assert_eq!(actual, expected);
        if lose_reply {
            return;
        }
        robot_rpc::write_message(
            &mut stream,
            &wire::Response {
                version: 1,
                request_id: actual.request_id,
                robot_epoch: vec![0x22; 16],
                result: Some(if refresh {
                    Reply::Report(wire::Report {
                        json: b"{}".to_vec(),
                    })
                } else {
                    Reply::Failure(wire::Failure {
                        code: wire::failure::Code::Rejected as i32,
                        message: "stale authority epoch".into(),
                    })
                }),
            },
        )
        .await
        .unwrap();
        // One socket, one original command; no automatic resend follows a reply.
        let mut byte = [0];
        assert!(matches!(stream.read(&mut byte).await, Ok(0) | Err(_)));
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(50), listener.accept())
                .await
                .is_err()
        );
    });
    let result = rpc::remote(
        &pair,
        p.client.as_bytes(),
        p.client_key.as_bytes(),
        &request,
    )
    .await;
    worker.await.unwrap();
    if lose_reply {
        assert!(result.unwrap_err().outcome_unknown);
    } else {
        assert!(result.is_ok(), "{result:?}");
    }
    assert_eq!(request.robot_epoch, vec![0x11; 16]);
    assert_eq!(pair.robot_epoch, "11".repeat(16));
}
fn retained_handle() -> robot_rpc::wire::Handle {
    robot_rpc::wire::Handle {
        namespace: vec![4; 16],
        attempt: vec![5; 16],
        key: vec![6; 32],
    }
}
#[tokio::test]
async fn retained_query_cancel_and_capture_refresh_epoch_on_the_same_pinned_tls_connection() {
    use robot_rpc::wire::{self, request::Command};
    for command in [
        Command::Query(retained_handle()),
        Command::Cancel(retained_handle()),
        Command::EvidenceRead(wire::EvidenceRead {
            handle: Some(retained_handle()),
            file: "checkpoints.sqlite".into(),
            offset: 12,
        }),
    ] {
        epoch_case(command, true, false).await;
    }
}
#[tokio::test]
async fn proposal_and_observation_keep_the_original_authority_epoch() {
    use robot_rpc::wire::{self, request::Command};
    epoch_case(
        Command::Propose(wire::Proposal {
            handle: Some(retained_handle()),
            observation_id: 7,
            target: Some(wire::Target {
                left_delta_ticks: 1,
                right_delta_ticks: -1,
                duration_ms: 1000,
            }),
            parent_digest: vec![8; 32],
        }),
        false,
        false,
    )
    .await;
    let mut handle = retained_handle();
    handle.key.clear();
    epoch_case(Command::Observe(handle), false, false).await;
}
#[tokio::test]
async fn lost_cancel_reply_after_refresh_remains_unknown_and_never_resends() {
    epoch_case(
        robot_rpc::wire::request::Command::Cancel(retained_handle()),
        true,
        true,
    )
    .await;
}
