# UI ↔ Script Integration Review

This document summarizes how the NiceGUI UI in `yakulingo/ui` connects to the backend translation scripts and services.

## Entry points and app wiring
- The top-level `app.py` sets up logging and calls `yakulingo.ui.app.run_app`, passing the host/port and enabling native window mode so the NiceGUI UI is bootstrapped consistently.
- `run_app` lazily imports NiceGUI, builds a `YakuLingoApp` instance via `create_app`, detects display sizes for sensible defaults, and registers shutdown cleanup that stops the hotkey manager, cancels login polling, and cancels any active translations.

## UI-to-service connections
- During startup (`wait_for_edge_connection` / `start_edge_and_connect`), the UI constructs `TranslationService` with the Copilot handler, user settings, and prompts directory before attempting browser login. This means translation APIs are available as soon as the UI is ready, independent of Copilot connection state.
- The Copilot handler itself is lazy-loaded on first access, so import overhead is deferred until a translation-related action triggers it.

## Text translation flow
- `_translate_text` enforces the 5,000 character UI limit and automatically routes longer input to file translation by writing a temporary file and switching to the File tab. This keeps UI behavior consistent for long content.
- For normal text input, the method detects the language through `TranslationService.detect_language`, updates the UI with the detected language, then calls `translate_text_with_options` with streaming callbacks to surface partial results in the result panel while the translation runs in a worker thread.

## File translation flow
- When a file is selected or a long text is converted to a temp file, `_translate_file` sets `FileState` and `TranslationStatus` flags, resets progress state, and refreshes the UI before starting translation work in a thread.
- The translation thread uses `_on_file_progress` to push progress updates and cancelation state back into the UI, while also writing output and optionally keeping original files based on settings. Errors are surfaced through NiceGUI notifications and status flags for user visibility.

## Hotkey and lifecycle hooks
- The app optionally starts a global hotkey manager (Ctrl+J on Windows) that calls `_on_hotkey_triggered`, bringing the NiceGUI window to the foreground and injecting the clipboard contents into the text input before invoking `_translate_text`.
- Shutdown hooks stop the hotkey manager and cancel running tasks to avoid dangling Playwright threads or partial file outputs when the user exits the UI.
