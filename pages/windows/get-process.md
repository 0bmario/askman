# Get-Process

> Get the processes that are running on the local computer.
> Note: This command can only be used through PowerShell.
> See also: `tasklist`, `Stop-Process`.
> More information: <https://learn.microsoft.com/powershell/module/microsoft.powershell.management/get-process>.

- List all running processes:

`Get-Process`

- Display detailed information about specific processes:

`Get-Process {{winword}}, {{explorer}} | Format-List *`

- Get processes by process ID:

`Get-Process -Id {{664}}, {{2060}}`

- Get processes with a working set greater than a given size:

`Get-Process | Where-Object WorkingSet -GT {{20MB}}`

- Show the owner of a process:

`Get-Process -Name {{pwsh}} -IncludeUserName`

- Get version information for a process (needs an elevated PowerShell for processes you don't own):

`Get-Process -Name {{pwsh}} -FileVersionInfo`

- Get the modules loaded by a process (needs an elevated PowerShell for processes you don't own):

`Get-Process -Name {{SQL*}} -Module`
