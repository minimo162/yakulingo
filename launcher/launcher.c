/*
 * YakuLingo Launcher
 *
 * Lightweight native launcher for YakuLingo application.
 * Features:
 * - No console window flash
 * - Duplicate instance prevention
 * - Portable path handling (fixes pyvenv.cfg)
 * - Environment variable setup
 *
 * Build: gcc -mwindows -O2 -s launcher.c -o YakuLingo.exe -lwinhttp
 */

#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE

#include <windows.h>
#include <winhttp.h>
#include <shlwapi.h>
#include <stdio.h>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "shlwapi.lib")

#define APP_PORT 8765
#define MAX_ENV_SIZE 32767

/* Check if the application is already running by attempting HTTP connection */
BOOL IsAppRunning(int port) {
    BOOL result = FALSE;
    HINTERNET hSession = NULL, hConnect = NULL, hRequest = NULL;

    hSession = WinHttpOpen(L"YakuLingo Launcher",
                           WINHTTP_ACCESS_TYPE_NO_PROXY,
                           WINHTTP_NO_PROXY_NAME,
                           WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) goto cleanup;

    /* Set short timeouts */
    DWORD timeout = 500;
    WinHttpSetOption(hSession, WINHTTP_OPTION_CONNECT_TIMEOUT, &timeout, sizeof(timeout));
    WinHttpSetOption(hSession, WINHTTP_OPTION_SEND_TIMEOUT, &timeout, sizeof(timeout));
    WinHttpSetOption(hSession, WINHTTP_OPTION_RECEIVE_TIMEOUT, &timeout, sizeof(timeout));

    hConnect = WinHttpConnect(hSession, L"127.0.0.1", (INTERNET_PORT)port, 0);
    if (!hConnect) goto cleanup;

    hRequest = WinHttpOpenRequest(hConnect, L"GET", L"/",
                                   NULL, WINHTTP_NO_REFERER,
                                   WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
    if (!hRequest) goto cleanup;

    if (WinHttpSendRequest(hRequest, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                           WINHTTP_NO_REQUEST_DATA, 0, 0, 0)) {
        if (WinHttpReceiveResponse(hRequest, NULL)) {
            result = TRUE;
        }
    }

cleanup:
    if (hRequest) WinHttpCloseHandle(hRequest);
    if (hConnect) WinHttpCloseHandle(hConnect);
    if (hSession) WinHttpCloseHandle(hSession);
    return result;
}

/* Find Python directory in .uv-python (cpython-*) */
BOOL FindPythonDir(WCHAR* baseDir, WCHAR* outPythonDir, DWORD size) {
    WCHAR searchPath[MAX_PATH];
    WIN32_FIND_DATAW findData;

    wsprintfW(searchPath, L"%s\\.uv-python\\cpython-*", baseDir);

    HANDLE hFind = FindFirstFileW(searchPath, &findData);
    if (hFind == INVALID_HANDLE_VALUE) {
        return FALSE;
    }

    do {
        if (findData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (wcsncmp(findData.cFileName, L"cpython-", 8) == 0) {
                wsprintfW(outPythonDir, L"%s\\.uv-python\\%s", baseDir, findData.cFileName);
                FindClose(hFind);
                return TRUE;
            }
        }
    } while (FindNextFileW(hFind, &findData));

    FindClose(hFind);
    return FALSE;
}

/* Fix pyvenv.cfg home path for portability */
BOOL FixPyvenvCfg(WCHAR* venvDir, WCHAR* pythonDir) {
    WCHAR cfgPath[MAX_PATH];
    WCHAR version[256] = L"";
    WCHAR line[1024];
    FILE* file;

    wsprintfW(cfgPath, L"%s\\pyvenv.cfg", venvDir);

    /* Read existing config to get version */
    if (_wfopen_s(&file, cfgPath, L"r") == 0 && file) {
        while (fgetws(line, 1024, file)) {
            /* Remove newline */
            WCHAR* nl = wcschr(line, L'\n');
            if (nl) *nl = L'\0';

            if (_wcsnicmp(line, L"version", 7) == 0) {
                wcscpy_s(version, 256, line);
            }
        }
        fclose(file);
    }

    /* Write new config with correct home path */
    if (_wfopen_s(&file, cfgPath, L"w") == 0 && file) {
        fwprintf(file, L"home = %s\n", pythonDir);
        fwprintf(file, L"include-system-site-packages = false\n");
        if (version[0] != L'\0') {
            fwprintf(file, L"%s\n", version);
        }
        fclose(file);
        return TRUE;
    }

    return FALSE;
}

/* Set environment variable, appending to existing PATH */
void SetupEnvironment(WCHAR* baseDir, WCHAR* venvDir, WCHAR* pythonDir) {
    WCHAR newPath[MAX_ENV_SIZE];
    WCHAR oldPath[MAX_ENV_SIZE];
    WCHAR playwrightPath[MAX_PATH];

    /* VIRTUAL_ENV */
    SetEnvironmentVariableW(L"VIRTUAL_ENV", venvDir);

    /* PLAYWRIGHT_BROWSERS_PATH */
    wsprintfW(playwrightPath, L"%s\\.playwright-browsers", baseDir);
    SetEnvironmentVariableW(L"PLAYWRIGHT_BROWSERS_PATH", playwrightPath);

    /* PATH - prepend venv and python directories */
    GetEnvironmentVariableW(L"PATH", oldPath, MAX_ENV_SIZE);
    wsprintfW(newPath, L"%s\\Scripts;%s;%s\\Scripts;%s",
              venvDir, pythonDir, pythonDir, oldPath);
    SetEnvironmentVariableW(L"PATH", newPath);
}

/* Show error message box */
void ShowError(WCHAR* message) {
    MessageBoxW(NULL, message, L"YakuLingo - Error", MB_ICONERROR | MB_OK);
}

/* Main entry point */
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                   LPSTR lpCmdLine, int nCmdShow) {
    WCHAR exePath[MAX_PATH];
    WCHAR baseDir[MAX_PATH];
    WCHAR venvDir[MAX_PATH];
    WCHAR pythonDir[MAX_PATH];
    WCHAR pythonExe[MAX_PATH];
    WCHAR appScript[MAX_PATH];
    WCHAR cmdLine[MAX_PATH * 2];

    /* Get executable directory */
    GetModuleFileNameW(NULL, exePath, MAX_PATH);
    wcscpy_s(baseDir, MAX_PATH, exePath);
    PathRemoveFileSpecW(baseDir);

    /* Check if already running */
    if (IsAppRunning(APP_PORT)) {
        MessageBoxW(NULL, L"YakuLingo is already running.",
                    L"YakuLingo", MB_ICONINFORMATION | MB_OK);
        return 0;
    }

    /* Find Python directory */
    if (!FindPythonDir(baseDir, pythonDir, MAX_PATH)) {
        ShowError(L"Python not found in .uv-python directory.\n\n"
                  L"Please reinstall the application.");
        return 1;
    }

    /* Check venv exists */
    wsprintfW(venvDir, L"%s\\.venv", baseDir);
    wsprintfW(pythonExe, L"%s\\Scripts\\pythonw.exe", venvDir);

    if (GetFileAttributesW(pythonExe) == INVALID_FILE_ATTRIBUTES) {
        ShowError(L".venv not found.\n\n"
                  L"Please reinstall the application.");
        return 1;
    }

    /* Fix pyvenv.cfg for portability */
    FixPyvenvCfg(venvDir, pythonDir);

    /* Setup environment variables */
    SetupEnvironment(baseDir, venvDir, pythonDir);

    /* Build command line */
    wsprintfW(appScript, L"%s\\app.py", baseDir);
    wsprintfW(cmdLine, L"\"%s\" \"%s\"", pythonExe, appScript);

    /* Launch application */
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi = { 0 };

    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;

    BOOL success = CreateProcessW(
        NULL,           /* Application name (use command line) */
        cmdLine,        /* Command line */
        NULL,           /* Process security attributes */
        NULL,           /* Thread security attributes */
        FALSE,          /* Inherit handles */
        CREATE_NO_WINDOW | DETACHED_PROCESS,  /* Creation flags */
        NULL,           /* Environment (inherit modified environment) */
        baseDir,        /* Current directory */
        &si,            /* Startup info */
        &pi             /* Process information */
    );

    if (!success) {
        ShowError(L"Failed to start application.\n\n"
                  L"Please check your installation.");
        return 1;
    }

    /* Clean up handles */
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    return 0;
}
