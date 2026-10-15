use actryn_server::observer::{ObserverStatus, REQUIRED_COVERAGE};
#[test]
fn collector_readiness_requires_full_coverage_and_stable_epoch() {
    let good = ObserverStatus {
        ready: true,
        collector_epoch: "epoch1".into(),
        coverage: REQUIRED_COVERAGE.iter().map(|s| s.to_string()).collect(),
        sequence: 12,
        lost: 0,
    };
    good.check(None).unwrap();
    good.check(Some("epoch1")).unwrap();
    assert!(good.check(Some("previous")).is_err());
    let mut missing = good.clone();
    missing.coverage.pop();
    assert!(missing.check(None).is_err());
    let mut lost = good.clone();
    lost.lost = 1;
    assert!(lost.check(None).is_err());
    let mut notready = good;
    notready.ready = false;
    assert!(notready.check(None).is_err());
}
