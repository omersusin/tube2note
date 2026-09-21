//! tube2note desktop shell: spawns the Python sidecar (`tube2note serve`)
//! and shows it in a native window. The sidecar does all the work;
//! this binary is only a launcher + window.
use tauri::Manager;
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

#[tauri::command]
async fn start_sidecar(app: tauri::AppHandle, port: u16) -> Result<(), String> {
    let (mut rx, child) = app
        .shell()
        .sidecar("tube2note-serve")
        .map_err(|e| e.to_string())?
        .args(["serve", "--port", &port.to_string(), "--no-open"])
        .spawn()
        .map_err(|e| e.to_string())?;
    app.manage(std::sync::Mutex::new(Some(child)));
    tauri::async_runtime::spawn(async move {
        while let Some(ev) = rx.recv().await {
            if let CommandEvent::Stdout(l) = ev {
                println!("[sidecar] {}", String::from_utf8_lossy(&l));
            }
        }
    });
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![start_sidecar])
        .run(tauri::generate_context!())
        .expect("tauri failed");
}
