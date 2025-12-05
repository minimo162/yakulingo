#[cfg(windows)]
fn main() {
    let mut res = winres::WindowsResource::new();
    res.set_icon("icon/yakulingo.ico")
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
