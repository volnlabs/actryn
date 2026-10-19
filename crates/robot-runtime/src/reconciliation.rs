use crate::*;

pub(crate) fn record(
    registry: &Registry,
    namespace: &Namespace,
    active: &mut Active,
    status: &Status,
) -> Result<()> {
    // Status.instance is the current owner: grant revocation clears it before
    // the QUIESCED receipt. The immutable instance still comes from Active.id
    // and is compared to the full stored operation by Registry::reconcile.
    let instance_matches = status.instance == active.id.instance
        || (status.instance == 0
            && status.state == 1
            && status.reason == 3
            && status.flags & 8 == 0);
    if status.state >= 4
        || status.operation_state != 4
        || !instance_matches
        || !bridge::matches(status, &active.id)
    {
        return Ok(());
    }
    // A stopped/failed writer cannot establish a new durable fact. Cleanup may
    // still finish, leaving the unresolved historical record charged.
    if registry.health().fault.is_some() {
        return Ok(());
    }
    let value = registry
        .query(namespace.id(), active.key)
        .ok_or(Error::Denied("operation key missing"))?;
    if !matches!(
        value.phase,
        robot_intent::Phase::Submitted
            | robot_intent::Phase::Completed
            | robot_intent::Phase::CancelPending
            | robot_intent::Phase::CancelledDurable
    ) {
        return Ok(());
    }
    registry.reconcile(namespace, active.key, &active.id)?;
    active.reconciled = true;
    if matches!(
        value.phase,
        robot_intent::Phase::CancelPending | robot_intent::Phase::CancelledDurable
    ) {
        active.verdict = Verdict::Cancelled;
    }
    Ok(())
}

pub(crate) fn stop_if_closed(
    registry: &Registry,
    namespace: &Namespace,
    active: Option<&mut Active>,
    status: &Status,
    stop: &AtomicBool,
) -> Result<()> {
    if status.state >= 4 || status.operation == 0 || status.operation_state == 4 {
        if let Some(active) = active {
            record(registry, namespace, active, status)?;
        }
        // Publication of the stop signal follows queueing the proof. Writer::run
        // performs its final flush; the owner joins it before reclaiming the slot.
        stop.store(true, Ordering::Release);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Authority;
    impl robot_intent::Authority for Authority {
        fn allocate(
            &self,
            intent: &Intent,
        ) -> std::result::Result<OperationId, robot_intent::AuthorityError> {
            Ok(OperationId {
                device: [1; 16],
                boot: 1,
                session: 1,
                runtime_nonce: [2; 16],
                grant: intent.grant,
                instance: intent.instance,
                operation: 1,
                stream: 1,
            })
        }
        fn submit(
            &self,
            _: &OperationId,
            _: &Intent,
        ) -> std::result::Result<(), robot_intent::AuthorityError> {
            Ok(())
        }
        fn close(
            &self,
            _: &OperationId,
        ) -> std::result::Result<robot_intent::CloseAck, robot_intent::AuthorityError> {
            Ok(robot_intent::CloseAck::LocallyClosed { transition: 1 })
        }
    }

    #[test]
    fn retiring_writer_flushes_matched_cancellation_proof_before_exit() {
        for variant in 0..8 {
            let dir = tempfile::tempdir().unwrap();
            let path = dir.path().join("intent.sqlite");
            let (registry, mut writer) = Registry::open(
                &path,
                [2; 16],
                robot_intent::Limits::default(),
                Arc::new(Authority),
            )
            .unwrap();
            let ns = registry.prepare_namespace([3; 16], [4; 16]).unwrap();
            writer.flush().unwrap();
            let intent = Intent {
                digest: [5; 32],
                configuration_digest: [6; 32],
                instance: 1,
                grant: 1,
                context_revision: 1,
                deadline_ns: 1_000_000,
                observation: 1,
                payload: vec![],
            };
            let id = registry
                .propose(&ns, [7; 32], intent)
                .unwrap()
                .operation
                .unwrap();
            writer.flush().unwrap();
            registry.retire_namespace(&ns).unwrap();
            let mut active = Active {
                key: [7; 32],
                id,
                step: Step::new(
                    [0, 0],
                    Target {
                        left_ticks: 1,
                        right_ticks: 1,
                        duration_ms: 1000,
                    },
                    1_000_000,
                )
                .unwrap(),
                deadline: 1_000_000,
                verdict: Verdict::Pending,
                reconciled: false,
                last_sample_ns: 0,
                last_sequence: 0,
            };
            let mut status = Status {
                state: 1,
                operation_state: 4,
                device_identity: id.device,
                runtime_nonce: id.runtime_nonce,
                controller_boot: id.boot,
                controller_session: id.session,
                grant: id.grant,
                operation: id.operation,
                stream: id.stream,
                reason: 3, // GRANT_REVOKED: the kernel clears the active instance.
                ..Status::default()
            };
            match variant {
                1 => status.state = 4,
                2 => status.stream += 1,
                3 => status.operation_state = 3,
                4 => status.instance = id.instance + 1,
                5 => status.reason = 0,
                6 => {
                    status.state = 2;
                    status.instance = id.instance;
                    status.reason = 2;
                }
                7 => status.flags = 8,
                _ => (),
            }
            let stop = Arc::new(AtomicBool::new(false));
            stop_if_closed(&registry, &ns, Some(&mut active), &status, &stop).unwrap();
            assert_eq!(stop.load(Ordering::Acquire), variant != 3);
            if variant == 3 {
                continue;
            }
            assert!(!registry
                .query(ns.id(), [7; 32])
                .unwrap()
                .reconciled_durable());
            writer.run(stop, Duration::from_millis(1)).unwrap();
            let record = robot_intent::inspect(
                &path,
                [3; 16],
                [4; 16],
                [7; 32],
                robot_intent::Limits::default(),
            )
            .unwrap()
            .snapshot
            .unwrap();
            assert_eq!(record.reconciled_durable(), matches!(variant, 0 | 6));
            assert_eq!(record.phase, robot_intent::Phase::CancelledDurable);
            assert_eq!(record.operation, Some(id));
        }
    }

    #[test]
    fn historical_completed_inspection_and_cancel_keep_proof_without_inventing_verdict() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("intent.sqlite");
        let (registry, mut writer) = Registry::open(
            &path,
            [2; 16],
            robot_intent::Limits::default(),
            Arc::new(Authority),
        )
        .unwrap();
        let ns = registry.prepare_namespace([3; 16], [4; 16]).unwrap();
        writer.flush().unwrap();
        bindings::persist(
            dir.path(),
            &Prepared {
                binding: Binding {
                    principal: [8; 32],
                    attempt: [3; 16],
                    namespace: [4; 16],
                    session_deadline_ns: 1_000_000,
                },
                instance: 1,
                configuration_digest: configuration_digest(),
                runtime_epoch: [2; 16],
            },
        )
        .unwrap();
        let intent = Intent {
            digest: [5; 32],
            configuration_digest: configuration_digest(),
            instance: 1,
            grant: 1,
            context_revision: 1,
            deadline_ns: 1_000_000,
            observation: 1,
            payload: vec![],
        };
        registry.propose(&ns, [7; 32], intent).unwrap();
        writer.flush().unwrap();
        registry.complete(&ns, [7; 32]).unwrap();
        writer.flush().unwrap();
        let cancelled = Snapshot::from_registry(
            registry.cancel(&ns, [7; 32]).unwrap(),
            Verdict::OutcomeUnknown,
        );
        assert!(cancelled.reconciled);
        assert_eq!(cancelled.verdict, Verdict::OutcomeUnknown);
        registry.retire_namespace(&ns).unwrap();
        writer
            .run(Arc::new(AtomicBool::new(true)), Duration::from_millis(1))
            .unwrap();
        drop(registry);
        let before = fs::read(&path).unwrap();
        let historical = Engine::inspect(dir.path(), [8; 32], [3; 16], [4; 16], [7; 32]).unwrap();
        assert!(!historical.live_authority);
        let historical = historical.snapshot.unwrap();
        assert!(historical.reconciled);
        assert_eq!(historical.verdict, Verdict::OutcomeUnknown);
        assert_eq!(historical.operation, cancelled.operation);
        assert_eq!(historical.revision, cancelled.revision);
        assert_eq!(fs::read(&path).unwrap(), before);
    }
}
