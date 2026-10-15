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
}
