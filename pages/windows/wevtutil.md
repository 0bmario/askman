# wevtutil

> Retrieve information about event logs and publishers, query events, and export, archive, or clear logs.
> More information: <https://learn.microsoft.com/windows-server/administration/windows-commands/wevtutil>.

- List the names of all logs:

`wevtutil {{[el|enum-logs]}}`

- Display the configuration of a log:

`wevtutil {{[gl|get-log]}} {{System}}`

- Display the status of a log, such as its size and number of records:

`wevtutil {{[gli|get-loginfo]}} {{Application}}`

- Display the most recent events from a log in text format:

`wevtutil {{[qe|query-events]}} {{Application}} /c:{{3}} /rd:true /f:text`

- Display events from a saved log file:

`wevtutil {{[qe|query-events]}} {{path\to\file.evtx}} /lf:true /f:text`

- Export a log to a file:

`wevtutil {{[epl|export-log]}} {{System}} {{path\to\file.evtx}}`

- Clear a log, saving a backup of its events first:

`wevtutil {{[cl|clear-log]}} {{Application}} /bu:{{path\to\backup.evtx}}`

- List the event publishers on the local computer:

`wevtutil {{[ep|enum-publishers]}}`
