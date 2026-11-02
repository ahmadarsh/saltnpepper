#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    fs::{self, File},
    io::{BufRead, BufReader, Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{mpsc, Mutex},
    sync::atomic::{AtomicUsize, Ordering},
    thread,
    time::{Duration, Instant},
};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri::webview::NewWindowResponse;

static NEXT_VIEWER: AtomicUsize = AtomicUsize::new(1);

struct Backend {
    child: Child,
    address: SocketAddr,
    token: String,
}

impl Backend {
    fn stop(&mut self) {
        if self.child.try_wait().ok().flatten().is_some() { return; }
        if let Ok(mut stream) = TcpStream::connect_timeout(&self.address, Duration::from_secs(2)) {
            let body = serde_json::json!({"token": self.token}).to_string();
            let request = format!("POST /api/shutdown HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", self.address, body.len(), body);
            let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
            let _ = stream.set_read_timeout(Some(Duration::from_secs(7)));
            if stream.write_all(request.as_bytes()).is_ok() {
                // Keep the connection alive until the shutdown handler acknowledges it.
                let mut response = String::new();
                let _ = stream.read_to_string(&mut response);
            }
        }
        let deadline = Instant::now() + Duration::from_secs(8);
        while Instant::now() < deadline {
            if self.child.try_wait().ok().flatten().is_some() { return; }
            thread::sleep(Duration::from_millis(100));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for Backend {
    fn drop(&mut self) { self.stop(); }
}

fn start_backend(executable: &Path, data: &Path, logs: &Path) -> Result<Backend, Box<dyn std::error::Error>> {
    fs::create_dir_all(data)?;
    fs::create_dir_all(logs)?;
    let errors = File::create(logs.join("backend-errors.log"))?;
    let mut command = Command::new(executable);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    let mut child = command.args(["--no-browser", "--port", "0", "--data-dir"])
        .arg(data)
        .arg("--desktop-parent").arg(std::process::id().to_string())
        .env("PYTHONUNBUFFERED", "1")
        .stdout(Stdio::piped()).stderr(errors).spawn()?;
    let stdout = child.stdout.take().ok_or("Backend stdout unavailable")?;
    let (sender, receiver) = mpsc::channel();
    let logfile = logs.join("backend.log");
    thread::spawn(move || {
        let mut log = File::create(logfile).ok();
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(file) = &mut log { let _ = writeln!(file, "{line}"); }
            if let Some(url) = line.strip_prefix("Salt and Pepper: ") { let _ = sender.send(url.to_owned()); }
        }
    });
    let result: Result<(SocketAddr, String), Box<dyn std::error::Error>> = (|| {
        let url = receiver.recv_timeout(Duration::from_secs(90))?;
        let control: serde_json::Value = serde_json::from_slice(&fs::read(data.join("server.json"))?)?;
        let port = control["port"].as_u64().ok_or("Backend port missing")?;
        let token = control["token"].as_str().ok_or("Backend control token missing")?.to_owned();
        let address: SocketAddr = format!("127.0.0.1:{port}").parse()?;
        let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(5))?;
        stream.set_read_timeout(Some(Duration::from_secs(5)))?;
        write!(stream, "GET /api/health HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n")?;
        let mut response = String::new(); stream.read_to_string(&mut response)?;
        if !response.contains("PCB Simulation Workbench") || !url.starts_with("http://127.0.0.1:") {
            return Err("Backend health check failed".into());
        }
        Ok((address, token))
    })();
    match result {
        Ok((address, token)) => Ok(Backend { child, address, token }),
        Err(error) => { let _ = child.kill(); let _ = child.wait(); Err(error) }
    }
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let support = app.path().app_data_dir()?;
            let logs = support.join("logs");
            // An override supports testing the packaged executable without touching user data.
            let data = std::env::var_os("SALT_PEPPER_DATA_DIR").map(PathBuf::from)
                .unwrap_or_else(|| support.join("data"));
            let executable = app.path().resource_dir()?.join(if cfg!(target_os = "windows") { "backend/salt-pepper-backend.exe" } else { "backend/salt-pepper-backend" });
            let backend = start_backend(&executable, &data, &logs)?;
            let url = format!("http://{}/", backend.address);
            app.manage(Mutex::new(Some(backend)));
            let origin = url.parse::<tauri::Url>()?.origin();
            let viewer_app = app.handle().clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse()?))
                .title("Salt and Pepper").inner_size(1440.0, 920.0)
                .disable_drag_drop_handler()
                .on_download(|_, _| true)
                .min_inner_size(900.0, 650.0)
                .on_new_window(move |url, features| {
                    if url.origin() != origin { return NewWindowResponse::Deny; }
                    let label = format!("viewer-{}", NEXT_VIEWER.fetch_add(1, Ordering::Relaxed));
                    match WebviewWindowBuilder::new(&viewer_app, label, WebviewUrl::External("about:blank".parse().unwrap()))
                        .title("Salt and Pepper — Results").window_features(features)
                        .on_download(|_, _| true)
                        .inner_size(1280.0, 850.0).build() {
                            Ok(window) => NewWindowResponse::Create { window },
                            Err(_) => NewWindowResponse::Deny,
                        }
                }).build()?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" && matches!(event, WindowEvent::Destroyed) { window.app_handle().exit(0); }
        })
        .build(tauri::generate_context!())
        .expect("Could not start Salt and Pepper. Check Application Support/com.arshahmad.salt-and-pepper/logs.");
    app.run(|handle, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            if let Some(state) = handle.try_state::<Mutex<Option<Backend>>>() {
                if let Ok(mut backend) = state.lock() { backend.take(); }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn bundled_backend_starts_and_stops_without_a_window() {
        let executable = std::env::var_os("SALT_PEPPER_TEST_BACKEND")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../dist/Salt and Pepper.app/Contents/Resources/backend/salt-pepper-backend"));
        let unique = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = std::env::temp_dir().join(format!("salt-pepper-rust-test-{unique}"));
        let data = root.join("data");
        let mut backend = start_backend(&executable, &data, &root.join("logs"))
            .expect("Bundled backend must start and answer its health endpoint");
        assert!(data.join("server.json").is_file());
        backend.stop();
        assert!(backend.child.try_wait().unwrap().unwrap().success());
        assert!(!data.join("server.json").exists());
        drop(backend);
        fs::remove_dir_all(root).unwrap();
    }
}
