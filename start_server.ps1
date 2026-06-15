$ErrorActionPreference = "SilentlyContinue"
$backendDir = "C:\Users\zoubida\Documents\king-fund\backend"
$pythonw    = "C:\Users\zoubida\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
$logFile    = "C:\Users\zoubida\Documents\king-fund\backend_launch.log"

Set-Location $backendDir

while ($true) {
    $timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    Add-Content $logFile "[$timestamp] Démarrage king-fund backend"

    $proc = Start-Process -FilePath $pythonw `
        -ArgumentList "-X", "utf8", "app.py" `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput "$backendDir\stdout.log" `
        -RedirectStandardError  "$backendDir\stderr.log" `
        -NoNewWindow -PassThru

    $proc.WaitForExit()
    $exitCode = $proc.ExitCode

    $timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    Add-Content $logFile "[$timestamp] Processus terminé (code=$exitCode) — redémarrage dans 10s"

    Start-Sleep -Seconds 10
}
