use rcgen::{
    BasicConstraints, CertificateParams, ExtendedKeyUsagePurpose, IsCa, Issuer, KeyPair,
    KeyUsagePurpose,
};
use robot_rpc::*;
use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_rustls::{TlsAcceptor, TlsConnector};
struct Pki {
    ca: String,
    server: String,
    server_key: String,
    client: String,
    client_key: String,
    client_der: Vec<u8>,
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
        params.not_before = SystemTime::now().into();
        params.not_after = params.not_before + std::time::Duration::from_secs(600);
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
        client_der: client.der().to_vec(),
    }
}
#[tokio::test]
async fn actual_mutual_tls_authenticates_original_peer_and_keeps_expiry_fixed() {
    let p = pki();
    let server = server_tls(
        p.ca.as_bytes(),
        p.server.as_bytes(),
        p.server_key.as_bytes(),
    )
    .unwrap();
    assert_eq!(server.max_early_data_size, 0);
    assert_eq!(server.send_tls13_tickets, 0);
    let client = client_tls(
        p.ca.as_bytes(),
        p.client.as_bytes(),
        p.client_key.as_bytes(),
    )
    .unwrap();
    let (s, c) = tokio::io::duplex(65536);
    let (s, c) = tokio::join!(
        TlsAcceptor::from(server).accept(s),
        TlsConnector::from(client).connect("robot.test".try_into().unwrap(), c)
    );
    let mut s = s.unwrap();
    let mut c = c.unwrap();
    assert_eq!(s.get_ref().1.alpn_protocol(), Some(ALPN));
    assert_eq!(
        s.get_ref().1.peer_certificates().unwrap()[0].as_ref(),
        p.client_der
    );
    let mut policy = Policy::default();
    policy.certificates.insert(
        fingerprint(&p.client_der),
        PrincipalPolicy {
            principal: "attempt-one".into(),
            scopes: vec![Scope::Read, Scope::Propose],
        },
    );
    let wall = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos() as u64;
    let session = policy.authenticated(&p.client_der, wall, 1000).unwrap();
    assert_eq!(session.deadline_ns, 300_000_001_000);
    session.authorize(&policy, Scope::Propose, 2000).unwrap();
    assert!(session
        .authorize(&policy, Scope::Propose, session.deadline_ns)
        .is_err());
    policy.revoked.insert("attempt-one".into());
    assert!(session.authorize(&policy, Scope::Read, 2000).is_err());
    c.write_all(b"encrypted").await.unwrap();
    c.flush().await.unwrap();
    let mut bytes = [0; 9];
    s.read_exact(&mut bytes).await.unwrap();
    assert_eq!(&bytes, b"encrypted");
}
#[tokio::test]
async fn untrusted_client_chain_cannot_reach_rpc() {
    let p = pki();
    let alien = pki();
    let server = server_tls(
        p.ca.as_bytes(),
        p.server.as_bytes(),
        p.server_key.as_bytes(),
    )
    .unwrap();
    let client = client_tls(
        p.ca.as_bytes(),
        alien.client.as_bytes(),
        alien.client_key.as_bytes(),
    )
    .unwrap();
    let (s, c) = tokio::io::duplex(65536);
    let (s, _) = tokio::join!(
        TlsAcceptor::from(server).accept(s),
        TlsConnector::from(client).connect("robot.test".try_into().unwrap(), c)
    );
    assert!(s.is_err());
}
#[tokio::test]
async fn no_client_certificate_cannot_reach_rpc() {
    let p = pki();
    let server = server_tls(
        p.ca.as_bytes(),
        p.server.as_bytes(),
        p.server_key.as_bytes(),
    )
    .unwrap();
    let mut roots = rustls::RootCertStore::empty();
    for cert in certificates(p.ca.as_bytes()).unwrap() {
        roots.add(cert).unwrap();
    }
    let mut client = rustls::ClientConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_protocol_versions(&[&rustls::version::TLS13])
    .unwrap()
    .with_root_certificates(roots)
    .with_no_client_auth();
    client.alpn_protocols = vec![ALPN.to_vec()];
    let (s, c) = tokio::io::duplex(65536);
    let (s, _) = tokio::join!(
        TlsAcceptor::from(server).accept(s),
        TlsConnector::from(Arc::new(client)).connect("robot.test".try_into().unwrap(), c)
    );
    assert!(s.is_err());
}

fn proposal_request() -> wire::Request {
    wire::Request {
        version: VERSION,
        request_id: vec![1; 16],
        robot_epoch: vec![2; 16],
        command: Some(wire::request::Command::Propose(wire::Proposal {
            handle: Some(wire::Handle {
                attempt: vec![3; 16],
                namespace: vec![4; 16],
                key: vec![5; 32],
            }),
            observation_id: 1,
            parent_digest: vec![6; 32],
            target: Some(wire::Target {
                left_delta_ticks: 1,
                right_delta_ticks: -1,
                duration_ms: 1000,
            }),
        })),
    }
}

#[tokio::test]
async fn prepared_rpc_sends_no_application_bytes_until_consuming_publication() {
    use sha2::{Digest, Sha256};
    use std::time::Duration;
    for publish in [false, true] {
        let p = pki();
        let server = server_tls(
            p.ca.as_bytes(),
            p.server.as_bytes(),
            p.server_key.as_bytes(),
        )
        .unwrap();
        let client = client_tls(
            p.ca.as_bytes(),
            p.client.as_bytes(),
            p.client_key.as_bytes(),
        )
        .unwrap();
        let pin: [u8; 32] =
            Sha256::digest(certificates(p.server.as_bytes()).unwrap()[0].as_ref()).into();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint = listener.local_addr().unwrap();
        let (ready, observed) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            let (socket, _) = listener.accept().await.unwrap();
            let mut tls = TlsAcceptor::from(server).accept(socket).await.unwrap();
            let mut first = [0];
            assert!(
                tokio::time::timeout(Duration::from_millis(50), tls.read(&mut first))
                    .await
                    .is_err()
            );
            ready.send(()).unwrap();
            if publish {
                let request: wire::Request = read_message(&mut tls).await.unwrap();
                assert_eq!(request, proposal_request());
                write_message(
                    &mut tls,
                    &wire::Response {
                        version: VERSION,
                        request_id: request.request_id,
                        robot_epoch: request.robot_epoch,
                        result: Some(wire::response::Result::Report(wire::Report {
                            json: b"{}".to_vec(),
                        })),
                    },
                )
                .await
                .unwrap();
            } else {
                // Dropping a prepared request after closure never flushes its ciphertext.
                let result = tls.read(&mut first).await;
                assert!(matches!(result, Ok(0) | Err(_)));
            }
        });
        let prepared = PreparedRpc::connect(
            endpoint,
            "robot.test".into(),
            client,
            pin,
            &proposal_request(),
        )
        .await
        .unwrap();
        observed.await.unwrap();
        if publish {
            let sent = prepared.try_send_once().unwrap();
            let reply = sent.read_response().await.unwrap();
            assert_eq!(reply.request_id, vec![1; 16]);
        } else {
            drop(prepared);
        }
        tokio::time::timeout(Duration::from_secs(2), server)
            .await
            .unwrap()
            .unwrap();
    }
}

#[tokio::test]
async fn prepared_rpc_checks_peer_before_publication_and_rejects_lost_or_stale_reply() {
    use sha2::{Digest, Sha256};
    use std::time::Duration;
    for case in ["pin", "dns", "lost", "epoch", "correlation"] {
        let p = pki();
        let server = server_tls(
            p.ca.as_bytes(),
            p.server.as_bytes(),
            p.server_key.as_bytes(),
        )
        .unwrap();
        let client = client_tls(
            p.ca.as_bytes(),
            p.client.as_bytes(),
            p.client_key.as_bytes(),
        )
        .unwrap();
        let pin: [u8; 32] =
            Sha256::digest(certificates(p.server.as_bytes()).unwrap()[0].as_ref()).into();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (socket, _) = listener.accept().await.unwrap();
            let tls = TlsAcceptor::from(server).accept(socket).await;
            if case == "dns" {
                assert!(tls.is_err());
                return;
            }
            let mut tls = tls.unwrap();
            if case == "pin" {
                let mut first = [0];
                assert!(matches!(tls.read(&mut first).await, Ok(0) | Err(_)));
                return;
            }
            let request: wire::Request = read_message(&mut tls).await.unwrap();
            assert_eq!(request, proposal_request());
            if case != "lost" {
                write_message(
                    &mut tls,
                    &wire::Response {
                        version: VERSION,
                        request_id: if case == "correlation" {
                            vec![8; 16]
                        } else {
                            request.request_id
                        },
                        robot_epoch: if case == "epoch" {
                            vec![9; 16]
                        } else {
                            request.robot_epoch
                        },
                        result: Some(wire::response::Result::Report(wire::Report {
                            json: b"{}".to_vec(),
                        })),
                    },
                )
                .await
                .unwrap();
            }
            // A failed response closes this connection; no second mutation is sent.
        });
        let prepared = PreparedRpc::connect(
            endpoint,
            if case == "dns" {
                "wrong.test"
            } else {
                "robot.test"
            }
            .into(),
            client,
            if case == "pin" { [0; 32] } else { pin },
            &proposal_request(),
        )
        .await;
        if matches!(case, "pin" | "dns") {
            assert!(prepared.is_err());
        } else {
            assert!(prepared
                .unwrap()
                .try_send_once()
                .unwrap()
                .read_response()
                .await
                .is_err());
        }
        tokio::time::timeout(Duration::from_secs(2), server)
            .await
            .unwrap()
            .unwrap();
    }
}
