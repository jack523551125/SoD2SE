fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }
    let vendor = std::path::Path::new("../../Native/vendor/minhook");
    println!("cargo:rerun-if-changed={}", vendor.display());
    let mut build = cc::Build::new();
    build
        .include(vendor.join("include"))
        .include(vendor.join("src"));
    for file in ["buffer.c", "hook.c", "trampoline.c", "hde/hde64.c"] {
        build.file(vendor.join("src").join(file));
    }
    build.compile("sod2se_minhook");
}
