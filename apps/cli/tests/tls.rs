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
