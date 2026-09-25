Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*app.py*' } |
  ForEach-Object { '{0}  started {1}  parent {2}  {3}' -f $_.ProcessId, $_.CreationDate, $_.ParentProcessId, $_.CommandLine }
