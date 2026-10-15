use anyhow::{bail, Result};
fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let value = if args.len() == 5
        && args[0] == "import"
        && args[1] == "--layout"
        && args[3] == "--digest"
    {
        actryn_server::artifact::import(std::path::Path::new(&args[2]), &args[4])?
    } else if args.len() == 3 && args[0] == "discard-incomplete" && args[1] == "--digest" {
        actryn_server::artifact::discard_incomplete(&args[2])?
    } else {
        bail!("usage: actryn-artifact import --layout ROOT_OWNED_OCI_DIR --digest sha256:MANIFEST | discard-incomplete --digest sha256:MANIFEST")
    };
    println!("{value}");
    Ok(())
}
