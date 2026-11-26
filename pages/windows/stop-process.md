# Stop-Process

> Stop one or more running processes. Stopping a process can also stop the processes and services that depend on it.
> Note: This command can only be used through PowerShell.
> See also: `taskkill`, `Get-Process`.
> More information: <https://learn.microsoft.com/powershell/module/microsoft.powershell.management/stop-process>.

- Stop all instances of a process by name:

`Stop-Process -Name "{{notepad}}"`

- Stop a process by ID, asking for confirmation first:

`Stop-Process -Id {{3952}} -Confirm -PassThru`

- Stop a process that the current user does not own (needs an elevated PowerShell):

`Get-Process -Name "{{process_name}}" | Stop-Process -Force`
