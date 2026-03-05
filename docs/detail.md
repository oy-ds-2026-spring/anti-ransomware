## Project Structure

```text
.
├── client
├── common
├── dashboard
│   ├── static
│   │   ├── css
│   │   └── js
│   └── templates
├── detection
├── docs
├── gateway
├── kerberos
├── pics
├── proto
├── recovery
│   ├── backup
│   └── message_bus
├── secrets
├── secure_backups
│   └── restic_repos
|	    └── finance
├── simulation_data
│   ├── finance1
│   ├── finance2
│   ├── finance3
│   └── finance4
└── tmp_scripts
```

The project has 11 components.

1. client1 (storage node, its name `finance` means it's for finance departmant)
2. client2
3. client3
4. client4
5. gateway (routes external requests)
6. detection (monitor and detect malware behaviors)
7. backup-storage (for snapshot and recovery)
8. rest-server (for snapshot)
9. kdc-server (authentication center)
10. rabbitmq (for message queue)
11. dashboard (deprecated dashboard)
