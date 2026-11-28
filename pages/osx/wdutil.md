# wdutil

> Wireless Diagnostics from the command line: Wi-Fi status, diagnostics and logging.
> Requires root privileges.
> More information: <https://keith.github.io/xcode-man-pages/wdutil.8.html>.

- Show information about the current Wi-Fi connection and wireless environment:

`sudo wdutil info`

- Run all wireless diagnostic tests:

`sudo wdutil diagnose`

- Dump the temporary Wi-Fi log buffer to a file in `/tmp`:

`sudo wdutil dump`

- Enable Wi-Fi logging:

`sudo wdutil log +wifi`

- Disable Wi-Fi logging:

`sudo wdutil log -wifi`
