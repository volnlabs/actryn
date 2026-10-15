use crate::{Error, Result};
use serde::Serialize;
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct Target {
    pub left_ticks: i64,
    pub right_ticks: i64,
    pub duration_ms: u64,
}
impl Target {
    pub fn validate(self) -> Result<()> {
        if self.left_ticks.unsigned_abs() > 100
            || self.right_ticks.unsigned_abs() > 100
            || self.duration_ms == 0
            || self.duration_ms > 10000
        {
            return Err(Error::Denied("target outside fixed skill envelope"));
        }
        Ok(())
    }
}
#[derive(Debug, PartialEq, Eq)]
pub(crate) enum Action {
    Duty([i32; 2]),
    Finish,
    Expired,
}
pub(crate) struct Step {
    target: [i64; 2],
    direction: [i32; 2],
    reached: [bool; 2],
    deadline: u64,
}
impl Step {
    pub fn new(start: [i64; 2], target: Target, deadline: u64) -> Result<Self> {
        target.validate()?;
        let delta = [target.left_ticks, target.right_ticks];
        let absolute = [
            start[0].checked_add(delta[0]),
            start[1].checked_add(delta[1]),
        ];
        Ok(Self {
            target: [
                absolute[0].ok_or(Error::Denied("encoder overflow"))?,
                absolute[1].ok_or(Error::Denied("encoder overflow"))?,
            ],
            direction: [delta[0].signum() as i32, delta[1].signum() as i32],
            reached: [delta[0] == 0, delta[1] == 0],
            deadline,
        })
    }
    pub fn update(&mut self, ticks: [i64; 2], now: u64) -> Result<Action> {
        if now >= self.deadline {
            return Ok(Action::Expired);
        }
        for (i, tick) in ticks.iter().enumerate() {
            self.reached[i] |= if self.direction[i] > 0 {
                *tick >= self.target[i]
            } else {
                *tick <= self.target[i]
            };
        }
        if self.reached.iter().all(|v| *v) {
            return Ok(Action::Finish);
        }
        Ok(Action::Duty(std::array::from_fn(|i| {
            if self.reached[i] {
                0
            } else {
                self.direction[i] * 100
            }
        })))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounded_target_and_checked_absolute_target() {
        assert!(Step::new(
            [i64::MAX, 0],
            Target {
                left_ticks: 1,
                right_ticks: 0,
                duration_ms: 1000
            },
            500
        )
        .is_err());
        assert!(Step::new(
            [0, 0],
            Target {
                left_ticks: 101,
                right_ticks: 0,
                duration_ms: 1000
            },
            500
        )
        .is_err());
        assert!(Step::new(
            [0, 0],
            Target {
                left_ticks: 1,
                right_ticks: 0,
                duration_ms: 10001
            },
            500
        )
        .is_err());
    }
    #[test]
    fn wheels_stop_independently_without_reversing_after_crossing() {
        let mut step = Step::new(
            [10, 10],
            Target {
                left_ticks: 2,
                right_ticks: -3,
                duration_ms: 1000,
            },
            5_000_000_000,
        )
        .unwrap();
        assert_eq!(step.update([10, 10], 1).unwrap(), Action::Duty([100, -100]));
        assert_eq!(step.update([13, 9], 2).unwrap(), Action::Duty([0, -100]));
        assert_eq!(step.update([11, 6], 3).unwrap(), Action::Finish);
        assert_eq!(step.update([10, 10], 4).unwrap(), Action::Finish);
    }
    #[test]
    fn expiry_cannot_report_target_success() {
        let mut step = Step::new(
            [0, 0],
            Target {
                left_ticks: 1,
                right_ticks: 1,
                duration_ms: 1,
            },
            5,
        )
        .unwrap();
        assert_eq!(step.update([1, 1], 5).unwrap(), Action::Expired);
    }
}
