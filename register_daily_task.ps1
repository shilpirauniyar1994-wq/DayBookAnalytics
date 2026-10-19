# Registers Windows Scheduled Task for Daily TikTok 9:00 AM Dispatch
$TaskName = "DayBook_TikTok_Daily_9AM"
$PythonPath = (Get-Command python).Source
$WorkingDir = "c:\Users\gupta\DayBookAnalytics"
$ScriptPath = Join-Path $WorkingDir "daily_tiktok_dispatch.py"

# Construct Action
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`"" -WorkingDirectory $WorkingDir

# Daily at 09:00 AM trigger
$Trigger = New-ScheduledTaskTrigger -Daily -At "09:00"

# Settings (run as soon as possible if missed, wake if supported)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Register or overwrite task
try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Daily 9:00 AM TikTok video reel generation and WhatsApp dispatch to +9779851155318" -Force
    Write-Host "✅ Successfully registered Windows Scheduled Task '$TaskName' to run every morning at 09:00 AM!" -ForegroundColor Green
} catch {
    Write-Warning "PowerShell Register-ScheduledTask notice: $_"
    # Fallback to schtasks
    $SchCmd = "schtasks /create /tn `"$TaskName`" /tr `"`"$PythonPath`" `"$ScriptPath`"`" /sc daily /st 09:00 /f"
    Invoke-Expression $SchCmd
}
