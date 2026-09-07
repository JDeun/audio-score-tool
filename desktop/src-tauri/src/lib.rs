use tauri_plugin_shell::ShellExt;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Development starts the Python API via npm's desktop:dev script.
            // Packaged builds launch the bundled PyInstaller orchestration sidecar.
            // cfg! keeps both branches type-checked during normal cargo check.
            if !cfg!(debug_assertions) {
                let sidecar = app.shell().sidecar("audio-score-backend")?;
                let (_rx, _child) = sidecar.spawn()?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running AudioScoreTool");
}
