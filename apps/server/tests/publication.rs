use actryn_server::broker::{BoundedOutput, PublicationGate};
#[test]
fn closed_context_cannot_publish_even_if_external_work_completes() {
    let gate = PublicationGate::default();
    let mut published = 0;
    gate.publish(|| {
        published += 1;
    })
    .unwrap();
    gate.close();
    assert!(gate
        .publish(|| {
            published += 1;
        })
        .is_err());
    assert_eq!(published, 1);
}
#[test]
fn bounded_stream_discards_overflow_and_never_recovers() {
    let mut output = BoundedOutput::new(4).unwrap();
    output.push(b"abc").unwrap();
    assert!(output.push(b"de").is_err());
    assert!(output.push(b"x").is_err());
    assert!(output.finish().is_err());
}
