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
use std::io::{ErrorKind, Read, Write};
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
const INSTANCE_ALREADY_RUNNING_CODE: i32 = 11;
const UPDATE_IN_PROGRESS_CODE: i32 = 20;
const MAX_RESTARTS: u32 = 3;
const RESTART_BACKOFF_BASE_SEC: u64 = 1;
const RESTART_RESET_AFTER_SEC: u64 = 60;
const LAUNCHER_STATE_TTL_SEC: u64 = 300;
const INSTANCE_MUTEX_NAME: &str = "Local\\YakuLingoSingleton";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum AppStatus {
    NotRunning,
    Running,
    PortInUse,
}

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
    let allow_multi_instance = env::var("YAKULINGO_ALLOW_MULTI_INSTANCE")
        .map(|value| value == "1")
        .unwrap_or(false);
    let mutex_present = if allow_multi_instance {
        false
    } else {
        is_instance_mutex_present()
    };
    let app_status = check_app_status(APP_PORT);
    if mutex_present || app_status == AppStatus::Running {
        log_event(
            &log_path,
            "Application already running - focusing existing window",
        );
        if !bring_window_to_front() && !request_activate(APP_PORT) {
            show_info("YakuLingo is already running.");
        }
        return Ok(());
    }
    if app_status == AppStatus::PortInUse {
        log_event(&log_path, "Port 8765 is in use by another application");
        return Err(
            "Port 8765 is already in use.\n\nPlease close the other application and try again."
                .to_string(),
        );
    }

    // Check venv exists
    let venv_dir = base_dir.join(".venv");
    // Use python.exe (not pythonw.exe) for better subprocess compatibility
    // Console is hidden via CREATE_NO_WINDOW flag
    let python_exe = venv_dir.join("Scripts").join("python.exe");

    if !python_exe.exists() {
        log_event(&log_path, ".venv not found - aborting");
        return Err(".venv not found.\n\nPlease reinstall the application.".to_string());
    }

    // Find Python directory in .uv-python (or pyvenv.cfg home)
    let python_dir = find_python_dir(&base_dir, &venv_dir, &log_path)?;
    log_event(&log_path, &format!("Using Python dir: {:?}", python_dir));

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

        if exit_code == INSTANCE_ALREADY_RUNNING_CODE {
            log_event(
                &log_path,
                "Existing instance detected (exit code 11) - stopping restart",
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
        EnumWindows, GetClassNameW, GetForegroundWindow, GetWindowTextLengthW, GetWindowTextW,
        IsIconic, SetForegroundWindow, ShowWindow, SW_RESTORE, SW_SHOW,
    };

    fn is_window_title_with_boundary(title: &str, base_title: &str) -> bool {
        if title.is_empty() || base_title.is_empty() {
            return false;
        }
        if title == base_title {
            return true;
        }
        match title.strip_prefix(base_title) {
            Some(rest) => match rest.chars().next() {
                Some(ch) => ch.is_whitespace(),
                None => false,
            },
            None => false,
        }
    }

    #[derive(Default)]
    struct WindowSearch {
        handle: Option<HWND>,
    }

    unsafe extern "system" fn enum_proc(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let search = &mut *(lparam as *mut WindowSearch);

        // Skip windows with no title
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

        if title.starts_with("Setup - YakuLingo") {
            return 1;
        }

        // Avoid matching File Explorer windows like "YakuLingo - エクスプローラー".
        let mut class_buf = [0u16; 256];
        let class_len = GetClassNameW(hwnd, class_buf.as_mut_ptr(), class_buf.len() as i32);
        if class_len > 0 {
            let class_name = OsString::from_wide(&class_buf[..class_len as usize])
                .to_string_lossy()
                .to_string();
            if class_name == "CabinetWClass" || class_name == "ExploreWClass" {
                return 1;
            }
        }

        // Avoid matching unrelated windows like "YakuLingo.html ...".
        if is_window_title_with_boundary(&title, "YakuLingo") {
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

#[cfg(windows)]
fn is_instance_mutex_present() -> bool {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use winapi::shared::minwindef::FALSE;
    use winapi::um::handleapi::CloseHandle;
    use winapi::um::synchapi::OpenMutexW;
    use winapi::um::winnt::SYNCHRONIZE;

    let wide_name: Vec<u16> = OsStr::new(INSTANCE_MUTEX_NAME)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    unsafe {
        let handle = OpenMutexW(SYNCHRONIZE, FALSE, wide_name.as_ptr());
        if handle.is_null() {
            return false;
        }
        CloseHandle(handle);
    }
    true
}

#[cfg(not(windows))]
fn is_instance_mutex_present() -> bool {
    false
}

fn request_activate(port: u16) -> bool {
    let addr = format!("127.0.0.1:{}", port);
    let mut stream = match TcpStream::connect_timeout(&addr.parse().unwrap(), Duration::from_millis(200)) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let request = b"POST /api/activate HTTP/1.1\r\nHost: 127.0.0.1\r\nX-YakuLingo-Activate: 1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
    stream.write_all(request).is_ok()
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

fn get_home_dir() -> Option<PathBuf> {
    if cfg!(windows) {
        if let Ok(profile) = env::var("USERPROFILE") {
            return Some(PathBuf::from(profile));
        }
        let drive = env::var("HOMEDRIVE").ok();
        let path = env::var("HOMEPATH").ok();
        if let (Some(drive), Some(path)) = (drive, path) {
            return Some(PathBuf::from(format!("{}{}", drive, path)));
        }
    }
    env::var("HOME").ok().map(PathBuf::from)
}

fn get_launcher_state_path(base_dir: &PathBuf) -> Option<PathBuf> {
    if let Some(home) = get_home_dir() {
        return Some(home.join(".yakulingo").join("launcher_state.json"));
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

/// Check if the application is already running by probing a local API endpoint.
fn check_app_status(port: u16) -> AppStatus {
    let addr = format!("127.0.0.1:{}", port);
    let mut stream = match TcpStream::connect_timeout(&addr.parse().unwrap(), Duration::from_millis(150)) {
        Ok(value) => value,
        Err(_) => return AppStatus::NotRunning,
    };

    let _ = stream.set_read_timeout(Some(Duration::from_millis(200)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(200)));

    let request =
        b"GET /api/setup-status HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(request).is_err() {
        return AppStatus::PortInUse;
    }

    let mut response = String::new();
    let mut buffer = [0u8; 512];
    loop {
        match stream.read(&mut buffer) {
            Ok(0) => break,
            Ok(read) => {
                response.push_str(&String::from_utf8_lossy(&buffer[..read]));
                if response.len() >= 4096 {
                    break;
                }
            }
            Err(err) if err.kind() == ErrorKind::WouldBlock || err.kind() == ErrorKind::TimedOut => {
                break;
            }
            Err(_) => break,
        }
    }

    if response.is_empty() {
        return AppStatus::PortInUse;
    }
    if is_yakulingo_setup_response(&response) {
        AppStatus::Running
    } else {
        AppStatus::PortInUse
    }
}

fn is_yakulingo_setup_response(response: &str) -> bool {
    let status_line = response.lines().next().unwrap_or("");
    if !status_line.contains(" 200 ") {
        return false;
    }

    let body = if let Some((_, body)) = response.split_once("\r\n\r\n") {
        body
    } else if let Some((_, body)) = response.split_once("\n\n") {
        body
    } else {
        ""
    };

    body.contains("\"ready\"") || body.contains("\"active\"")
}

fn read_pyvenv_home(venv_dir: &PathBuf) -> Option<PathBuf> {
    let cfg_path = venv_dir.join("pyvenv.cfg");
    if !cfg_path.exists() {
        return None;
    }
    let content = fs::read_to_string(&cfg_path).ok()?;
    for line in content.lines() {
        let lower = line.trim_start().to_lowercase();
        if lower.starts_with("home") {
            if let Some(pos) = line.find('=') {
                let value = line[pos + 1..].trim();
                if !value.is_empty() {
                    return Some(PathBuf::from(value));
                }
            }
        }
    }
    None
}

fn parse_cpython_version(name: &str) -> Option<(u32, u32, u32)> {
    if !name.starts_with("cpython-") {
        return None;
    }
    let tail = &name["cpython-".len()..];
    let version_part = tail.split('-').next()?;
    let mut iter = version_part.split('.');
    let major: u32 = iter.next()?.parse().ok()?;
    let minor: u32 = iter.next().unwrap_or("0").parse().ok()?;
    let patch: u32 = iter.next().unwrap_or("0").parse().ok()?;
    Some((major, minor, patch))
}

/// Find Python directory in .uv-python (cpython-*) or pyvenv.cfg home.
fn find_python_dir(
    base_dir: &PathBuf,
    venv_dir: &PathBuf,
    log_path: &Option<PathBuf>,
) -> Result<PathBuf, String> {
    if let Some(home) = read_pyvenv_home(venv_dir) {
        let resolved = if home.is_absolute() {
            home
        } else {
            base_dir.join(home)
        };
        if resolved.exists() {
            log_event(
                log_path,
                &format!("Using pyvenv.cfg home for Python dir: {:?}", resolved),
            );
            return Ok(resolved);
        }
        log_event(
            log_path,
            &format!("pyvenv.cfg home not found: {:?}", resolved),
        );
    }

    let uv_python_dir = base_dir.join(".uv-python");
    if !uv_python_dir.exists() {
        return Err(
            "Python not found in .uv-python directory.\n\nPlease reinstall the application."
                .to_string(),
        );
    }

    let entries = fs::read_dir(&uv_python_dir)
        .map_err(|e| format!("Failed to read .uv-python directory: {}", e))?;

    let mut candidates: Vec<(PathBuf, Option<(u32, u32, u32)>, Option<SystemTime>, String)> =
        Vec::new();
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().to_string();
        let path = entry.path();
        if name.starts_with("cpython-") && path.is_dir() {
            let version = parse_cpython_version(&name);
            let modified = fs::metadata(&path).and_then(|meta| meta.modified()).ok();
            candidates.push((path, version, modified, name));
        }
    }

    if candidates.is_empty() {
        return Err(
            "Python not found in .uv-python directory.\n\nPlease reinstall the application."
                .to_string(),
        );
    }

    candidates.sort_by(|a, b| {
        let (_, version_a, modified_a, name_a) = a;
        let (_, version_b, modified_b, name_b) = b;
        match (version_a, version_b) {
            (Some(va), Some(vb)) => vb.cmp(va),
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => std::cmp::Ordering::Equal,
        }
        .then_with(|| match (modified_a, modified_b) {
            (Some(ma), Some(mb)) => mb.cmp(ma),
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => std::cmp::Ordering::Equal,
        })
        .then_with(|| name_b.cmp(name_a))
    });

    let selected = candidates[0].0.clone();
    if candidates.len() > 1 {
        log_event(
            log_path,
            &format!(
                "Multiple Python dirs found in .uv-python; selected {:?}",
                selected
            ),
        );
    }

    Ok(selected)
}

/// Fix pyvenv.cfg home path for portability (only if needed)
fn fix_pyvenv_cfg(venv_dir: &PathBuf, python_dir: &PathBuf) -> Result<(), String> {
    let cfg_path = venv_dir.join("pyvenv.cfg");

    if !cfg_path.exists() {
        return Ok(()); // Skip if not exists
    }

    let current_content =
        fs::read_to_string(&cfg_path).map_err(|e| format!("Failed to read pyvenv.cfg: {}", e))?;
    let expected_home = python_dir.display().to_string();

    let mut lines: Vec<String> = Vec::new();
    let mut found_home = false;
    for line in current_content.lines() {
        let lower = line.trim_start().to_lowercase();
        if lower.starts_with("home") {
            lines.push(format!("home = {}", expected_home));
            found_home = true;
        } else {
            lines.push(line.to_string());
        }
    }

    if !found_home {
        lines.insert(0, format!("home = {}", expected_home));
    }

    let line_ending = if current_content.contains("\r\n") { "\r\n" } else { "\n" };
    let mut new_content = lines.join(line_ending);
    if current_content.ends_with(line_ending) {
        new_content.push_str(line_ending);
    }

    if new_content == current_content {
        return Ok(());
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
    if env::var("PLAYWRIGHT_BROWSERS_PATH").is_err() && playwright_path.exists() {
        env::set_var("PLAYWRIGHT_BROWSERS_PATH", &playwright_path);
    }

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
    if env::var("YAKULINGO_WATCHDOG").is_err() {
        command.env("YAKULINGO_WATCHDOG", "1");
    }

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
    if env::var("YAKULINGO_WATCHDOG").is_err() {
        command.env("YAKULINGO_WATCHDOG", "1");
    }

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
