//! YakuLingo Launcher
//!
//! Lightweight native launcher for YakuLingo application.
//! - No console window
//! - Duplicate instance prevention
//! - Portable path handling (fixes pyvenv.cfg)
//! - Environment variable setup

#![windows_subsystem = "windows"]

use std::env;
use std::fs;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const APP_PORT: u16 = 8765;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

fn main() {
    if let Err(e) = run() {
        show_error(&e);
    }
}

fn run() -> Result<(), String> {
    // Get executable directory
    let exe_path = env::current_exe()
        .map_err(|e| format!("Failed to get executable path: {}", e))?;
    let base_dir = exe_path
        .parent()
        .ok_or("Failed to get executable directory")?
        .to_path_buf();

    // Check if already running
    if is_app_running(APP_PORT) {
        show_info("YakuLingo is already running.");
        return Ok(());
    }

    // Find Python directory in .uv-python
    let python_dir = find_python_dir(&base_dir)?;

    // Check venv exists
    let venv_dir = base_dir.join(".venv");
    // Use python.exe (not pythonw.exe) for better subprocess compatibility
    // Console is hidden via CREATE_NO_WINDOW flag
    let python_exe = venv_dir.join("Scripts").join("python.exe");

    if !python_exe.exists() {
        return Err(".venv not found.\n\nPlease reinstall the application.".to_string());
    }

    // Fix pyvenv.cfg for portability
    fix_pyvenv_cfg(&venv_dir, &python_dir)?;

    // Setup environment variables
    setup_environment(&base_dir, &venv_dir, &python_dir);

    // Launch application
    let app_script = base_dir.join("app.py");
    launch_app(&python_exe, &app_script, &base_dir)?;

    Ok(())
}

/// Check if the application is already running by attempting TCP connection
fn is_app_running(port: u16) -> bool {
    let addr = format!("127.0.0.1:{}", port);
    // Reduced timeout from 500ms to 100ms for faster startup when app isn't running
    TcpStream::connect_timeout(
        &addr.parse().unwrap(),
        Duration::from_millis(100),
    )
    .is_ok()
}

/// Find Python directory in .uv-python (cpython-*)
fn find_python_dir(base_dir: &PathBuf) -> Result<PathBuf, String> {
    let uv_python_dir = base_dir.join(".uv-python");

    if !uv_python_dir.exists() {
        return Err("Python not found in .uv-python directory.\n\nPlease reinstall the application.".to_string());
    }

    let entries = fs::read_dir(&uv_python_dir)
        .map_err(|e| format!("Failed to read .uv-python directory: {}", e))?;

    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if name_str.starts_with("cpython-") && entry.path().is_dir() {
            return Ok(entry.path());
        }
    }

    Err("Python not found in .uv-python directory.\n\nPlease reinstall the application.".to_string())
}

/// Fix pyvenv.cfg home path for portability (only if needed)
fn fix_pyvenv_cfg(venv_dir: &PathBuf, python_dir: &PathBuf) -> Result<(), String> {
    let cfg_path = venv_dir.join("pyvenv.cfg");

    if !cfg_path.exists() {
        return Ok(()); // Skip if not exists
    }

    // Read existing config
    let mut current_content = String::new();
    let mut version_line = String::new();
    let mut current_home = String::new();

    if let Ok(mut file) = fs::File::open(&cfg_path) {
        if file.read_to_string(&mut current_content).is_ok() {
            for line in current_content.lines() {
                let lower = line.to_lowercase();
                if lower.starts_with("version") {
                    version_line = line.to_string();
                } else if lower.starts_with("home") {
                    // Extract current home path
                    if let Some(pos) = line.find('=') {
                        current_home = line[pos + 1..].trim().to_string();
                    }
                }
            }
        }
    }

    // Check if home path is already correct
    let expected_home = python_dir.display().to_string();
    if current_home == expected_home {
        return Ok(()); // Already correct, skip rewrite
    }

    // Write new config with correct home path
    let mut new_content = format!(
        "home = {}\ninclude-system-site-packages = false\n",
        expected_home
    );
    if !version_line.is_empty() {
        new_content.push_str(&version_line);
        new_content.push('\n');
    }

    fs::write(&cfg_path, new_content)
        .map_err(|e| format!("Failed to write pyvenv.cfg: {}", e))?;

    Ok(())
}

/// Setup environment variables
fn setup_environment(base_dir: &PathBuf, venv_dir: &PathBuf, python_dir: &PathBuf) {
    // VIRTUAL_ENV
    env::set_var("VIRTUAL_ENV", venv_dir);

    // PLAYWRIGHT_BROWSERS_PATH
    let playwright_path = base_dir.join(".playwright-browsers");
    env::set_var("PLAYWRIGHT_BROWSERS_PATH", &playwright_path);

    // pywebview web engine (avoid runtime installation dialog)
    env::set_var("PYWEBVIEW_GUI", "edgechromium");

    // Proxy bypass for localhost (avoids corporate proxy delays)
    env::set_var("NO_PROXY", "localhost,127.0.0.1");

    // Disable Python output buffering (slightly faster startup)
    env::set_var("PYTHONUNBUFFERED", "1");

    // PATH - prepend venv and python directories
    let venv_scripts = venv_dir.join("Scripts");
    let python_scripts = python_dir.join("Scripts");

    let old_path = env::var("PATH").unwrap_or_default();
    let new_path = format!(
        "{};{};{};{}",
        venv_scripts.display(),
        python_dir.display(),
        python_scripts.display(),
        old_path
    );
    env::set_var("PATH", new_path);
}

/// Launch the application
#[cfg(windows)]
fn launch_app(python_exe: &PathBuf, app_script: &PathBuf, working_dir: &PathBuf) -> Result<(), String> {
    Command::new(python_exe)
        .arg(app_script)
        .current_dir(working_dir)
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map_err(|e| format!("Failed to start application: {}", e))?;

    Ok(())
}

#[cfg(not(windows))]
fn launch_app(python_exe: &PathBuf, app_script: &PathBuf, working_dir: &PathBuf) -> Result<(), String> {
    Command::new(python_exe)
        .arg(app_script)
        .current_dir(working_dir)
        .spawn()
        .map_err(|e| format!("Failed to start application: {}", e))?;

    Ok(())
}

/// Show error message box (Windows) or print to stderr
#[cfg(windows)]
fn show_error(message: &str) {
    use std::ffi::OsStr;
    use std::iter::once;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::null_mut;

    let wide_message: Vec<u16> = OsStr::new(message)
        .encode_wide()
        .chain(once(0))
        .collect();
    let wide_title: Vec<u16> = OsStr::new("YakuLingo - Error")
        .encode_wide()
        .chain(once(0))
        .collect();

    unsafe {
        winapi::um::winuser::MessageBoxW(
            null_mut(),
            wide_message.as_ptr(),
            wide_title.as_ptr(),
            winapi::um::winuser::MB_ICONERROR | winapi::um::winuser::MB_OK,
        );
    }
}

#[cfg(not(windows))]
fn show_error(message: &str) {
    eprintln!("Error: {}", message);
}

/// Show info message box (Windows) or print to stdout
#[cfg(windows)]
fn show_info(message: &str) {
    use std::ffi::OsStr;
    use std::iter::once;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::null_mut;

    let wide_message: Vec<u16> = OsStr::new(message)
        .encode_wide()
        .chain(once(0))
        .collect();
    let wide_title: Vec<u16> = OsStr::new("YakuLingo")
        .encode_wide()
        .chain(once(0))
        .collect();

    unsafe {
        winapi::um::winuser::MessageBoxW(
            null_mut(),
            wide_message.as_ptr(),
            wide_title.as_ptr(),
            winapi::um::winuser::MB_ICONINFORMATION | winapi::um::winuser::MB_OK,
        );
    }
}

#[cfg(not(windows))]
fn show_info(message: &str) {
    println!("{}", message);
}
