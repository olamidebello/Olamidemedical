"""Create deduplicated local operational alerts; no external messages are sent."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server


def run():
    with server.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for table,predicate,title,audience in [
          ('critical_results',"julianday(due_at)<=julianday('now') AND status!='resolved'",'Critical result follow-up overdue','clinical'),
          ('referral_followups',"julianday(due_at)<=julianday('now') AND status NOT IN ('completed','cancelled')",'Referral follow-up overdue','clinical'),
          ('transition_tasks',"julianday(due_at)<=julianday('now') AND status NOT IN ('completed','cancelled')",'Care transition task overdue','clinical'),
          ('inventory',"CAST(quantity AS INTEGER)<=CAST(reorder_level AS INTEGER)",'Low stock','clinical'),
          ('inventory',"expiry IS NOT NULL AND expiry<=date('now','+30 days')",'Stock expiry review','clinical'),
          ('professionals',"license_expiry IS NOT NULL AND license_expiry<=date('now','+30 days')",'Credential expiry review','admin'),
          ('policies',"coverage_end IS NOT NULL AND coverage_end<=date('now','+30 days') AND status NOT IN ('expired','cancelled')",'Coverage expiry review','billing'),
          ('authorizations',"expires IS NOT NULL AND expires<=date('now','+7 days') AND status='approved'",'Authorization expiry review','billing'),
          ('coupons',"expires IS NOT NULL AND expires<=date('now','+7 days') AND status='active'",'Coupon expiry review','billing')
        ]:
            for row in c.execute(f'SELECT id,hospital_id FROM {table} WHERE '+predicate):
                if not c.execute('SELECT 1 FROM hospitals WHERE id=? AND active=1',(row['hospital_id'],)).fetchone():continue
                key=title+' · '+table+' #'+str(row['id'])
                # One durable alert per condition/record; operators review or reopen it.
                if c.execute('SELECT 1 FROM alerts WHERE hospital_id=? AND title=?',(row['hospital_id'],key)).fetchone():continue
                c.execute("INSERT INTO alerts(hospital_id,title,message,severity,audience,status,created_by) VALUES(?,?,?,'warning',?,'open','system')",(row['hospital_id'],key,'Review the corresponding record in '+table+'.',audience))
                c.execute("INSERT INTO audit(actor,action,resource,record_id,hospital_id) VALUES('system','alert-create',?, ?, ?)",(table,row['id'],row['hospital_id']))

if __name__=='__main__':run()
