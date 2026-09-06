#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            #[cfg(not(debug_assertions))]
            {
                use tauri_plugin_shell::ShellExt;
                let sidecar = app.shell().sidecar("audio-score-backend")?;
                let (_rx, _child) = sidecar.spawn()?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running AudioScoreTool");
}
