; EZ Tag - Windows installer (one simple Setup, Python and everything included)
; Built by installer/build.sh with:  makensis -DVERSION=x.y.z -DSTAGE=<folder> -DOUTFILE=<exe> ez-tag.nsi

Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user          ; installs for you - no admin password needed

!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!define APPNAME "EZ Tag"
!define COMPANY "Dr. Szaba"
!define REGKEY  "Software\Microsoft\Windows\CurrentVersion\Uninstall\EZTag"
!define PYW     "$INSTDIR\python\pythonw.exe"
!define MAIN    "$INSTDIR\app\ez_tag.pyw"
!define ICON    "$INSTDIR\app\assets\ez-tag.ico"

Name "${APPNAME} ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\EZ Tag"
InstallDirRegKey HKCU "Software\EZ Tag" "InstallDir"
BrandingText "EZ Tag ${VERSION} - free from Dr. Szaba"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "CompanyName" "${COMPANY}"
VIAddVersionKey "FileDescription" "EZ Tag Setup - easy music tag editor"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Free software by ${COMPANY}"

!include "MUI2.nsh"
!include "FileFunc.nsh"
!define MUI_ICON "${STAGE}\app\assets\ez-tag.ico"
!define MUI_UNICON "${STAGE}\app\assets\ez-tag.ico"
!define MUI_WELCOMEPAGE_TITLE "Welcome to EZ Tag!"
!define MUI_WELCOMEPAGE_TEXT "EZ Tag is the easy, colorful music tag editor.$\r$\n$\r$\nFix song titles, artists, albums and cover art for MP3, FLAC, M4A, WMA, WAV, OGG and every other audio format.$\r$\n$\r$\nNew in 1.1: EZ Tag updates itself - it checks for new versions and installs them for you.$\r$\n$\r$\nEverything it needs is included. Your settings are kept. Click Next to continue."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Start EZ Tag now"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!define MUI_ABORTWARNING

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function LaunchApp
  Exec '"${PYW}" "${MAIN}"'
FunctionEnd

; automatic updates run this setup quietly (/S); with /UPDATE it reopens EZ Tag afterwards
Function .onInstSuccess
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/UPDATE" $1
  IfErrors +2 0
    Call LaunchApp
FunctionEnd

Section "EZ Tag" SecMain
  SectionIn RO
  ; an automatic update starts while EZ Tag is closing - give it a moment
  IfSilent 0 +2
    Sleep 2500
  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\app"                  ; clean old program files on update (settings live in AppData)
  SetOutPath "$INSTDIR\python"
  File /r "${STAGE}\python\*.*"
  SetOutPath "$INSTDIR\app"
  File /r "${STAGE}\app\*.*"
  SetOutPath "$INSTDIR"
  File "${STAGE}\README.txt"
  File "${STAGE}\LICENSE.txt"
  File "${STAGE}\LICENSES.txt"

  ; shortcuts
  SetOutPath "$INSTDIR\app"
  CreateShortCut "$DESKTOP\EZ Tag.lnk" "${PYW}" '"${MAIN}"' "${ICON}" 0
  CreateDirectory "$SMPROGRAMS\EZ Tag"
  CreateShortCut "$SMPROGRAMS\EZ Tag\EZ Tag.lnk" "${PYW}" '"${MAIN}"' "${ICON}" 0
  CreateShortCut "$SMPROGRAMS\EZ Tag\Uninstall EZ Tag.lnk" "$INSTDIR\Uninstall EZ Tag.exe"

  ; right-click "Edit tags with EZ Tag" on folders and on music files
  WriteRegStr HKCU "Software\Classes\Directory\shell\EZTag" "" "Edit tags with EZ Tag"
  WriteRegStr HKCU "Software\Classes\Directory\shell\EZTag" "Icon" "${ICON}"
  WriteRegStr HKCU "Software\Classes\Directory\shell\EZTag\command" "" '"${PYW}" "${MAIN}" "%1"'
  WriteRegStr HKCU "Software\Classes\SystemFileAssociations\audio\shell\EZTag" "" "Edit tags with EZ Tag"
  WriteRegStr HKCU "Software\Classes\SystemFileAssociations\audio\shell\EZTag" "Icon" "${ICON}"
  WriteRegStr HKCU "Software\Classes\SystemFileAssociations\audio\shell\EZTag\command" "" '"${PYW}" "${MAIN}" "%1"'

  ; Add/Remove Programs
  WriteRegStr HKCU "Software\EZ Tag" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${REGKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${REGKEY}" "Publisher" "${COMPANY}"
  WriteRegStr HKCU "${REGKEY}" "DisplayIcon" "${ICON}"
  WriteRegStr HKCU "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "URLInfoAbout" "https://drszaba.github.io/ez-tag/"
  WriteRegStr HKCU "${REGKEY}" "UninstallString" '"$INSTDIR\Uninstall EZ Tag.exe"'
  WriteRegDWORD HKCU "${REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${REGKEY}" "NoRepair" 1
  WriteUninstaller "$INSTDIR\Uninstall EZ Tag.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\EZ Tag.lnk"
  RMDir /r "$SMPROGRAMS\EZ Tag"
  DeleteRegKey HKCU "Software\Classes\Directory\shell\EZTag"
  DeleteRegKey HKCU "Software\Classes\SystemFileAssociations\audio\shell\EZTag"
  DeleteRegKey HKCU "${REGKEY}"
  DeleteRegKey HKCU "Software\EZ Tag"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\LICENSE.txt"
  Delete "$INSTDIR\LICENSES.txt"
  Delete "$INSTDIR\Uninstall EZ Tag.exe"
  RMDir "$INSTDIR"
SectionEnd
