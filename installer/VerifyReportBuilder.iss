; Inno Setup script - builds a normal Windows installer (Setup.exe) around the one-file app.
; Build:  iscc /DAppVersion=10.0.3 /DArch=x64 installer\VerifyReportBuilder.iss      (Arch = x64 | x86)
#ifndef AppVersion
  #define AppVersion "10.0.3"
#endif
#ifndef Arch
  #define Arch "x64"
#endif

[Setup]
AppId={{6C1D0B3E-5B5A-4C52-9E0B-7A3A5C8F2D11}
AppName=Verify Report Builder
AppVersion={#AppVersion}
AppPublisher=Barikoi Technologies Limited
DefaultDirName={autopf}\Verify Report Builder
DefaultGroupName=Verify Report Builder
DisableProgramGroupPage=yes
OutputDir=..\installer_out
OutputBaseFilename=VerifyReportBuilder-Setup-{#Arch}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; per-user install: no administrator password needed
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\VerifyReportBuilder.exe
#if Arch == "x64"
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\VerifyReportBuilder.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Verify Report Builder"; Filename: "{app}\VerifyReportBuilder.exe"
Name: "{autodesktop}\Verify Report Builder"; Filename: "{app}\VerifyReportBuilder.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VerifyReportBuilder.exe"; Description: "Open Verify Report Builder"; Flags: nowait postinstall skipifsilent
