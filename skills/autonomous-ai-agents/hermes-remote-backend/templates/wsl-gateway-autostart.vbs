' Hermes WSL gateway — boot the distro at logon and keep it up.
'
' WSL2 terminates a distro the moment its last wsl.exe session ends, regardless
' of systemd or logind linger. Booting alone is therefore NOT enough: a session
' has to be HELD OPEN. This holds one, hidden, and re-establishes it if it drops.
'
' Booting the distro starts the Hermes backend (linger=yes), which serves the
' gateway on 127.0.0.1:9119.
'
' Replace <DISTRO> with the distro name (`wsl.exe -l -v`). Note the sleep path:
' a NixOS guest has no FHS, so /bin/sleep does not exist and the session dies
' instantly. On a distro WITH an FHS, /bin/sleep is fine.
'
' Install: copy into
'   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
' Do NOT use Task Scheduler — an ONLOGON task needs elevation and fails with
' "Access is denied".
'
' To disable: delete this file from the Startup folder.

Set sh = CreateObject("WScript.Shell")

Do
  ' Hidden window (0), and wait (True): the loop only advances when the session
  ' actually ends, so this re-establishes rather than spins.
  sh.Run "wsl.exe -d <DISTRO> --exec /run/current-system/sw/bin/sleep infinity", 0, True
  WScript.Sleep 5000
Loop
