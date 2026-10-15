fn main() {
    println!("cargo:rerun-if-changed=../../schemas/robot-v1.proto");
    prost_build::Config::new()
        .compile_protos(&["../../schemas/robot-v1.proto"], &["../../schemas"])
        .expect("compile fixed Robot RPC schema");
}
