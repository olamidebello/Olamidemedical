"""Consistent SQLite backup: python deploy/backup.py /secure/path/backup.db"""
import os, sqlite3, sys
from pathlib import Path
source=os.environ.get('DATABASE_PATH',str(Path(__file__).resolve().parents[1]/'data/hospital.db'))
if len(sys.argv)!=2:raise SystemExit('Provide a destination backup path')
destination=Path(sys.argv[1])
if destination.exists():raise SystemExit('Destination already exists')
with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:src.backup(dst)
destination.chmod(0o600)
print('Backup completed')
