use crate::{Error, Result};
use authority_client::Event;

/// A new explicit recovery starts a stream; cumulative historical loss is retained.
pub(crate) struct Continuity {
    pub epoch: [u8; 16],
    pub lost_baseline: u32,
    pub faulted: bool,
    sequence: Option<u64>,
}
impl Continuity {
    pub fn new(epoch: [u8; 16], lost_baseline: u32) -> Result<Self> {
        if epoch == [0; 16] || lost_baseline == u32::MAX {
            return Err(Error::Denied("event identity/loss counter exhausted"));
        }
        Ok(Self {
            epoch,
            lost_baseline,
            faulted: false,
            sequence: None,
        })
    }
    pub fn accept(&mut self, event: &Event) -> Result<bool> {
        if event.status.runtime_nonce != self.epoch {
            return Ok(false);
        }
        if self.faulted
            || event.status.events_lost != self.lost_baseline
            || self
                .sequence
                .is_some_and(|last| last.checked_add(1) != Some(event.sequence))
        {
            self.faulted = true;
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
}
