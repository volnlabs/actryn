use crate::{Error, Result};
use authority_client::Event;
use serde::Serialize;

#[derive(Debug, Serialize)]
struct SourceFault {
    source: &'static str,
    epoch: [u8; 16],
    previous_sequence: Option<u64>,
    observed_sequence: u64,
    loss_baseline: u32,
    observed_loss: u32,
    sequence_discontinuity: bool,
    loss_counter_changed: bool,
}

#[derive(Serialize)]
struct FaultRecord<'a> {
    fault: &'a SourceFault,
    event: &'a Event,
}

/// A new explicit recovery starts a stream; cumulative historical loss is retained.
pub(crate) struct Continuity {
    pub epoch: [u8; 16],
    pub lost_baseline: u32,
    pub faulted: bool,
    sequence: Option<u64>,
    first_fault: Option<SourceFault>,
}
impl Continuity {
    pub fn capture_event(
        &mut self,
        event: &Event,
        capture: Option<&crate::capture::Capture>,
        record_normal: bool,
    ) -> Result<bool> {
        let was_faulted = self.faulted;
        let accepted = match self.accept(event) {
            Ok(accepted) => accepted,
            Err(error) => {
                if !was_faulted {
                    if let (Some(capture), Some(fault)) = (capture, &self.first_fault) {
                        // Bounded reserved memory only, never filesystem work.
                        // Keep the authority-closing result even if recording
                        // fails; the recorder independently latches SourceGap.
                        let _ = capture.record(
                            1,
                            event.captured_ns,
                            evidence::EventKind::SourceGap,
                            &FaultRecord { fault, event },
                        );
                    }
                }
                return Err(error);
            }
        };
        if accepted && record_normal {
            if let Some(capture) = capture.filter(|c| !c.recorder.health().revoke_required) {
                capture.record(1, event.captured_ns, evidence::EventKind::Transition, event)?;
            }
        }
        Ok(accepted)
    }
    pub fn new(epoch: [u8; 16], lost_baseline: u32) -> Result<Self> {
        if epoch == [0; 16] || lost_baseline == u32::MAX {
            return Err(Error::Denied("event identity/loss counter exhausted"));
        }
        Ok(Self {
            epoch,
            lost_baseline,
            faulted: false,
            sequence: None,
            first_fault: None,
        })
    }
    pub fn accept(&mut self, event: &Event) -> Result<bool> {
        if event.status.runtime_nonce != self.epoch {
            return Ok(false);
        }
        if self.faulted {
            return Err(Error::Denied("kernel event source gap"));
        }
        let sequence_discontinuity = event.sequence == 0
            || self
                .sequence
                .is_some_and(|last| last.checked_add(1) != Some(event.sequence));
        let loss_counter_changed = event.status.events_lost != self.lost_baseline;
        if sequence_discontinuity || loss_counter_changed {
            self.faulted = true;
            self.first_fault = Some(SourceFault {
                source: "kernel.event",
                epoch: self.epoch,
                previous_sequence: self.sequence,
                observed_sequence: event.sequence,
                loss_baseline: self.lost_baseline,
                observed_loss: event.status.events_lost,
                sequence_discontinuity,
                loss_counter_changed,
            });
            return Err(Error::Denied("kernel event source gap"));
        }
        self.sequence = Some(event.sequence);
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn event(epoch: [u8; 16], lost: u32, sequence: u64) -> Event {
        Event {
            sequence,
            status: authority_client::Status {
                runtime_nonce: epoch,
                events_lost: lost,
                ..Default::default()
            },
            ..Default::default()
        }
    }
    #[test]
    fn explicit_new_epoch_accepts_historical_loss_but_never_hides_new_loss() {
        let mut stream = Continuity::new([2; 16], 3862).unwrap();
        assert_eq!(stream.lost_baseline, 3862);
        assert!(!stream.accept(&event([1; 16], u32::MAX, u64::MAX)).unwrap());
        assert!(stream.accept(&event([2; 16], 3862, 500)).unwrap());
        assert!(stream.accept(&event([2; 16], 3862, 501)).unwrap());
        assert!(stream.accept(&event([2; 16], 3863, 502)).is_err());
        assert!(stream.accept(&event([2; 16], 3862, 502)).is_err());
        assert!(!stream.accept(&event([3; 16], 0, 1)).unwrap());
        assert!(stream.faulted);
        let mut recovery = Continuity::new([4; 16], 3863).unwrap();
        assert!(recovery.accept(&event([4; 16], 3864, 800)).is_err());
    }
    #[test]
    fn sequence_gap_saturation_and_wrap_require_explicit_recovery() {
        assert!(Continuity::new([1; 16], u32::MAX).is_err());
        assert!(Continuity::new([0; 16], 0).is_err());
        let mut stream = Continuity::new([1; 16], 0).unwrap();
        assert!(stream.accept(&event([1; 16], 0, 9)).unwrap());
        assert!(stream.accept(&event([1; 16], 0, 11)).is_err());
        assert!(stream.accept(&event([1; 16], 0, 10)).is_err());
        let mut stream = Continuity::new([1; 16], 0).unwrap();
        assert!(stream.accept(&event([1; 16], 0, u64::MAX)).unwrap());
        assert!(stream.accept(&event([1; 16], 0, 0)).is_err());
    }

    #[test]
    fn first_kernel_fault_retains_raw_event_and_survives_new_recovery() {
        use crate::{capture::Capture, Binding};
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("old");
        let binding = Binding {
            principal: [1; 32],
            attempt: [2; 16],
            namespace: [3; 16],
            session_deadline_ns: 1000,
        };
        let (capture, mut writer) = Capture::create(&path, &binding, [2; 16]).unwrap();
        let mut stream = Continuity::new([2; 16], 9).unwrap();
        assert!(stream
            .capture_event(&event([2; 16], 9, 500), Some(&capture), true)
            .unwrap());
        assert!(stream
            .capture_event(&event([2; 16], 10, 502), Some(&capture), true)
            .is_err());
        assert!(stream
            .capture_event(&event([2; 16], 10, 503), Some(&capture), true)
            .is_err());
        assert_eq!(capture.recorder.health().frontiers[1].gap_count, 1);
        assert_eq!(capture.recorder.health().frontiers[0].gap_count, 0);
        writer.flush().unwrap();
        let recovered = evidence::Recorder::recover(&path).unwrap();
        assert_eq!(recovered.records.len(), 2);
        let fault = &recovered.records[1];
        assert_eq!(fault.kind, evidence::EventKind::SourceGap);
        let retained: serde_json::Value =
            serde_json::from_slice(fault.payload.as_ref().unwrap()).unwrap();
        assert_eq!(retained["fault"]["previous_sequence"], 500);
        assert_eq!(retained["fault"]["observed_sequence"], 502);
        assert_eq!(retained["fault"]["loss_baseline"], 9);
        assert_eq!(retained["fault"]["observed_loss"], 10);
        assert_eq!(retained["event"]["sequence"], 502);
        assert!(recovered.source_summary()[1].gaps.is_empty());
        assert_eq!(recovered.source_summary()[1].source_gap_records, vec![2]);
        assert_eq!(recovered.frontiers[1].gap_count, 1);
        assert!(!recovered.execution_replay(0).eligible);
        let (fresh, mut fresh_writer) =
            Capture::create(&root.path().join("new"), &binding, [4; 16]).unwrap();
        let mut recovery = Continuity::new([4; 16], 10).unwrap();
        assert!(!recovery
            .capture_event(&event([2; 16], 999, 999), Some(&fresh), true)
            .unwrap());
        assert!(recovery
            .capture_event(&event([4; 16], 10, 800), Some(&fresh), true)
            .unwrap());
        fresh_writer.flush().unwrap();
        assert_eq!(fresh.recorder.health().frontiers[1].gap_count, 0);
        assert_eq!(
            evidence::Recorder::recover(&path).unwrap().frontiers[1].gap_count,
            1
        );
    }

    #[test]
    fn contiguous_loss_duplicate_regression_and_wrap_keep_the_exact_offending_event() {
        use crate::{capture::Capture, Binding};
        for (previous, observed, lost, sequence_fault, loss_fault) in [
            (Some(8), 9, 1, false, true),
            (Some(8), 8, 0, true, false),
            (Some(8), 7, 0, true, false),
            (Some(u64::MAX), 0, 0, true, false),
            (None, 0, 0, true, false),
        ] {
            let root = tempfile::tempdir().unwrap();
            let path = root.path().join("capture");
            let binding = Binding {
                principal: [1; 32],
                attempt: [2; 16],
                namespace: [3; 16],
                session_deadline_ns: 1000,
            };
            let (capture, mut writer) = Capture::create(&path, &binding, [2; 16]).unwrap();
            let mut stream = Continuity::new([2; 16], 0).unwrap();
            if let Some(previous) = previous {
                stream
                    .capture_event(&event([2; 16], 0, previous), Some(&capture), true)
                    .unwrap();
            }
            // A stopped ordinary-record path must not suppress the first fault.
            assert!(stream
                .capture_event(&event([2; 16], lost, observed), Some(&capture), false)
                .is_err());
            assert!(stream.faulted);
            writer.flush().unwrap();
            let recovered = evidence::Recorder::recover(&path).unwrap();
            let fault = recovered.records.last().unwrap();
            assert_eq!(fault.kind, evidence::EventKind::SourceGap);
            let value: serde_json::Value =
                serde_json::from_slice(fault.payload.as_ref().unwrap()).unwrap();
            assert_eq!(value["event"]["sequence"], observed);
            assert_eq!(value["event"]["status"]["events_lost"], lost);
            assert_eq!(value["fault"]["sequence_discontinuity"], sequence_fault);
            assert_eq!(value["fault"]["loss_counter_changed"], loss_fault);
            assert_eq!(recovered.frontiers[1].gap_count, 1);
        }
    }
}
