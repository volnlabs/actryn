#[tokio::main]
async fn main() {
    let result = match actryn_cli::command::run(std::env::args().skip(1).collect()).await {
        Ok(value) => value,
        Err(error) => {
            serde_json::json!({"result":"error","code":"invalid_input_or_local_state","message":format!("{error:#}"),"outcome_unknown":false,"automatic_retry":false})
        }
    };
    let failure = result["result"] == "error";
    println!(
        "{}",
        serde_json::to_string(&result).expect("JSON value serialization")
    );
    if failure {
        std::process::exit(1);
    }
}
