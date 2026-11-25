# schtasks

> Create, list, run and delete scheduled tasks.
> More information: <https://learn.microsoft.com/windows-server/administration/windows-commands/schtasks>.

- List all scheduled tasks on the local computer:

`schtasks /query`

- List all scheduled tasks with details:

`schtasks /query /fo LIST /v`

- Schedule a program to run every 20 minutes (only administrators can schedule tasks):

`schtasks /create /sc minute /mo 20 /tn "{{task_name}}" /tr {{path\to\program}}`

- Schedule a program to run every day at a given time:

`schtasks /create /tn {{task_name}} /tr {{path\to\program}} /sc daily /st {{08:00}}`

- Schedule a program to run every time the system starts:

`schtasks /create /tn {{task_name}} /tr {{path\to\program}} /sc onstart`

- Run a scheduled task now:

`schtasks /run /tn "{{task_name}}"`

- Delete a scheduled task:

`schtasks /delete /tn "{{task_name}}"`

- Delete all scheduled tasks on the computer, including other users' tasks, without confirmation:

`schtasks /delete /tn * /f`
