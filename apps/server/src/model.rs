use crate::broker::BoundedOutput;
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Duration;
pub const MODEL: &str = "gpt-5.4-mini-2026-03-17";
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelInput {
    pub goal: String,
    pub observation_id: String,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Proposal {
    pub left_delta_ticks: i64,
    pub right_delta_ticks: i64,
    pub duration_ms: i64,
}
impl Proposal {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            (-100..=100).contains(&self.left_delta_ticks)
                && (-100..=100).contains(&self.right_delta_ticks)
                && (1..=10000).contains(&self.duration_ms),
            "model proposal exceeds fixed skill bounds"
        );
        Ok(())
    }
}
pub fn request_body(input: &ModelInput) -> Result<Value> {
    ensure!(
        !input.goal.is_empty() && input.goal.len() <= 4096,
        "invalid goal length"
    );
    ensure!(
        !input.observation_id.is_empty() && input.observation_id.len() <= 128,
        "invalid observation identity"
    );
    Ok(
        json!({"model":MODEL,"store":false,"background":false,"max_output_tokens":1024,"tools":[],
        "instructions":"Propose one restrained simulated wheel index step. Return signed left_delta_ticks and right_delta_ticks in [-100,100] and duration_ms in [1,10000]. This proposal grants no authority. No tools are available.",
        "input":input.goal,"text":{"format":{"type":"json_schema","name":"wheel_index_step","strict":true,
            "schema":{"type":"object","additionalProperties":false,"required":["left_delta_ticks","right_delta_ticks","duration_ms"],
                "properties":{"left_delta_ticks":{"type":"integer","minimum":-100,"maximum":100},"right_delta_ticks":{"type":"integer","minimum":-100,"maximum":100},"duration_ms":{"type":"integer","minimum":1,"maximum":10000}}}}}}),
    )
}
pub fn decode_completed(response: &Value) -> Result<(Proposal, i64)> {
    ensure!(
        response["status"] == "completed" && response["model"] == MODEL,
        "model result incomplete or wrong model"
    );
    let tokens = response["usage"]["output_tokens"]
        .as_i64()
        .context("missing provider usage")?;
    ensure!(
        (0..=1024).contains(&tokens),
        "provider output reservation exceeded"
    );
    let output = response["output"]
        .as_array()
        .context("missing model output")?;
    let mut text = None;
    for item in output {
        if item["type"] == "message" {
            for content in item["content"]
                .as_array()
                .context("missing message content")?
            {
                ensure!(
                    content["type"] == "output_text" && text.is_none(),
                    "refused or ambiguous model output"
                );
                text = Some(content["text"].as_str().context("missing output text")?);
            }
        } else {
            ensure!(item["type"] == "reasoning", "unexpected hosted tool output");
        }
    }
    let proposal: Proposal = serde_json::from_str(text.context("no proposal")?)?;
    proposal.validate()?;
    Ok((proposal, tokens))
}
/// A transport failure keeps the previously committed reservation unresolved.
pub async fn live(input: &ModelInput, key: &str) -> Result<(Proposal, i64)> {
    let body = request_body(input)?;
    let client = reqwest::Client::builder()
        .https_only(true)
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(30))
        .build()?;
    let mut response = client
        .post("https://api.openai.com/v1/responses")
        .bearer_auth(key)
        .json(&body)
        .send()
        .await?;
    ensure!(
        response.status().is_success(),
        "provider returned HTTP {}; reservation unresolved",
        response.status()
    );
    let mut output = BoundedOutput::new(65536)?;
    while let Some(chunk) = response.chunk().await? {
        output.push(&chunk)?;
    }
    decode_completed(&serde_json::from_slice(&output.finish()?)?)
}
