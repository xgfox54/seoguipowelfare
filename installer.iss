#ifndef AppVersion
  #define AppVersion "1.3.3"
#endif
#ifndef ModelVariant
  #define ModelVariant "E2B"
#endif
#ifndef ExeFileName
  #define ExeFileName "복지업무비서_v" + AppVersion + "_" + ModelVariant + ".exe"
#endif
#if ModelVariant == "E4B"
#define AppName "복지톡AI 복지업무비서 E4B"
#define InstallFolder "BokjiTalkAI_E4B"
#define InstallId "BokjiTalkAI_E4B"
#else
#define AppName "복지톡AI 복지업무비서"
#define InstallFolder "BokjiTalkAI"
#define InstallId "{{7E4B2C1A-9D3F-4A6B-8C5E-2F1D0B9A7E63}"
#endif
#define ExeName ExeFileName

[Setup]
AppId={#InstallId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion} ({#ModelVariant})
AppPublisher=서귀포시
DefaultDirName={localappdata}\{#InstallFolder}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=복지톡AI_Setup_v{#AppVersion}_{#ModelVariant}
SetupIconFile=assets\bokjitalk.ico
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2/fast
SolidCompression=no
LZMAUseSeparateProcess=yes
#if ModelVariant == "E4B"
DiskSpanning=yes
DiskSliceSize=2100000000
#else
DiskSpanning=no
#endif
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"

[Files]
Source: "dist\welfare_assistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\logs"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "지금 {#AppName} 실행"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\.openkb"
