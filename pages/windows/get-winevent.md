# Get-WinEvent

> Get events from event logs and event tracing log files on local and remote computers.
> Note: This command can only be used through PowerShell.
> See also: `wevtutil`.
> More information: <https://learn.microsoft.com/powershell/module/microsoft.powershell.diagnostics/get-winevent>.

- List all event logs:

`Get-WinEvent -ListLog *`

- List only event logs that contain events:

`Get-WinEvent -ListLog * | Where-Object { $_.RecordCount }`

- Get the most recent events from a log:

`Get-WinEvent -LogName {{System}} -MaxEvents {{10}}`

- Get events from logs whose names match a wildcard pattern:

`Get-WinEvent -LogName {{*PowerShell*}}`

- Get events from a saved event log file:

`Get-WinEvent -Path {{path\to\file.evtx}}`

- Get events with a specific ID from a log since a given date:

`Get-WinEvent -FilterHashtable @{ LogName='{{Application}}'; Id={{1003}}; StartTime=(Get-Date).AddDays(-{{2}}) }`

- Get events from a log on a remote computer:

`Get-WinEvent -LogName {{Application}} -ComputerName {{computer_name}} -MaxEvents {{10}}`

- List event providers whose names match a pattern:

`Get-WinEvent -ListProvider {{*Policy*}}`
