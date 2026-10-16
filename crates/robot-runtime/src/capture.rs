use crate::{configuration_digest, profile_digest, Binding, Error, Result};
use evidence::{CapturePolicy, CaptureSpec, EventKind, Origin, Producer, ProducerSpec, Recorder};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{path::Path, sync::Mutex};
pub(crate) struct Capture {
    pub recorder: Recorder,
    producers: [Producer; 2],
    sequences: Mutex<[u64; 2]>,
}
impl Capture {
    pub fn preparation_ready(&self) -> bool {
        let health = self.recorder.health();
        // The three preparation records precede activation and streamed observations.
        !health.revoke_required && health.frontiers[0].durable >= 3
    }
    pub fn create(
        path: &Path,
        binding: &Binding,
        epoch: [u8; 16],
    ) -> Result<(Self, evidence::Writer)> {
        let producers = [Origin::Runtime, Origin::Kernel]
            .into_iter()
            .enumerate()
            .map(|(i, origin)| {
                let mut h = Sha256::new();
                h.update(epoch);
                h.update(binding.attempt);
                h.update([i as u8]);
                let hash: [u8; 32] = h.finalize().into();
                ProducerSpec {
                    identity: hash[..16].try_into().unwrap(),
                    session: 1,
                    origin,
                    clock_domain: "robot CLOCK_BOOTTIME".into(),
                    clock_error_ns: 22_000_000,
                    requested: vec![
                        EventKind::Activation,
                        EventKind::Configuration,
                        EventKind::Execution,
                        EventKind::Intervention,
                        EventKind::Observation,
                        EventKind::Transition,
                        EventKind::SourceGap,
                    ],
                    required_for_replay: false,
                }
            })
            .collect();
        let (recorder, writer) = Recorder::create(
            path,
            CaptureSpec {
                attempt: binding.attempt,
                profile_digest: profile_digest(),
                configuration_digest: configuration_digest(),
                policy: CapturePolicy::MetadataOnly,
                retention: "local bounded software evidence".into(),
                redaction: "no model or sensor payload collection".into(),
                producers,
            },
            evidence::Limits::default(),
        )?;
        let result = Self {
            producers: [
                recorder
                    .producer(0)
                    .ok_or(Error::Denied("runtime producer missing"))?,
                recorder
                    .producer(1)
                    .ok_or(Error::Denied("kernel producer missing"))?,
            ],
            recorder,
            sequences: Mutex::new([0, 0]),
        };
        Ok((result, writer))
    }
    pub fn record(
        &self,
        producer: usize,
        time: u64,
        kind: EventKind,
        value: &impl Serialize,
    ) -> Result<()> {
        let bytes =
            serde_json::to_vec(value).map_err(|_| Error::Denied("metadata serialization"))?;
        if bytes.len() > 8192 {
            return Err(Error::Denied("metadata too large"));
        }
        let mut sequences = self.sequences.lock().unwrap();
        let next = sequences[producer]
            .checked_add(1)
            .ok_or(Error::Denied("capture sequence exhausted"))?;
        self.producers[producer].read_metadata(next, time, kind, &bytes)?;
        sequences[producer] = next;
        self.recorder.queue_read();
        Ok(())
    }
    /// Controller observations are derived by the manager from kernel receipts;
    /// their sequence is not an additional raw kernel event.
    pub fn record_observation(&self, time: u64, value: &impl Serialize) -> Result<()> {
        self.record(0, time, EventKind::Observation, value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn durable_preparation_can_be_ready_while_new_observations_are_queued() {
        let root = tempfile::tempdir().unwrap();
        let binding = Binding {
            principal: [1; 32],
            attempt: [2; 16],
            namespace: [3; 16],
            session_deadline_ns: 1000,
        };
        let (capture, mut writer) =
            Capture::create(&root.path().join("capture"), &binding, [4; 16]).unwrap();
        for n in 0..3 {
            capture.record(0, n, EventKind::Configuration, &n).unwrap();
        }
        assert!(!capture.preparation_ready());
        writer.flush().unwrap();
        capture.record_observation(4, &"fresh observation").unwrap();
        assert_eq!(capture.recorder.health().pending_records, 1);
        assert_eq!(capture.recorder.health().frontiers[0].read, 4);
        assert_eq!(capture.recorder.health().frontiers[1].read, 0);
        assert!(capture.preparation_ready());
    }

    #[test]
    fn exhausted_fault_reserve_does_not_replace_the_authority_closing_error() {
        let root = tempfile::tempdir().unwrap();
        let producers = [Origin::Runtime, Origin::Kernel]
            .into_iter()
            .enumerate()
            .map(|(index, origin)| ProducerSpec {
                identity: [index as u8 + 1; 16],
                session: 1,
                origin,
                clock_domain: "test CLOCK_BOOTTIME".into(),
                clock_error_ns: 0,
                requested: vec![EventKind::Transition, EventKind::SourceGap],
                required_for_replay: false,
            })
            .collect();
        let (recorder, _writer) = Recorder::create(
            root.path().join("capture"),
            CaptureSpec {
                attempt: [2; 16],
                profile_digest: [3; 32],
                configuration_digest: [4; 32],
                policy: CapturePolicy::MetadataOnly,
                retention: "test".into(),
                redaction: "test".into(),
                producers,
            },
            evidence::Limits {
                volatile_records: 2,
                reserved_records: 1,
                ..Default::default()
            },
        )
        .unwrap();
        let capture = Capture {
            producers: [recorder.producer(0).unwrap(), recorder.producer(1).unwrap()],
            recorder,
            sequences: Mutex::new([0, 0]),
        };
        let mut stream = crate::events::Continuity::new([2; 16], 0).unwrap();
        let mut event = authority_client::Event {
            sequence: 9,
            status: authority_client::Status {
                runtime_nonce: [2; 16],
                ..Default::default()
            },
            ..Default::default()
        };
        stream.capture_event(&event, Some(&capture), true).unwrap();
        capture
            .record(0, 0, EventKind::Transition, &"reserve occupied")
            .unwrap();
        event.sequence = 11;
        assert!(matches!(
            stream.capture_event(&event, Some(&capture), true),
            Err(Error::Denied("kernel event source gap"))
        ));
        let health = capture.recorder.health();
        assert!(stream.faulted && health.revoke_required);
        assert_eq!(health.frontiers[1].gap_count, 1);
        assert_eq!(health.frontiers[1].read, 1);
        assert_eq!(health.pending_records, 2);
        assert!(health.issues.contains(&evidence::HealthIssue::SourceGap));
        assert!(health.issues.contains(&evidence::HealthIssue::Capacity));
    }
}
