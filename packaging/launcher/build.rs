#[cfg(windows)]
fn main() {
    use std::env;
    use std::path::PathBuf;

    // Reuse the main application icon so the desktop shortcut and taskbar entry stay consistent
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let icon_path = PathBuf::from(manifest_dir)
        .join("..")
        .join("..")
        .join("yakulingo")
        .join("ui")
        .join("yakulingo.ico");

    let mut res = winres::WindowsResource::new();
    let icon_path_str = icon_path
        .to_str()
        .expect("Icon path contains invalid UTF-8 characters");

    res.set_icon(icon_path_str)
        .set("ProductName", "YakuLingo")
        .set("FileDescription", "YakuLingo Translation Tool")
        .set("CompanyName", "YakuLingo")
        .set("LegalCopyright", "MIT License");

    if let Err(e) = res.compile() {
        eprintln!("Warning: Failed to compile Windows resource: {}", e);
        // Don't fail the build - icon is optional
    }
}

#[cfg(not(windows))]
fn main() {
    // No resource compilation needed on non-Windows platforms
}
