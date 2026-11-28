# icacls

> Display or change the access control lists (permissions) of files and directories.
> More information: <https://learn.microsoft.com/windows-server/administration/windows-commands/icacls>.

- Show the permissions of a file or directory:

`icacls {{path\to\file_or_directory}}`

- Grant a user Delete and Write DAC permissions on a file:

`icacls {{path\to\file}} /grant "{{User1}}:(d,wdac)"`

- Save the permissions of all files in a directory and its subdirectories to a file:

`icacls {{path\to\directory}}\* /save {{path\to\aclfile}} /t`

- Restore saved permissions to the files in a directory:

`icacls {{path\to\directory}}\ /restore {{path\to\aclfile}}`
