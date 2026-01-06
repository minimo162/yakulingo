# Manual Tests (Windows)

## Browser UI prewarm (resident + browser mode)
1. Set env vars:
   - `YAKULINGO_NO_AUTO_OPEN=1`
   - `YAKULINGO_RESIDENT_UI_MODE=browser`
   - `YAKULINGO_BROWSER_PREWARM=1`
2. Launch the app.
3. Confirm `startup.log` contains "browser UI prewarm enabled (silent)".
4. Within a few seconds after launch, trigger the hotkey (Ctrl+C twice) to hit the prewarm race window.
5. Verify the UI appears without a visible flash and comes to the foreground.

## Native mode ignores leftover Edge app window
1. Run in browser mode and open the UI once to create the Edge app window.
2. Terminate the YakuLingo process without graceful shutdown (leave the Edge app window open).
3. Run in native mode:
   - `YAKULINGO_RESIDENT_UI_MODE=native`
   - Leave `YAKULINGO_BROWSER_PREWARM` unset.
4. Trigger the UI open (hotkey or `/api/activate`).
5. Verify the native window is foreground and the old Edge app window is not activated.

## Foreground retry fallback (threaded path)
1. Run in browser mode with resident enabled.
2. Trigger UI open from a hotkey while another window is focused.
3. Verify `[TIMING] foreground_retry_*` logs appear and the UI eventually foregrounds.
