# Get-HotFix

> Get the hotfixes (updates) installed on local or remote computers.
> Note: This command can only be used through PowerShell.
> More information: <https://learn.microsoft.com/powershell/module/microsoft.powershell.management/get-hotfix>.

- List all hotfixes installed on the local computer:

`Get-HotFix`

- Check whether a specific update is installed:

`Get-HotFix -Id {{KB957095}}`

- Show the most recently installed hotfix:

`(Get-HotFix | Sort-Object -Property InstalledOn)[-1]`
