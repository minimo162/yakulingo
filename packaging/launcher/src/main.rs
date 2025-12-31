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
use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const APP_PORT: u16 = 8765;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
const USER_EXIT_CODE: i32 = 10;
const UPDATE_IN_PROGRESS_CODE: i32 = 20;
const MAX_RESTARTS: u32 = 3;
const RESTART_BACKOFF_BASE_SEC: u64 = 1;
const RESTART_RESET_AFTER_SEC: u64 = 60;
const LAUNCHER_STATE_TTL_SEC: u64 = 300;

fn main() {
    if let Err(e) = run() {
        show_error(&e);
    }
}

fn run() -> Result<(), String> {
    // Get executable directory
    let exe_path =
        env::current_exe().map_err(|e| format!("Failed to get executable path: {}", e))?;
    let base_dir = exe_path
        .parent()
        .ok_or("Failed to get executable directory")?
        .to_path_buf();

    let log_path = init_log_path(&base_dir);
    log_event(
        &log_path,
        &format!("Launcher start (exe: {:?}, base: {:?})", exe_path, base_dir),
    );

    // Check if already running
    if is_app_running(APP_PORT) {
        log_event(
            &log_path,
            "Application already running - focusing existing window",
        );
        if !bring_window_to_front() {
            show_info("YakuLingo is already running.");
        }
        return Ok(());
    }

    // Find Python directory in .uv-python
    let python_dir = find_python_dir(&base_dir)?;
    log_event(&log_path, &format!("Using Python dir: {:?}", python_dir));

    // Check venv exists
    let venv_dir = base_dir.join(".venv");
    // Use python.exe (not pythonw.exe) for better subprocess compatibility
    // Console is hidden via CREATE_NO_WINDOW flag
    let python_exe = venv_dir.join("Scripts").join("python.exe");

    if !python_exe.exists() {
        log_event(&log_path, ".venv not found - aborting");
        return Err(".venv not found.\n\nPlease reinstall the application.".to_string());
    }

    // Fix pyvenv.cfg for portability
    fix_pyvenv_cfg(&venv_dir, &python_dir)?;
    log_event(&log_path, "pyvenv.cfg patched");

    // Setup environment variables
    setup_environment(&base_dir, &venv_dir, &python_dir);
    log_event(&log_path, "Environment variables configured");

    // Launch application and keep a watchdog loop
    let app_script = base_dir.join("app.py");
    let launcher_state_path = get_launcher_state_path(&base_dir);
    let mut restart_attempts: u32 = 0;
    let mut backoff = Duration::from_secs(RESTART_BACKOFF_BASE_SEC);

    loop {
        let start_time = Instant::now();
        let mut child = launch_app(&python_exe, &app_script, &base_dir, &log_path)?;
        log_event(&log_path, "Python process spawned, watchdog active");

        let status = child
            .wait()
            .map_err(|e| format!("Failed to wait for application: {}", e))?;
        let exit_code = status.code().unwrap_or(-1);
        let elapsed = start_time.elapsed();

        if let Some(reason) =
            read_and_clear_launcher_state(&launcher_state_path, &log_path)
        {
            log_event(
                &log_path,
                &format!("Launcher state detected ({}) - stopping restart", reason),
            );
            break;
        }

        if exit_code == USER_EXIT_CODE {
            log_event(
                &log_path,
                "Explicit user exit detected (exit code 10) - stopping restart",
            );
            break;
        }

        if exit_code == UPDATE_IN_PROGRESS_CODE {
            log_event(
                &log_path,
                "Update in progress detected (exit code 20) - stopping restart",
            );
            break;
        }

        if elapsed > Duration::from_secs(RESTART_RESET_AFTER_SEC) {
            restart_attempts = 0;
            backoff = Duration::from_secs(RESTART_BACKOFF_BASE_SEC);
        }

        if restart_attempts >= MAX_RESTARTS {
            log_event(
                &log_path,
                &format!(
                    "Restart limit reached (exit code {}) - watchdog stopping",
                    exit_code
                ),
            );
            break;
        }

        log_event(
            &log_path,
            &format!(
                "UI exited (code {}), restarting in {}s (attempt {}/{})",
                exit_code,
                backoff.as_secs(),
                restart_attempts + 1,
                MAX_RESTARTS
            ),
        );
        thread::sleep(backoff);
        restart_attempts += 1;
        backoff = Duration::from_secs(backoff.as_secs().saturating_mul(2).max(1));
    }

    Ok(())
}

/// Attempt to bring existing YakuLingo window to the foreground when already running.
#[cfg(windows)]
fn bring_window_to_front() -> bool {
    use std::ffi::OsString;
    use std::os::windows::ffi::OsStringExt;
    use winapi::shared::minwindef::{BOOL, LPARAM};
    use winapi::shared::windef::HWND;
    use winapi::um::winuser::{
        EnumWindows, GetForegroundWindow, GetWindowTextLengthW, GetWindowTextW, IsIconic,
        SetForegroundWindow, ShowWindow, SW_RESTORE, SW_SHOW,
    };

    #[derive(Default)]
    struct WindowSearch {
        handle: Option<HWND>,
    }

    unsafe extern "system" fn enum_proc(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let search = &mut *(lparam as *mut WindowSearch);

        // Skip invisible windows
        if GetWindowTextLengthW(hwnd) == 0 {
            return 1; // TRUE to continue
        }

        let length = GetWindowTextLengthW(hwnd) as usize;
        let mut buffer = vec![0u16; length + 1];
        let read_len = GetWindowTextW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32);
        if read_len <= 0 {
            return 1;
        }

        buffer.truncate(read_len as usize);
        let title = OsString::from_wide(&buffer).to_string_lossy().to_string();

        if title.contains("YakuLingo") {
            search.handle = Some(hwnd);
            return 0; // FALSE to stop enumeration
        }

        1
    }

    let mut search = WindowSearch::default();
    let search_ptr: *mut WindowSearch = &mut search;

    unsafe {
        EnumWindows(Some(enum_proc), search_ptr as LPARAM);

        if let Some(hwnd) = search.handle {
            if IsIconic(hwnd) != 0 {
                ShowWindow(hwnd, SW_RESTORE);
            } else {
                ShowWindow(hwnd, SW_SHOW);
            }

            if GetForegroundWindow() != hwnd {
                SetForegroundWindow(hwnd);
            }

            return true;
        }
    }

    false
}

#[cfg(not(windows))]
fn bring_window_to_front() -> bool {
    false
}

fn init_log_path(base_dir: &PathBuf) -> Option<PathBuf> {
    let mut candidate = env::var("LOCALAPPDATA")
        .map(PathBuf::from)
        .map(|p| p.join("YakuLingo").join("logs"))
        .ok();

    if candidate.is_none() {
        candidate = Some(base_dir.join("logs"));
    }

    if let Some(dir) = candidate {
        if fs::create_dir_all(&dir).is_ok() {
            return Some(dir.join("launcher.log"));
        }
    }

    None
}

fn log_event(log_path: &Option<PathBuf>, message: &str) {
    if let Some(path) = log_path {
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
            let timestamp = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_else(|_| Duration::from_secs(0))
                .as_secs();
            let _ = writeln!(file, "[{}] {}", timestamp, message);
        }
    }
}

fn get_launcher_state_path(base_dir: &PathBuf) -> Option<PathBuf> {
    if let Ok(home) = env::var("USERPROFILE").or_else(|_| env::var("HOME")) {
        return Some(PathBuf::from(home).join(".yakulingo").join("launcher_state.json"));
    }
    Some(base_dir.join("launcher_state.json"))
}

fn read_and_clear_launcher_state(
    path: &Option<PathBuf>,
    log_path: &Option<PathBuf>,
) -> Option<String> {
    let path = path.as_ref()?;
    if !path.exists() {
        return None;
    }
    let content = match fs::read_to_string(path) {
        Ok(value) => value,
        Err(err) => {
            log_event(
                log_path,
                &format!("Failed to read launcher state: {}", err),
            );
            return None;
        }
    };
    let reason = if content.contains("update_in_progress") {
        Some("update_in_progress")
    } else if content.contains("user_exit") {
        Some("user_exit")
    } else {
        None
    };

    let reason = match reason {
        Some(value) => value,
        None => {
            log_event(log_path, "Unknown launcher state reason; clearing file");
            let _ = fs::remove_file(path);
            return None;
        }
    };

    let now_secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0))
        .as_secs();
    let ts_secs = match parse_launcher_state_ts(&content) {
        Some(value) => value,
        None => {
            log_event(log_path, "Invalid launcher state timestamp; clearing file");
            let _ = fs::remove_file(path);
            return None;
        }
    };

    if now_secs < ts_secs || now_secs - ts_secs > LAUNCHER_STATE_TTL_SEC {
        log_event(log_path, "Stale launcher state detected; clearing file");
        let _ = fs::remove_file(path);
        return None;
    }

    let _ = fs::remove_file(path);
    Some(reason.to_string())
}

fn parse_launcher_state_ts(content: &str) -> Option<u64> {
    let ts_idx = content.find("\"ts\"")?;
    let after_key = &content[ts_idx + 4..];
    let colon_idx = after_key.find(':')?;
    let mut slice = after_key[colon_idx + 1..].trim_start();
    let mut end = 0usize;
    for ch in slice.chars() {
        if ch.is_ascii_digit() || ch == '.' {
            end += ch.len_utf8();
        } else {
            break;
        }
    }
    if end == 0 {
        return None;
    }
    let num = &slice[..end];
    let value: f64 = num.parse().ok()?;
    if value.is_sign_negative() {
        return None;
    }
    Some(value.floor() as u64)
}

/// Check if the application is already running by attempting TCP connection
fn is_app_running(port: u16) -> bool {
    let addr = format!("127.0.0.1:{}", port);
    // Reduced timeout from 500ms to 100ms for faster startup when app isn't running
    TcpStream::connect_timeout(&addr.parse().unwrap(), Duration::from_millis(100)).is_ok()
}

/// Find Python directory in .uv-python (cpython-*)
fn find_python_dir(base_dir: &PathBuf) -> Result<PathBuf, String> {
    let uv_python_dir = base_dir.join(".uv-python");

    if !uv_python_dir.exists() {
        return Err(
            "Python not found in .uv-python directory.\n\nPlease reinstall the application."
                .to_string(),
        );
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

    Err(
        "Python not found in .uv-python directory.\n\nPlease reinstall the application."
            .to_string(),
    )
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

    fs::write(&cfg_path, new_content).map_err(|e| format!("Failed to write pyvenv.cfg: {}", e))?;

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

/// Launch the application and wait for window to appear
/// This keeps the launcher process alive until the window is shown,
/// which maintains the Windows busy cursor (loading circle) until the app is ready.
#[cfg(windows)]
fn launch_app(
    python_exe: &PathBuf,
    app_script: &PathBuf,
    working_dir: &PathBuf,
    log_path: &Option<PathBuf>,
) -> Result<Child, String> {
    let mut command = Command::new(python_exe);
    command
        .arg(app_script)
        .current_dir(working_dir)
        .creation_flags(CREATE_NO_WINDOW);

    if env::var("YAKULINGO_NO_AUTO_OPEN").is_err() {
        command.env("YAKULINGO_NO_AUTO_OPEN", "1");
    }
    if env::var("YAKULINGO_LAUNCH_SOURCE").is_err() {
        command.env("YAKULINGO_LAUNCH_SOURCE", "launcher");
    }
    command.env("YAKULINGO_WATCHDOG", "1");

    let child = command
        .spawn()
        .map_err(|e| format!("Failed to start application: {}", e))?;

    log_event(log_path, "Python process spawned, waiting for window");

    // Wait for YakuLingo window to appear
    // This keeps the launcher alive, maintaining the Windows busy cursor
    wait_for_window("YakuLingo", Duration::from_secs(30));

    Ok(child)
}

/// Wait for a window with the specified title to appear
#[cfg(windows)]
fn wait_for_window(title: &str, timeout: Duration) {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use std::thread;
    use winapi::um::winuser::FindWindowW;

    let wide_title: Vec<u16> = OsStr::new(title)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    let start = std::time::Instant::now();
    let poll_interval = Duration::from_millis(100);

    while start.elapsed() < timeout {
        unsafe {
            let hwnd = FindWindowW(std::ptr::null(), wide_title.as_ptr());
            if !hwnd.is_null() {
                // Window found, exit the loop
                return;
            }
        }
        thread::sleep(poll_interval);
    }
    // Timeout reached, exit anyway (app might still be starting)
}

#[cfg(not(windows))]
fn launch_app(
    python_exe: &PathBuf,
    app_script: &PathBuf,
    working_dir: &PathBuf,
    _log_path: &Option<PathBuf>,
) -> Result<Child, String> {
    let mut command = Command::new(python_exe);
    command
        .arg(app_script)
        .current_dir(working_dir);

    if env::var("YAKULINGO_NO_AUTO_OPEN").is_err() {
        command.env("YAKULINGO_NO_AUTO_OPEN", "1");
    }
    if env::var("YAKULINGO_LAUNCH_SOURCE").is_err() {
        command.env("YAKULINGO_LAUNCH_SOURCE", "launcher");
    }
    command.env("YAKULINGO_WATCHDOG", "1");

    command
        .spawn()
        .map_err(|e| format!("Failed to start application: {}", e))
}

/// Show error message box (Windows) or print to stderr
#[cfg(windows)]
fn show_error(message: &str) {
    use std::ffi::OsStr;
    use std::iter::once;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::null_mut;

    let wide_message: Vec<u16> = OsStr::new(message).encode_wide().chain(once(0)).collect();
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

    let wide_message: Vec<u16> = OsStr::new(message).encode_wide().chain(once(0)).collect();
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
