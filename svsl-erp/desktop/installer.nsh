; Allow phones / other office computers on PRIVATE networks to reach the ERP on port 8000.
!macro customInstall
  nsExec::Exec 'netsh advfirewall firewall delete rule name="SVSL ERP"'
  nsExec::Exec 'netsh advfirewall firewall add rule name="SVSL ERP" dir=in action=allow protocol=TCP localport=8000 profile=private,domain'
!macroend
!macro customUnInstall
  nsExec::Exec 'netsh advfirewall firewall delete rule name="SVSL ERP"'
!macroend
