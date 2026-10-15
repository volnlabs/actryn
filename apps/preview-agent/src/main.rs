use std::io::Write;
fn main() {
    match actryn_preview_agent::run() {
        Ok(value) => {
            println!(
                "{}",
                serde_json::json!({"event":"preview_proposal","skill":"wheel.index_step.v1","authority_issued":false,"value":value})
            );
            let _ = std::io::stdout().flush();
            // Keep broker publication available for explicit operator inspection, within the attempt ceiling.
            std::thread::sleep(std::time::Duration::from_secs(60));
        }
        Err(error) => {
            eprintln!(
                "{}",
                serde_json::json!({"event":"preview_error","message":error.to_string(),"automatic_retry":false,"next_action":"inspect_existing_attempt_and_request_key"})
            );
            std::process::exit(1);
        }
    }
}
