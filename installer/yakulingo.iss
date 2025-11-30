; YakuLingo Installer Script for Inno Setup
; Inno Setup: https://jrsoftware.org/isinfo.php

#define MyAppName "YakuLingo"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Your Company"
#define MyAppExeName "run.bat"

[Setup]
; アプリケーション情報
AppId={{8A3F5B2C-1D4E-4F6A-9B8C-7D2E3F4A5B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=YakuLingo_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; アイコン (後で追加)
; SetupIconFile=..\assets\icon.ico

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ルートレベル (エントリーポイント)
Source: "..\setup.bat"; DestDir: "{app}"; Flags: ignoreversion

; _internal フォルダ内のメインファイル
Source: "..\app.py"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\uv.toml"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\glossary.csv"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\run.bat"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\setup.ps1"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\remove.bat"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\remove.ps1"; DestDir: "{app}\_internal"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}\_internal"; Flags: ignoreversion

; パッケージ (_internal 内)
Source: "..\yakulingo\*"; DestDir: "{app}\_internal\yakulingo"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\prompts\*"; DestDir: "{app}\_internal\prompts"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; スタートメニュー
Name: "{group}\{#MyAppName}"; Filename: "{app}\_internal\run.bat"; WorkingDir: "{app}\_internal"; IconFilename: "{sys}\shell32.dll"; IconIndex: 13
Name: "{group}\{#MyAppName} セットアップ"; Filename: "{app}\setup.bat"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; デスクトップ
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\_internal\run.bat"; WorkingDir: "{app}\_internal"; IconFilename: "{sys}\shell32.dll"; IconIndex: 13; Tasks: desktopicon

[Run]
; インストール後にセットアップを実行
Filename: "{app}\setup.bat"; Description: "依存関係をインストール (初回必須)"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
; アンインストール時に削除するフォルダ
Type: filesandordirs; Name: "{app}\_internal\.venv"
Type: filesandordirs; Name: "{app}\_internal\.uv-python"
Type: filesandordirs; Name: "{app}\_internal\.playwright-browsers"
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
Type: filesandordirs; Name: "{app}\_internal\*.pyc"

[Messages]
japanese.WelcomeLabel1=YakuLingo セットアップウィザードへようこそ
japanese.WelcomeLabel2=このプログラムは YakuLingo (日英翻訳ツール) をコンピュータにインストールします。%n%nインストールを続行する前に、他のアプリケーションをすべて閉じることを推奨します。
japanese.FinishedLabel=YakuLingo のインストールが完了しました。%n%n「依存関係をインストール」にチェックを入れて初回セットアップを実行してください（約2-3分）。

[Code]
// インストール完了後のメッセージ
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 追加の処理があればここに
  end;
end;
