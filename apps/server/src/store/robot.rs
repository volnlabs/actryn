use super::*;
use crate::robot::{self, Binding, Handle, Intent, Observation, Phase, RemoteSnapshot};

pub(super) fn close(tx: &rusqlite::Transaction<'_>, attempt: Option<&str>) -> Result<()> {
    let rows = tx
        .prepare(
            "SELECT data FROM robot_requests WHERE outstanding=1 AND (?1 IS NULL OR attempt_id=?1)",
        )?
        .query_map([attempt], |r| r.get::<_, String>(0))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    for row in rows {
        let mut value: Intent = serde_json::from_str(&row)?;
        value.cancellation_requested = true;
        value.phase = Phase::Unknown;
        save(tx, &value)?;
    }
    Ok(())
}
fn save(db: &Connection, value: &Intent) -> Result<()> {
    let data = serde_json::to_string(value)?;
    ensure!(data.len() <= 8192, "robot intent metadata bound");
    ensure!(db.execute("UPDATE robot_requests SET data=?3,outstanding=?4,cancelled=?5 WHERE attempt_id=?1 AND request_key=?2",
        params![value.handle.attempt,value.request_key,data,value.outstanding_debit,value.cancellation_requested])?==1,"robot intent missing");
    Ok(())
}
fn get(db: &Connection, attempt: &str, key: &str) -> Result<Intent> {
    let data: String = db.query_row(
        "SELECT data FROM robot_requests WHERE attempt_id=?1 AND request_key=?2",
        params![attempt, key],
        |r| r.get(0),
    )?;
    ensure!(data.len() <= 8192, "retained Robot intent bound");
    Ok(serde_json::from_str(&data)?)
}
fn mutable(db: &Connection, value: &Intent, now: i64) -> Result<()> {
    let attempt = db.query_row(ATTEMPT, [&value.handle.attempt], read_attempt)?;
    ensure!(
        attempt.state == "running"
            && attempt.deadline_ms > now
            && value.deadline_ms > now
            && !value.cancellation_requested,
        "robot publication closed or expired"
    );
    Ok(())
}
impl Store {
    pub fn robot_bind(&mut self, binding: &Binding, now: i64) -> Result<()> {
        binding.validate()?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let attempt = tx.query_row(ATTEMPT, [&binding.attempt_id], read_attempt)?;
        ensure!(
            attempt.state == "prepared"
                && attempt.deadline_ms > now
                && binding.created_ms <= now
                && binding.deadline_ms > now
                && binding.deadline_ms <= attempt.deadline_ms,
            "binding requires a live prepared attempt"
        );
        tx.execute(
            "INSERT INTO robot_bindings(attempt_id,namespace,data) VALUES(?1,?2,?3)",
            params![
                binding.attempt_id,
                binding.namespace,
                serde_json::to_string(binding)?
            ],
        )?;
        tx.commit()?;
        Ok(())
    }
    pub fn robot_binding(&self, attempt: &str) -> Result<Option<Binding>> {
        self.db
            .query_row(
                "SELECT data FROM robot_bindings WHERE attempt_id=?1",
                [attempt],
                |r| r.get::<_, String>(0),
            )
            .optional()?
            .map(|v| {
                ensure!(v.len() <= 4096, "retained Robot binding bound");
                let binding: Binding = serde_json::from_str(&v)?;
                binding.validate()?;
                Ok(binding)
            })
            .transpose()
    }
    pub fn robot_reserve(
        &mut self,
        attempt: &str,
        request_key: &str,
        request_digest: &str,
        now: i64,
    ) -> Result<Intent> {
        key(request_key)?;
        ensure!(
            !request_digest.is_empty() && request_digest.len() <= 128,
            "request digest bound"
        );
        let binding = self
            .robot_binding(attempt)?
            .context("robot delegation not bound")?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let a = tx.query_row(ATTEMPT, [attempt], read_attempt)?;
        ensure!(
            a.state == "running" && a.deadline_ms > now && binding.deadline_ms > now,
            "robot attempt expired/closed"
        );
        let cancelled:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM calls WHERE attempt_id=?1 AND request_key=?2 AND publication_closed=1)",params![attempt,request_key],|r|r.get(0))?;
        ensure!(!cancelled, "request key already cancelled");
        let count: i64 = tx.query_row(
            "SELECT count(*) FROM robot_requests WHERE attempt_id=?1",
            [attempt],
            |r| r.get(0),
        )?;
        let (local,global):(i64,i64)=tx.query_row("SELECT coalesce(sum(attempt_id=?1),0),count(*) FROM robot_requests WHERE outstanding=1",[attempt],|r|Ok((r.get(0)?,r.get(1)?)))?;
        ensure!(
            count < robot::KEYS_PER_ATTEMPT as i64
                && local < robot::PER_ATTEMPT_JOBS as i64
                && global < robot::GLOBAL_JOBS as i64,
            "robot retained-key/outstanding capacity exhausted"
        );
        let key: String = tx.query_row("SELECT lower(hex(randomblob(32)))", [], |r| r.get(0))?;
        let intent = Intent {
            request_key: request_key.into(),
            request_digest: request_digest.into(),
            handle: Handle {
                attempt: attempt.into(),
                namespace: binding.namespace,
                key,
            },
            robot_epoch: binding.robot_epoch,
            phase: Phase::Reserved,
            cancellation_requested: false,
            outstanding_debit: true,
            deadline_ms: a.deadline_ms.min(binding.deadline_ms),
            observation: None,
            observation_digest: None,
            execution_observation: None,
            execution_observation_digest: None,
            parent_digest: None,
            proposal_digest: None,
            last_remote: None,
            historical_response: false,
            remote_unavailable: false,
        };
        tx.execute("INSERT INTO robot_requests(attempt_id,request_key,data,outstanding,cancelled) VALUES(?1,?2,?3,1,0)",params![attempt,request_key,serde_json::to_string(&intent)?])?;
        tx.commit()?;
        Ok(intent)
    }
    pub fn robot_intent(&self, attempt: &str, request_key: &str) -> Result<Intent> {
        get(&self.db, attempt, request_key)
    }
    pub fn robot_intents(&self, attempt: &str) -> Result<Vec<Intent>> {
        self.db
            .prepare("SELECT data FROM robot_requests WHERE attempt_id=?1 ORDER BY rowid")?
            .query_map([attempt], |r| r.get::<_, String>(0))?
            .map(|v| Ok(serde_json::from_str(&v?)?))
            .collect()
    }
    pub fn robot_pending(&self) -> Result<Vec<(Binding, Intent)>> {
        let rows = self
            .db
            .prepare("SELECT data FROM robot_requests WHERE outstanding=1 ORDER BY rowid")?
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        ensure!(
            rows.len() <= robot::GLOBAL_JOBS,
            "ambiguous remote debit accounting"
        );
        rows.into_iter()
            .map(|v| {
                let i: Intent = serde_json::from_str(&v)?;
                Ok((
                    self.robot_binding(&i.handle.attempt)?
                        .context("robot binding missing")?,
                    i,
                ))
            })
            .collect()
    }
    pub fn robot_observe(
        &mut self,
        attempt: &str,
        key: &str,
        observation: &Observation,
        now: i64,
    ) -> Result<Intent> {
        observation.validate()?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut value = get(&tx, attempt, key)?;
        mutable(&tx, &value, now)?;
        ensure!(
            value.phase == Phase::Reserved && value.observation.is_none(),
            "observation already fixed"
        );
        value.observation = Some(observation.clone());
        value.observation_digest = Some(robot::digest(observation)?);
        value.parent_digest = Some(robot::digest(
            &serde_json::json!({"handle":value.handle,"request_digest":value.request_digest,"robot_epoch":value.robot_epoch,"observation":observation}),
        )?);
        value.phase = Phase::Observed;
        save(&tx, &value)?;
        tx.commit()?;
        Ok(value)
    }
    pub fn robot_dispatch(
        &mut self,
        attempt: &str,
        key: &str,
        digest: &str,
        now: i64,
    ) -> Result<Intent> {
        ensure!(valid_digest(digest), "proposal digest required");
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut value = get(&tx, attempt, key)?;
        mutable(&tx, &value, now)?;
        ensure!(
            value.phase == Phase::Observed && value.proposal_digest.is_none(),
            "proposal already sent or closed"
        );
        value.proposal_digest = Some(digest.into());
        value.phase = Phase::DispatchIntent;
        save(&tx, &value)?;
        tx.commit()?;
        Ok(value)
    }

    pub fn robot_execution_observe(
        &mut self,
        attempt: &str,
        key: &str,
        observation: &Observation,
        now: i64,
    ) -> Result<Intent> {
        observation.validate()?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut value = get(&tx, attempt, key)?;
        mutable(&tx, &value, now)?;
        let original = value
            .observation
            .as_ref()
            .context("model observation missing")?;
        ensure!(
            value.phase == Phase::Observed
                && value.execution_observation.is_none()
                && observation.id > original.id
                && observation.acquired_earliest_ns > original.acquired_earliest_ns
                && observation.acquired_latest_ns > original.acquired_latest_ns
                && observation.controller_ns >= original.controller_ns
                && observation.left_ticks == original.left_ticks
                && observation.right_ticks == original.right_ticks
                && observation.context_revision == original.context_revision
                && observation.simulated == original.simulated,
            "execution observation does not revalidate model context"
        );
        value.execution_observation = Some(observation.clone());
        value.execution_observation_digest = Some(robot::digest(observation)?);
        save(&tx, &value)?;
        tx.commit()?;
        Ok(value)
    }
    pub fn robot_cancel_key(&mut self, attempt: &str, key: &str) -> Result<Option<Intent>> {
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let exists: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM robot_requests WHERE attempt_id=?1 AND request_key=?2)",
            params![attempt, key],
            |r| r.get(0),
        )?;
        if !exists {
            return Ok(None);
        }
        let mut value = get(&tx, attempt, key)?;
        value.cancellation_requested = true;
        if value.outstanding_debit {
            value.phase = Phase::Unknown;
        }
        save(&tx, &value)?;
        tx.commit()?;
        Ok(Some(value))
    }
    pub fn robot_unknown(&mut self, attempt: &str, key: &str, historical: bool) -> Result<Intent> {
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut value = get(&tx, attempt, key)?;
        if value.outstanding_debit {
            value.phase = Phase::Unknown;
        }
        value.historical_response |= historical;
        value.remote_unavailable = true;
        save(&tx, &value)?;
        tx.commit()?;
        Ok(value)
    }
    pub fn robot_snapshot(
        &mut self,
        attempt: &str,
        key: &str,
        snapshot: &RemoteSnapshot,
    ) -> Result<Intent> {
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut value = get(&tx, attempt, key)?;
        snapshot.validate_for(&value)?;
        // Retained durable reconciliation is independent proof; a later historical
        // query must not overwrite it with the restarted manager's uncertainty.
        if !value.outstanding_debit {
            return Ok(value);
        }
        if value.outstanding_debit {
            if snapshot.settled() {
                value.outstanding_debit = false;
                value.phase = Phase::Settled;
            } else if snapshot.verdict == robot::Verdict::OutcomeUnknown {
                value.phase = Phase::Unknown;
            } else {
                value.phase = Phase::Accepted;
            }
        }
        value.last_remote = Some(snapshot.clone());
        value.remote_unavailable = false;
        save(&tx, &value)?;
        tx.commit()?;
        Ok(value)
    }
}
