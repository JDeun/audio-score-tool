use std::sync::Mutex;

use tauri::{Manager, RunEvent, State};
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use uuid::Uuid;

type BackendChild = Mutex<Option<CommandChild>>;
struct BackendApiToken(String);

#[tauri::command]
fn backend_api_token(state: State<'_, BackendApiToken>) -> String {
    state.0.clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let api_token = Uuid::new_v4().simple().to_string();
    let sidecar_token = api_token.clone();

    let app = tauri::Builder::default()
        // Must be registered before plugins that can create side effects. A duplicate
        // desktop launch should focus the existing window instead of spawning another
        // backend that would contend for the fixed loopback port.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(BackendApiToken(api_token))
        .invoke_handler(tauri::generate_handler![backend_api_token])
        .setup(move |app| {
            // Development starts the Python API via npm's desktop:dev script.
            // Packaged builds launch the bundled PyInstaller orchestration sidecar.
            let mut child = None;
            if !cfg!(debug_assertions) {
                let sidecar = app
                    .shell()
                    .sidecar("audio-score-backend")?
                    .env("AST_API_TOKEN", &sidecar_token);
                let (mut rx, spawned) = sidecar.spawn()?;
                child = Some(spawned);

                // Keep draining the plugin event channel so backend stdout/stderr cannot
                // back-pressure a long-running transcription process. Application logs
                // are intentionally not persisted here until a redaction policy exists.
                tauri::async_runtime::spawn(async move {
                    while rx.recv().await.is_some() {}
                });
            }
            app.manage(BackendChild::new(child));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building AudioScoreTool");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit) {
            let state = app_handle.state::<BackendChild>();
            if let Ok(mut guard) = state.lock() {
                if let Some(child) = guard.take() {
                    let _ = child.kill();
                }
            };
        }
    });
}
