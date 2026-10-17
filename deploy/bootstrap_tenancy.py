"""Provision a platform administrator from protected stdin without exposing passwords."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

def main():
    data=json.load(sys.stdin)
    server.init_db()
    username=data.get('username','platformadmin')
    with server.connect() as c:existing=c.execute('SELECT role FROM users WHERE username=?',(username,)).fetchone()
    if existing:
        if existing['role']!='super_admin':raise ValueError('Choose a separate platform username; existing hospital accounts are not elevated')
        print(json.dumps({'changed':False}));return
    server.add_user(username,data.get('password',''),'super_admin')
    print(json.dumps({'changed':True}))

if __name__=='__main__':main()
