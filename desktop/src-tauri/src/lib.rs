use std::{net::TcpListener, sync::Mutex, time::Duration};

use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_shell::{process::CommandChild, ShellExt};
#[cfg(desktop)]
use tauri_plugin_updater::{Update, UpdaterExt};
use uuid::Uuid;

type BackendChild = Mutex<Option<CommandChild>>;
struct BackendApiToken(String);
struct BackendApiBaseUrl(String);

#[cfg(desktop)]
struct PendingUpdate(Mutex<Option<Update>>);

#[tauri::command]
fn backend_api_token(state: State<'_, BackendApiToken>) -> String {
    state.0.clone()
}

#[tauri::command]
fn backend_api_base_url(state: State<'_, BackendApiBaseUrl>) -> String {
    state.0.clone()
}

#[cfg(desktop)]
#[tauri::command]
fn updater_configured() -> bool {
    option_env!("AST_UPDATER_PUBKEY").is_some()
}

#[cfg(desktop)]
#[tauri::command]
async fn check_for_update(
    app: AppHandle,
    pending_update: State<'_, PendingUpdate>,
) -> Result<Option<String>, String> {
    let Some(pubkey) = option_env!("AST_UPDATER_PUBKEY") else {
        return Ok(None);
    };

    let endpoint = "https://github.com/JDeun/audio-score-tool/releases/latest/download/latest.json"
        .parse()
        .map_err(|error| format!("invalid updater endpoint: {error}"))?;
    let update = app
        .updater_builder()
        .pubkey(pubkey)
        .endpoints(vec![endpoint])
        .map_err(|error| error.to_string())?
        .timeout(Duration::from_secs(20))
        .build()
        .map_err(|error| error.to_string())?
        .check()
        .await
        .map_err(|error| error.to_string())?;
    let version = update.as_ref().map(|candidate| candidate.version.clone());

    let mut guard = pending_update
        .0
        .lock()
        .map_err(|_| "updater state lock is poisoned".to_string())?;
    *guard = update;
    Ok(version)
}

#[cfg(desktop)]
#[tauri::command]
async fn install_pending_update(
    app: AppHandle,
    pending_update: State<'_, PendingUpdate>,
) -> Result<(), String> {
    let update = {
        let mut guard = pending_update
            .0
            .lock()
            .map_err(|_| "updater state lock is poisoned".to_string())?;
        guard
            .take()
            .ok_or_else(|| "there is no pending update".to_string())?
    };

    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|error| error.to_string())?;

    #[cfg(target_os = "windows")]
    {
        let _ = app;
        Ok(())
    }

    #[cfg(not(target_os = "windows"))]
    {
        app.restart()
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let api_token = Uuid::new_v4().simple().to_string();
    let sidecar_token = api_token.clone();

    // Development starts the Python API independently through npm and keeps the
    // conventional port. Packaged builds reserve an ephemeral loopback port until
    // immediately before the sidecar is spawned, minimizing the bind race window.
    let (api_port, mut reserved_listener) = if cfg!(debug_assertions) {
        (8080, None)
    } else {
        let listener = TcpListener::bind(("127.0.0.1", 0))
            .expect("failed to reserve backend loopback port");
        let port = listener
            .local_addr()
            .expect("failed to inspect backend loopback port")
            .port();
        (port, Some(listener))
    };
    let api_base_url = format!("http://127.0.0.1:{api_port}");
    let sidecar_port = api_port.to_string();

    let app = tauri::Builder::default()
        // Must be registered before plugins that can create side effects. A duplicate
        // desktop launch should focus the existing window instead of spawning another
        // backend process.
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
        .manage(BackendApiBaseUrl(api_base_url))
        .invoke_handler(tauri::generate_handler![
            backend_api_token,
            backend_api_base_url,
            #[cfg(desktop)]
            updater_configured,
            #[cfg(desktop)]
            check_for_update,
            #[cfg(desktop)]
            install_pending_update
        ])
        .setup(move |app| {
            #[cfg(desktop)]
            {
                app.manage(PendingUpdate(Mutex::new(None)));
                if let Some(pubkey) = option_env!("AST_UPDATER_PUBKEY") {
                    app.handle().plugin(
                        tauri_plugin_updater::Builder::new()
                            .pubkey(pubkey)
                            .build(),
                    )?;
                }
            }

            // Development starts the Python API via npm's desktop:dev script.
            // Packaged builds launch the bundled PyInstaller orchestration sidecar.
            let mut child = None;
            if !cfg!(debug_assertions) {
                // Release the reserved socket only when the sidecar is ready to bind it.
                drop(reserved_listener.take());
                let sidecar = app
                    .shell()
                    .sidecar("audio-score-backend")?
                    .env("AST_API_TOKEN", &sidecar_token)
                    .env("AST_API_PORT", &sidecar_port);
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
