use std::sync::Mutex;

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

type BackendChild = Mutex<Option<CommandChild>>;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Development starts the Python API via npm's desktop:dev script.
            // Packaged builds launch the bundled PyInstaller orchestration sidecar.
            let mut child = None;
            if !cfg!(debug_assertions) {
                let sidecar = app.shell().sidecar("audio-score-backend")?;
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
            }
        }
    });
}
