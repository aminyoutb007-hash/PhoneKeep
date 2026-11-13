; Inno Setup script: turns dist\PhoneKeep into a single PhoneKeep-Setup.exe
#ifndef AppVersion
  #define AppVersion "5.0.0"
#endif

[Setup]
AppId={{94F1224F-3F99-4F0F-98E9-CD2B1839A383}
AppName=PhoneKeep
AppVersion={#AppVersion}
AppPublisher=PhoneKeep
DefaultDirName={autopf}\PhoneKeep
DefaultGroupName=PhoneKeep
DisableProgramGroupPage=yes
OutputDir=..\Output
OutputBaseFilename=PhoneKeep-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\PhoneKeep.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\PhoneKeep\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PhoneKeep"; Filename: "{app}\PhoneKeep.exe"
Name: "{autodesktop}\PhoneKeep"; Filename: "{app}\PhoneKeep.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PhoneKeep.exe"; Description: "Open PhoneKeep now"; Flags: nowait postinstall skipifsilent

[Messages]
FinishedLabel=PhoneKeep is installed.%n%nWindows needs Apple's USB driver to talk to an iPhone: if you don't have iTunes, install the free "Apple Devices" app from the Microsoft Store.
