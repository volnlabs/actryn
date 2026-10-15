use authority_client::{AuthorityDevice, Opcode, Request, Role};

#[test]
#[ignore = "requires the bound Actryn authority module in the disposable ARM64 guest"]
fn actual_status_abi_and_malformed_request_rejection() {
    authority_client::deny_exec().unwrap();
    let device = AuthorityDevice::bind(Role::Admin).unwrap();
    let before = device.status().unwrap();
    let mut bad = Request::new(Opcode::Health);
    bad.reserved[0] = 1;
    assert_eq!(
        device.request(&mut bad).unwrap_err().raw_os_error(),
        Some(libc::EINVAL)
    );
    let after = device.status().unwrap();
    assert_eq!(before.state, after.state);
    assert_eq!(before.operation, after.operation);
    assert_eq!(before.runtime_nonce, after.runtime_nonce);
}
