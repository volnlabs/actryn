#[tokio::main]
async fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let outcome = match actryn_cli::command::installation_command(&args) {
        Ok(Some(mut command)) => {
            use std::os::unix::process::CommandExt;
            Err(command.exec().into())
        }
        Ok(None) => actryn_cli::command::run(args).await,
        Err(error) => Err(error),
    };
    let result = match outcome {
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
