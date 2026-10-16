use crate::{Error, Result};
const MS: u64 = 1_000_000;
/// Conservative mapping measured by an actual HELLO exchange. No poll refreshes it.
#[derive(Clone, Copy)]
pub(crate) struct Mapping {
    sent: u64,
    received: u64,
    controller: u64,
}
impl Mapping {
    pub fn new(sent: u64, received: u64, controller: u64) -> Result<Self> {
        if received < sent || received - sent > 10 * MS {
            return Err(Error::Denied("clock exchange uncertainty"));
        }
        Ok(Self {
            sent,
            received,
            controller,
        })
    }
    /// Conservative current controller time for preflighting kernel slew credit.
    /// Accepted HELLO event capture is no earlier than the kernel's map_host;
    /// using it and rounding drift outward cannot grant extra elapsed credit.
    pub fn controller_lower(&self, host: u64) -> Result<u64> {
        let age = host
            .checked_sub(self.sent)
            .ok_or(Error::Denied("clock moved backwards"))?;
        if age >= 60_000 * MS {
            return Err(Error::Denied("clock mapping expired"));
        }
        let elapsed = host
            .checked_sub(self.received)
            .ok_or(Error::Denied("clock moved backwards"))?;
        self.controller
            .checked_add(elapsed)
            .and_then(|v| v.checked_sub(age.div_ceil(10_000)))
            .ok_or(Error::Denied("controller clock overflow"))
    }
    /// Grants must fit in this exchange's conservative host validity interval.
    pub fn validate_grant_deadline(&self, now: u64, deadline: u64) -> Result<()> {
        self.controller_lower(now)
            .map_err(|_| Error::Denied("clock mapping invalid; explicit recovery required"))?;
        if deadline <= now {
            return Err(Error::Denied("grant deadline is not in the future"));
        }
        let cutoff = self.sent.checked_add(60_000 * MS).ok_or(Error::Denied(
            "clock mapping cutoff overflow; explicit recovery required",
        ))?;
        if deadline >= cutoff {
            return Err(Error::Denied(
                "grant exceeds clock mapping lifetime; recover, rearm and prepare again",
            ));
        }
        Ok(())
    }
    pub fn acquisition(&self, controller: u64, received: u64) -> Result<(u64, u64)> {
        let age = received
            .checked_sub(self.sent)
            .ok_or(Error::Denied("clock moved backwards"))?;
        if age > 60_000 * MS {
            return Err(Error::Denied("clock mapping expired"));
        }
        let delta = controller
            .checked_sub(self.controller)
            .ok_or(Error::Denied("controller clock regressed"))?;
        let drift = age.div_ceil(10_000); // 100 ppm, rounded outwards
        let earliest = self
            .sent
            .checked_add(delta)
            .and_then(|v| v.checked_sub(drift))
            .ok_or(Error::Denied("clock interval overflow"))?;
        let latest = self
            .received
            .checked_add(delta)
            .and_then(|v| v.checked_add(drift))
            .ok_or(Error::Denied("clock interval overflow"))?
            .min(received);
        if earliest > latest {
            return Err(Error::Denied("clock interval uncertainty"));
        }
        Ok((earliest, latest))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn conservative_bounds_and_no_poll_freshness() {
        let m = Mapping::new(100 * MS, 102 * MS, 900 * MS).unwrap();
        let (a, b) = m.acquisition(1000 * MS, 204 * MS).unwrap();
        assert!(a <= 200 * MS && b >= 202 * MS);
        assert!(m.acquisition(1000 * MS, 61_000 * MS).is_err());
        assert!(m.acquisition(899 * MS, 204 * MS).is_err());
        assert!(Mapping::new(0, 11 * MS, 0).is_err());
    }
    #[test]
    fn grant_must_end_before_conservative_mapping_cutoff() {
        let mapping = Mapping::new(1000 * MS, 1002 * MS, 2000 * MS).unwrap();
        let now = 57_000 * MS;
        let cutoff = 61_000 * MS;
        assert!(mapping.controller_lower(now).is_ok());
        // A currently valid old mapping cannot cover a fresh thirty-second grant.
        assert!(mapping
            .validate_grant_deadline(now, now + 30_000 * MS)
            .is_err());
        assert!(mapping.validate_grant_deadline(now, cutoff).is_err());
        assert!(mapping.validate_grant_deadline(now, cutoff - 1).is_ok());
    }
    #[test]
    fn grant_requires_current_mapping_and_future_deadline() {
        let mapping = Mapping::new(1000 * MS, 1002 * MS, 2000 * MS).unwrap();
        assert!(mapping
            .validate_grant_deadline(2000 * MS, 2000 * MS)
            .is_err());
        assert!(mapping
            .validate_grant_deadline(2000 * MS, 1999 * MS)
            .is_err());
        assert!(mapping
            .validate_grant_deadline(999 * MS, 2000 * MS)
            .is_err());
        assert!(mapping
            .validate_grant_deadline(1001 * MS, 2000 * MS)
            .is_err());
        assert!(mapping
            .validate_grant_deadline(61_000 * MS, 61_001 * MS)
            .is_err());
        assert!(Mapping::new(0, 0, u64::MAX)
            .unwrap()
            .validate_grant_deadline(1, 2)
            .is_err());
    }
    #[test]
    fn grant_mapping_cutoff_overflow_is_rejected() {
        let sent = u64::MAX - 1000 * MS;
        let mapping = Mapping::new(sent, sent + MS, 2000 * MS).unwrap();
        let now = sent + 2 * MS;
        assert!(mapping.controller_lower(now).is_ok());
        assert!(mapping.validate_grant_deadline(now, now + MS).is_err());
    }
}

#[cfg(test)]
mod slew_tests {
    use super::*;
    #[test]
    fn delayed_start_has_no_credit_from_old_baseline() {
        let mapping = Mapping::new(990 * MS, 1000 * MS, 2000 * MS).unwrap();
        let baseline = 2000 * MS;
        let started = 2200 * MS; // START delayed by durable writer, then just accepted
        let now = 1201 * MS;
        assert!(mapping.controller_lower(now).unwrap() - baseline >= 100 * MS);
        assert!(mapping.controller_lower(now).unwrap() - started < 100 * MS);
        assert!(mapping.controller_lower(1301 * MS).unwrap() - started >= 100 * MS);
    }
    #[test]
    fn observed_hundred_ms_is_not_conservative_hundred_ms() {
        let mapping = Mapping::new(990 * MS, 1000 * MS, 2000 * MS).unwrap();
        let started = 2000 * MS;
        let actual_observation = 2100 * MS;
        assert_eq!(actual_observation - started, 100 * MS);
        assert!(mapping.controller_lower(1100 * MS).unwrap() - started < 100 * MS);
        assert!(mapping.controller_lower(1101 * MS).unwrap() - started >= 100 * MS);
        assert!(mapping.controller_lower(60_990 * MS).is_err());
    }
}
