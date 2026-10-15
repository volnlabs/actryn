use anyhow::{bail, ensure, Context, Result};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};
use std::{path::Path, time::Duration};
mod robot;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Limits {
    pub prepared: i64,
    pub active: i64,
    pub prepare_lifetime_ms: i64,
    pub attempt_lifetime_ms: i64,
    pub per_attempt_jobs: i64,
    pub global_jobs: i64,
    pub request_bytes: i64,
    pub response_bytes: i64,
    pub retained_output_bytes: i64,
    pub max_output_tokens: i64,
    pub max_calls_per_attempt: i64,
    pub request_deadline_ms: i64,
    pub keys_per_attempt: i64,
    pub retained_attempts: i64,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            prepared: 1,
            active: 1,
            prepare_lifetime_ms: 60_000,
            attempt_lifetime_ms: 120_000,
            per_attempt_jobs: 2,
            global_jobs: 4,
            request_bytes: 65_536,
            response_bytes: 65_536,
            retained_output_bytes: 262_144,
            max_output_tokens: 1024,
            max_calls_per_attempt: 4,
            request_deadline_ms: 30_000,
            keys_per_attempt: 16,
            retained_attempts: 128,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Attempt {
    pub id: String,
    pub artifact_digest: String,
    pub state: String,
    pub deadline_ms: i64,
    pub binding: Option<String>,
    pub outcome: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Reservation {
    pub id: String,
    pub request_key: String,
    pub state: String,
    pub consumed_tokens: i64,
    pub deadline_ms: i64,
    pub publication_closed: bool,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct Inspection {
    pub attempt: Attempt,
    pub calls: Vec<Reservation>,
    pub evidence_gaps: Vec<String>,
    pub denials: Vec<Denial>,
    #[serde(default)]
    pub denials_omitted: usize,
    #[serde(default)]
    pub robot_binding: Option<crate::robot::Binding>,
    #[serde(default)]
    pub robot_requests: Vec<crate::robot::Summary>,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct Denial {
    pub request_key: String,
    pub method: String,
    pub reason: String,
}
#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Publication {
    Published(Vec<u8>),
    Suppressed,
    OutputLimit,
}

pub struct Store {
    db: Connection,
    limits: Limits,
}
const ATTEMPT: &str =
    "SELECT id,artifact_digest,state,deadline_ms,binding,outcome FROM attempts WHERE id=?1";
const CALL: &str = "SELECT id,request_key,state,consumed_tokens,deadline_ms,publication_closed FROM calls WHERE attempt_id=?1 AND request_key=?2";
fn read_attempt(r: &rusqlite::Row<'_>) -> rusqlite::Result<Attempt> {
    Ok(Attempt {
        id: r.get(0)?,
        artifact_digest: r.get(1)?,
        state: r.get(2)?,
        deadline_ms: r.get(3)?,
        binding: r.get(4)?,
        outcome: r.get(5)?,
    })
}
fn read_call(r: &rusqlite::Row<'_>) -> rusqlite::Result<Reservation> {
    Ok(Reservation {
        id: r.get(0)?,
        request_key: r.get(1)?,
        state: r.get(2)?,
        consumed_tokens: r.get(3)?,
        deadline_ms: r.get(4)?,
        publication_closed: r.get(5)?,
    })
}
fn id(db: &Connection) -> Result<String> {
    Ok(db.query_row("SELECT lower(hex(randomblob(16)))", [], |r| r.get(0))?)
}
fn deadline(now: i64, delta: i64) -> Result<i64> {
    let value = now.checked_add(delta).context("deadline overflow")?;
    ensure!(now >= 0 && value >= 0, "invalid deadline");
    Ok(value)
}
pub fn valid_id(s: &str) -> bool {
    s.len() == 32
        && s.bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}
pub fn valid_digest(s: &str) -> bool {
    s.strip_prefix("sha256:").is_some_and(|v| {
        v.len() == 64
            && v.bytes()
                .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
    })
}
fn key(s: &str) -> Result<()> {
    ensure!(
        !s.is_empty()
            && s.len() <= 128
            && s.bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-_.:".contains(&b)),
        "invalid request key"
    );
    Ok(())
}

impl Store {
    pub fn record_runtime_evidence(&mut self, id: &str, data: &str) -> Result<()> {
        ensure!(data.len() <= 16384, "runtime evidence exceeds fixed cap");
        let _: serde_json::Value = serde_json::from_str(data)?;
        self.db.execute("INSERT INTO runtime_evidence(attempt_id,data) VALUES(?1,?2) ON CONFLICT(attempt_id) DO UPDATE SET data=excluded.data",params![id,data])?;
        Ok(())
    }
    pub fn runtime_evidence(&self, id: &str) -> Result<Option<String>> {
        Ok(self
            .db
            .query_row(
                "SELECT data FROM runtime_evidence WHERE attempt_id=?1",
                [id],
                |r| r.get(0),
            )
            .optional()?)
    }
    pub fn open(path: impl AsRef<Path>, limits: Limits) -> Result<Self> {
        for n in [
            limits.prepared,
            limits.active,
            limits.prepare_lifetime_ms,
            limits.attempt_lifetime_ms,
            limits.per_attempt_jobs,
            limits.global_jobs,
            limits.request_bytes,
            limits.response_bytes,
            limits.retained_output_bytes,
            limits.max_output_tokens,
            limits.max_calls_per_attempt,
            limits.request_deadline_ms,
            limits.keys_per_attempt,
            limits.retained_attempts,
        ] {
            ensure!(n > 0 && n <= 1_000_000_000, "invalid finite limit");
        }
        ensure!(
            limits.keys_per_attempt > limits.max_calls_per_attempt,
            "no cancellation key reserve"
        );
        let db = Connection::open(path)?;
        db.busy_timeout(Duration::from_millis(250))?;
        db.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS attempts (
              id TEXT PRIMARY KEY,artifact_digest TEXT NOT NULL,state TEXT NOT NULL,
              deadline_ms INTEGER NOT NULL,binding TEXT,outcome TEXT NOT NULL DEFAULT 'pending');
            CREATE TABLE IF NOT EXISTS calls (
              id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL REFERENCES attempts(id),request_key TEXT NOT NULL,
              digest TEXT,state TEXT NOT NULL,request_bytes INTEGER NOT NULL DEFAULT 0,
              response_capacity INTEGER NOT NULL DEFAULT 0,token_reserved INTEGER NOT NULL DEFAULT 0,
              consumed_tokens INTEGER NOT NULL DEFAULT 0,deadline_ms INTEGER NOT NULL DEFAULT 0,
              publication_closed INTEGER NOT NULL DEFAULT 0,output BLOB,UNIQUE(attempt_id,request_key));
            CREATE TABLE IF NOT EXISTS gaps(attempt_id TEXT NOT NULL REFERENCES attempts(id),reason TEXT NOT NULL,UNIQUE(attempt_id,reason));
            CREATE TABLE IF NOT EXISTS runtime_evidence(attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS denials(attempt_id TEXT NOT NULL REFERENCES attempts(id),request_key TEXT NOT NULL,method TEXT NOT NULL,UNIQUE(attempt_id,request_key,method));")?;
        db.execute_batch("CREATE TABLE IF NOT EXISTS robot_bindings(attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),namespace TEXT NOT NULL UNIQUE,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS robot_requests(attempt_id TEXT NOT NULL REFERENCES robot_bindings(attempt_id),request_key TEXT NOT NULL,data TEXT NOT NULL,outstanding INTEGER NOT NULL,cancelled INTEGER NOT NULL,PRIMARY KEY(attempt_id,request_key));")?;
        let integrity: String = db.query_row("PRAGMA quick_check", [], |r| r.get(0))?;
        ensure!(integrity == "ok", "ambiguous/corrupt accounting storage");
        Ok(Self { db, limits })
    }
    /// Import only an authenticated restricted-launcher response, never an agent field.
    pub fn adopt_prepared(&mut self, a: &Attempt) -> Result<()> {
        ensure!(
            valid_id(&a.id)
                && valid_digest(&a.artifact_digest)
                && a.state == "prepared"
                && a.binding.is_some(),
            "invalid launcher preparation"
        );
        self.db.execute("INSERT INTO attempts(id,artifact_digest,state,deadline_ms,binding,outcome) VALUES(?1,?2,'prepared',?3,?4,'pending')",params![a.id,a.artifact_digest,a.deadline_ms,a.binding])?;
        Ok(())
    }
    pub fn prepare(&mut self, artifact_digest: &str, now: i64) -> Result<Attempt> {
        ensure!(
            valid_digest(artifact_digest),
            "invalid immutable artifact digest"
        );
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let (staged,live):(i64,i64)=tx.query_row("SELECT coalesce(sum(state IN ('preparing','prepared')),0),coalesce(sum(state!='reaped'),0) FROM attempts",[],|r|Ok((r.get(0)?,r.get(1)?)))?;
        let retained: i64 = tx.query_row("SELECT count(*) FROM attempts", [], |r| r.get(0))?;
        ensure!(
            retained < self.limits.retained_attempts,
            "retained attempt history capacity exhausted"
        );
        ensure!(
            staged < self.limits.prepared && live < self.limits.prepared + self.limits.active,
            "preparation capacity exhausted; cleanup still charged"
        );
        let identity = id(&tx)?;
        tx.execute("INSERT INTO attempts(id,artifact_digest,state,deadline_ms) VALUES(?1,?2,'preparing',?3)",params![identity,artifact_digest,deadline(now,self.limits.prepare_lifetime_ms)?])?;
        let result = tx.query_row(ATTEMPT, [&identity], read_attempt)?;
        tx.commit()?;
        Ok(result)
    }
    pub fn record_binding(&mut self, id: &str, binding: &str) -> Result<()> {
        ensure!(binding.len() <= 16384, "binding too large");
        ensure!(
            self.db.execute(
                "UPDATE attempts SET binding=?2 WHERE id=?1 AND state IN ('preparing','prepared')",
                params![id, binding]
            )? == 1,
            "attempt not bindable"
        );
        Ok(())
    }
    pub fn mark_prepared(&mut self, id: &str, binding: &str) -> Result<()> {
        ensure!(
            !binding.is_empty() && binding.len() <= 16384,
            "invalid runtime binding"
        );
        ensure!(
            self.db.execute(
                "UPDATE attempts SET state='prepared',binding=?2 WHERE id=?1 AND state='preparing'",
                params![id, binding]
            )? == 1,
            "attempt closed or not preparing"
        );
        Ok(())
    }
    pub fn start(&mut self, id: &str, now: i64) -> Result<()> {
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let running: i64 = tx.query_row(
            "SELECT count(*) FROM attempts WHERE state='running'",
            [],
            |r| r.get(0),
        )?;
        ensure!(running < self.limits.active, "active capacity exhausted");
        ensure!(tx.execute("UPDATE attempts SET state='running',deadline_ms=?3 WHERE id=?1 AND state='prepared' AND deadline_ms>?2 AND binding IS NOT NULL",params![id,now,deadline(now,self.limits.attempt_lifetime_ms)?])?==1,"expired or closed preparation");
        tx.commit()?;
        Ok(())
    }
    /// Close publication gates before invoking this durable bookkeeping operation.
    pub fn record_denial(&mut self, id: &str, request_key: &str, method: &str) -> Result<()> {
        ensure!(
            request_key.len() <= 128 && method.len() <= 128,
            "denial metadata too large"
        );
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let count: i64 = tx.query_row(
            "SELECT count(*) FROM denials WHERE attempt_id=?1",
            [id],
            |r| r.get(0),
        )?;
        if count < 64 {
            tx.execute(
                "INSERT OR IGNORE INTO denials(attempt_id,request_key,method) VALUES(?1,?2,?3)",
                params![id, request_key, method],
            )?;
        } else {
            tx.execute(
                "INSERT OR IGNORE INTO gaps(attempt_id,reason) VALUES(?1,'policy_denial_overflow')",
                [id],
            )?;
        }
        tx.commit()?;
        Ok(())
    }
    pub fn record_gap(&mut self, id: &str, reason: &str) -> Result<()> {
        ensure!(
            [
                "observer_unavailable",
                "observer_changed",
                "log_incomplete",
                "policy_denial_overflow"
            ]
            .contains(&reason),
            "unknown diagnostic gap"
        );
        self.db.execute(
            "INSERT OR IGNORE INTO gaps(attempt_id,reason) VALUES(?1,?2)",
            params![id, reason],
        )?;
        Ok(())
    }
    pub fn cancel(&mut self, id: &str) -> Result<()> {
        self.retire(id, "cancelled")
    }
    pub fn retire(&mut self, id: &str, outcome: &str) -> Result<()> {
        ensure!(
            !outcome.is_empty() && outcome.len() <= 64,
            "invalid outcome"
        );
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        ensure!(tx.execute("UPDATE attempts SET state=CASE WHEN state='reaped' THEN state ELSE 'retiring' END,outcome=CASE WHEN outcome='pending' THEN ?2 ELSE outcome END WHERE id=?1",params![id,outcome])?==1,"unknown attempt");
        tx.execute("UPDATE calls SET publication_closed=1,output=NULL,state=CASE WHEN state='reserved' THEN 'cancelled' ELSE state END WHERE attempt_id=?1",[id])?;
        robot::close(&tx, Some(id))?;
        tx.commit()?;
        Ok(())
    }
    /// Only call after the entire cgroup is empty and runtime resources are gone.
    pub fn mark_reaped(&mut self, id: &str) -> Result<()> {
        ensure!(
            self.db.execute(
                "UPDATE attempts SET state='reaped' WHERE id=?1 AND state IN ('retiring','reaped')",
                [id]
            )? == 1,
            "attempt not retiring"
        );
        Ok(())
    }
    pub fn recover(&mut self) -> Result<Vec<String>> {
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let ids = tx
            .prepare("SELECT id FROM attempts WHERE state!='reaped' ORDER BY id")?
            .query_map([], |r| r.get(0))?
            .collect::<rusqlite::Result<Vec<String>>>()?;
        tx.execute(
            "UPDATE attempts SET state='retiring',outcome=CASE WHEN outcome='pending' THEN 'unknown' ELSE outcome END WHERE state!='reaped'",
            [],
        )?;
        tx.execute("UPDATE calls SET publication_closed=1,output=NULL,state=CASE WHEN state='reserved' THEN 'cancelled' WHEN state='dispatched' THEN 'unknown' ELSE state END",[])?;
        robot::close(&tx, None)?;
        tx.commit()?;
        Ok(ids)
    }
    pub fn reserve_call(
        &mut self,
        attempt: &str,
        request_key: &str,
        digest: &str,
        bytes: i64,
        now: i64,
    ) -> Result<Reservation> {
        key(request_key)?;
        ensure!(
            !digest.is_empty() && digest.len() <= 128,
            "invalid request digest"
        );
        ensure!(
            bytes >= 0 && bytes <= self.limits.request_bytes,
            "request too large"
        );
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        if let Some(existing) = tx
            .query_row(CALL, params![attempt, request_key], read_call)
            .optional()?
        {
            let stored: Option<String> = tx.query_row(
                "SELECT digest FROM calls WHERE id=?1",
                [&existing.id],
                |r| r.get(0),
            )?;
            ensure!(
                !existing.publication_closed && stored.as_deref() == Some(digest),
                "closed key or changed duplicate"
            );
            return Ok(existing);
        }
        let a = tx.query_row(ATTEMPT, [attempt], read_attempt)?;
        ensure!(
            a.state == "running" && a.deadline_ms > now,
            "attempt is not live"
        );
        let count: i64 = tx.query_row(
            "SELECT count(*) FROM calls WHERE attempt_id=?1 AND digest IS NOT NULL",
            [attempt],
            |r| r.get(0),
        )?;
        ensure!(
            count < self.limits.max_calls_per_attempt,
            "attempt call budget exhausted"
        );
        let keys: i64 = tx.query_row(
            "SELECT count(*) FROM calls WHERE attempt_id=?1",
            [attempt],
            |r| r.get(0),
        )?;
        ensure!(
            keys < self.limits.keys_per_attempt,
            "request-key capacity exhausted"
        );
        let (local,global):(i64,i64)=tx.query_row("SELECT coalesce(sum(attempt_id=?1),0),count(*) FROM calls WHERE state IN ('reserved','dispatched','unknown')",[attempt],|r|Ok((r.get(0)?,r.get(1)?)))?;
        ensure!(
            local < self.limits.per_attempt_jobs && global < self.limits.global_jobs,
            "delegated capacity exhausted"
        );
        let retained:i64=tx.query_row("SELECT coalesce(sum(CASE WHEN state IN ('reserved','dispatched','unknown') THEN response_capacity ELSE coalesce(length(output),0) END),0) FROM calls",[],|r|r.get(0))?;
        ensure!(
            retained + self.limits.response_bytes <= self.limits.retained_output_bytes,
            "output storage capacity exhausted"
        );
        let identity = id(&tx)?;
        tx.execute("INSERT INTO calls(id,attempt_id,request_key,digest,state,request_bytes,response_capacity,token_reserved,deadline_ms) VALUES(?1,?2,?3,?4,'reserved',?5,?6,?7,?8)",params![identity,attempt,request_key,digest,bytes,self.limits.response_bytes,self.limits.max_output_tokens,deadline(now,self.limits.request_deadline_ms)?.min(a.deadline_ms)])?;
        let result = tx.query_row(CALL, params![attempt, request_key], read_call)?;
        tx.commit()?;
        Ok(result)
    }
    /// Commit before the first external effect. Any crash after this point is uncertain.
    pub fn mark_dispatched(&mut self, id: &str, now: i64) -> Result<()> {
        ensure!(self.db.execute("UPDATE calls SET state='dispatched' WHERE id=?1 AND state='reserved' AND publication_closed=0 AND deadline_ms>?2 AND EXISTS(SELECT 1 FROM attempts WHERE attempts.id=calls.attempt_id AND state='running' AND deadline_ms>?2)",params![id,now])?==1,"request closed, expired or already dispatched");
        Ok(())
    }
    pub fn cancel_call(&mut self, attempt: &str, request_key: &str) -> Result<()> {
        key(request_key)?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let _: Attempt = tx.query_row(ATTEMPT, [attempt], read_attempt)?;
        let changed=tx.execute("UPDATE calls SET publication_closed=1,output=NULL,state=CASE WHEN state='reserved' THEN 'cancelled' ELSE state END WHERE attempt_id=?1 AND request_key=?2",params![attempt,request_key])?;
        if changed == 0 {
            let count: i64 = tx.query_row(
                "SELECT count(*) FROM calls WHERE attempt_id=?1",
                [attempt],
                |r| r.get(0),
            )?;
            if count >= self.limits.keys_per_attempt {
                tx.execute("UPDATE attempts SET state='retiring',outcome='capacity' WHERE id=?1 AND state!='reaped'",[attempt])?;
                tx.execute(
                    "UPDATE calls SET publication_closed=1 WHERE attempt_id=?1",
                    [attempt],
                )?;
                tx.commit()?;
                bail!("cancellation-key capacity exhausted; namespace closed");
            }
            tx.execute("INSERT INTO calls(id,attempt_id,request_key,state,publication_closed) VALUES(?1,?2,?3,'cancelled',1)",params![id(&tx)?,attempt,request_key])?;
        }
        tx.commit()?;
        Ok(())
    }
    /// The trusted connector must establish terminal provider completion before settlement.
    pub fn settle(
        &mut self,
        id: &str,
        tokens: i64,
        output: &[u8],
        now: i64,
    ) -> Result<Publication> {
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let (state,closed,cap,reserved,expires,attempt):(String,bool,i64,i64,i64,String)=tx.query_row("SELECT state,publication_closed,response_capacity,token_reserved,deadline_ms,attempt_id FROM calls WHERE id=?1",[id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?)))?;
        ensure!(
            state == "dispatched" || state == "unknown",
            "not unsettled external work"
        );
        ensure!(
            tokens >= 0 && tokens <= reserved,
            "provider exceeded reserved tokens; debit remains quarantined"
        );
        let a = tx.query_row(ATTEMPT, [attempt], read_attempt)?;
        let publication =
            if closed || a.state != "running" || expires <= now || a.deadline_ms <= now {
                Publication::Suppressed
            } else if output.len() as i64 > cap {
                Publication::OutputLimit
            } else {
                Publication::Published(output.to_vec())
            };
        let retained = match &publication {
            Publication::Published(v) => Some(v.as_slice()),
            _ => None,
        };
        tx.execute(
            "UPDATE calls SET state='settled',consumed_tokens=?2,output=?3 WHERE id=?1",
            params![id, tokens, retained],
        )?;
        tx.commit()?;
        Ok(publication)
    }
    pub fn inspect(&self, id: &str) -> Result<Inspection> {
        let attempt = self.db.query_row(ATTEMPT, [id], read_attempt)?;
        let calls=self.db.prepare("SELECT id,request_key,state,consumed_tokens,deadline_ms,publication_closed FROM calls WHERE attempt_id=?1 ORDER BY rowid")?.query_map([id],read_call)?.collect::<rusqlite::Result<_>>()?;
        let evidence_gaps = self
            .db
            .prepare("SELECT reason FROM gaps WHERE attempt_id=?1 ORDER BY reason")?
            .query_map([id], |r| r.get(0))?
            .collect::<rusqlite::Result<_>>()?;
        let mut inspection = Inspection {
            attempt,
            calls,
            evidence_gaps,
            denials_omitted: 0,
            robot_binding: self.robot_binding(id)?,
            robot_requests: self
                .robot_intents(id)?
                .iter()
                .map(crate::robot::Intent::summary)
                .collect(),
            denials: self
                .db
                .prepare(
                    "SELECT request_key,method FROM denials WHERE attempt_id=?1 ORDER BY rowid",
                )?
                .query_map([id], |r| {
                    Ok(Denial {
                        request_key: r.get(0)?,
                        method: r.get(1)?,
                        reason: "method_not_allowed".into(),
                    })
                })?
                .collect::<rusqlite::Result<_>>()?,
        };
        // Untrusted denied method strings may expand sixfold in JSON. Keep
        // status usable while retaining every raw record in the durable store.
        while serde_json::to_vec(&inspection)?.len() > crate::protocol::MAX_MESSAGE - 1024 {
            ensure!(
                inspection.denials.pop().is_some(),
                "inspection metadata exceeds response cap"
            );
            inspection.denials_omitted += 1;
        }
        Ok(inspection)
    }
    /// Read an existing result only; this never allocates or dispatches work.
    pub fn result(
        &self,
        attempt: &str,
        request_key: &str,
        now: i64,
    ) -> Result<(Reservation, Option<Vec<u8>>)> {
        key(request_key)?;
        Ok(self.db.query_row(
            "SELECT calls.id,request_key,calls.state,consumed_tokens,calls.deadline_ms,publication_closed,
             CASE WHEN calls.state='settled' AND publication_closed=0 AND attempts.state='running'
               AND calls.deadline_ms>?3 AND attempts.deadline_ms>?3 THEN output ELSE NULL END
             FROM calls JOIN attempts ON attempts.id=calls.attempt_id WHERE attempt_id=?1 AND request_key=?2",
            params![attempt,request_key,now], |row| Ok((read_call(row)?, row.get(6)?)))?)
    }
    pub fn attempts(&self) -> Result<Vec<Attempt>> {
        Ok(self.db.prepare("SELECT id,artifact_digest,state,deadline_ms,binding,outcome FROM attempts ORDER BY rowid")?.query_map([],read_attempt)?.collect::<rusqlite::Result<_>>()?)
    }
}
