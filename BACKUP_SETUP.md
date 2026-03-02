# DB Backup to AWS EC2

This project includes `db_backup_to_ec2.py` to:
- take a safe SQLite snapshot backup,
- compress it (`.db.gz`),
- store it in a separate local backup directory,
- upload it to AWS EC2 over SSH/SCP,
- delete old local and remote backups.

## 1) Configure

Create `backup_config.json` from template:

```bash
cp backup_config.json.example backup_config.json
```

Update:
- `ec2_host`
- `ec2_user`
- `ssh_key_file`
- `remote_backup_dir`
- retention values:
  - `keep_local_days`
  - `keep_remote_days`

Desktop EXE flow:
- On desktop app startup (`desktop_main.py`), backup runs once per day in background.
- Config file is first searched at app-data path:
  - Windows: `%APPDATA%\ELTA_Workshop_Suite\backup_config.json`
  - Linux/macOS: `~/.ELTA_Workshop_Suite/backup_config.json`
- If missing, template is auto-copied there (from `backup_config.json.example` when available).

If `local_backup_dir` is empty, default is:
- Windows: `%APPDATA%/ELTA_Workshop_Suite/db_backups`
- Linux/macOS: `~/.ELTA_Workshop_Suite/db_backups`

## 2) Test

Dry run (local backup only):

```bash
python db_backup_to_ec2.py --dry-run
```

Full run:

```bash
python db_backup_to_ec2.py
```

## 3) Run Daily

### Linux (cron)

Run daily at 1:30 AM:

```bash
30 1 * * * /usr/bin/python3 /path/to/elta_workshop/db_backup_to_ec2.py >> /path/to/elta_workshop/backup.log 2>&1
```

### Windows (Task Scheduler)

Create a daily task that runs:

- Program: `python`
- Arguments: `db_backup_to_ec2.py`
- Start in: `<project_folder>`

Use an account that can access:
- DB file location
- SSH key file
- network route to EC2
