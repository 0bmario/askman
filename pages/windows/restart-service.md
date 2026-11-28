# Restart-Service

> Stop and then start one or more services.
> Note: This command can only be used through PowerShell.
> See also: `Get-Service`, `sc`.
> More information: <https://learn.microsoft.com/powershell/module/microsoft.powershell.management/restart-service>.

- Restart a service:

`Restart-Service -Name {{winmgmt}}`

- Restart services by display name, excluding one:

`Restart-Service -DisplayName "{{net*}}" -Exclude "{{net logon}}"`

- Restart all stopped services whose name matches a pattern:

`Get-Service -Name "{{net*}}" | Where-Object {$_.Status -eq "Stopped"} | Restart-Service`
