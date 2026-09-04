from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash, abort, send_file
import sqlite3, os, uuid
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(BASE,'entertainment.db')
UPLOAD=os.path.join(BASE,'uploads')
os.makedirs(UPLOAD, exist_ok=True)
app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY','change-this-secret-key')
app.config['MAX_CONTENT_LENGTH']=8*1024*1024
ALLOWED={'jpg','jpeg','png','pdf'}

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db();
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, name TEXT, role TEXT, manager_id INTEGER);
    CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT, request_no TEXT UNIQUE, member_id INTEGER, company TEXT, people_count INTEGER, place TEXT, amount REAL, entertainment_date TEXT, receipt_file TEXT, status TEXT DEFAULT 'Waiting Approval', rejection_reason TEXT, submitted_at TEXT, approved_at TEXT, approver_id INTEGER);
    CREATE TABLE IF NOT EXISTS entertained_people(id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER, name TEXT, level TEXT);
    ''')
    if c.execute('SELECT COUNT(*) n FROM users').fetchone()['n']==0:
        users=[('admin','admin123','System Admin','admin',None),('manager','manager123','Manager One','manager',None),('member','member123','Member One','member',2)]
        for u in users: c.execute('INSERT INTO users(username,password,name,role,manager_id) VALUES(?,?,?,?,?)',(u[0],generate_password_hash(u[1]),u[2],u[3],u[4]))
    c.commit(); c.close()
init_db()

def login_required(role=None):
    if 'uid' not in session: return redirect(url_for('login'))
    if role and session.get('role') not in (role if isinstance(role,tuple) else (role,)): abort(403)
    return None

def current_user():
    if 'uid' not in session:return None
    c=db(); u=c.execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone(); c.close(); return u
@app.context_processor
def inject(): return {'current_user':current_user()}

@app.route('/')
def index():
    if 'uid' not in session:return redirect(url_for('login'))
    if session['role']=='member': return redirect(url_for('member_dashboard'))
    if session['role']=='manager': return redirect(url_for('manager_dashboard'))
    return redirect(url_for('admin_dashboard'))

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        c=db(); u=c.execute('SELECT * FROM users WHERE username=?',(request.form['username'].strip(),)).fetchone(); c.close()
        if u and check_password_hash(u['password'],request.form['password']):
            session.clear(); session.update(uid=u['id'],role=u['role'],name=u['name']); return redirect(url_for('index'))
        flash('Invalid username or password','error')
    return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/member')
def member_dashboard():
    r=login_required('member');
    if r:return r
    c=db(); rows=c.execute('SELECT * FROM requests WHERE member_id=? ORDER BY id DESC',(session['uid'],)).fetchall(); c.close()
    return render_template('member.html',requests=rows)

@app.route('/member/new',methods=['GET','POST'])
def new_request():
    r=login_required('member');
    if r:return r
    if request.method=='POST':
        company=request.form['company'].strip(); place=request.form['place'].strip(); date=request.form['entertainment_date']; amount=float(request.form['amount'] or 0); count=int(request.form['people_count'] or 0)
        names=request.form.getlist('person_name'); levels=request.form.getlist('person_level')
        if not company or not place or not date or count<1 or len(names)!=count or any(not x.strip() for x in names): flash('Please complete all required fields.','error'); return render_template('new_request.html')
        receipt=request.files.get('receipt'); filename=None
        if receipt and receipt.filename:
            ext=receipt.filename.rsplit('.',1)[-1].lower() if '.' in receipt.filename else ''
            if ext not in ALLOWED: flash('Receipt must be JPG, PNG, or PDF.','error'); return render_template('new_request.html')
            filename=f"{uuid.uuid4().hex}.{ext}"; receipt.save(os.path.join(UPLOAD,filename))
        reqno='ENT-'+datetime.now().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:5].upper()
        c=db(); cur=c.execute('INSERT INTO requests(request_no,member_id,company,people_count,place,amount,entertainment_date,receipt_file,status,submitted_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(reqno,session['uid'],company,count,place,amount,date,filename,'Waiting Approval',datetime.now().isoformat(timespec='seconds'))); rid=cur.lastrowid
        for n,l in zip(names,levels): c.execute('INSERT INTO entertained_people(request_id,name,level) VALUES(?,?,?)',(rid,n.strip(),l.strip()))
        c.commit(); c.close(); return redirect(url_for('member_dashboard'))
    return render_template('new_request.html')

@app.route('/request/<int:rid>')
def request_detail(rid):
    r=login_required(('member','manager','admin'))
    if r:return r
    c=db(); req=c.execute('SELECT r.*,u.name member_name FROM requests r JOIN users u ON u.id=r.member_id WHERE r.id=?',(rid,)).fetchone(); people=c.execute('SELECT * FROM entertained_people WHERE request_id=?',(rid,)).fetchall(); c.close()
    if not req: abort(404)
    if session['role']=='member' and req['member_id']!=session['uid']: abort(403)
    return render_template('detail.html',req=req,people=people)

@app.route('/receipt/<filename>')
def receipt(filename):
    if 'uid' not in session: abort(403)
    return send_from_directory(UPLOAD,filename,as_attachment=False)

@app.route('/manager')
def manager_dashboard():
    r=login_required(('manager','admin'))
    if r:return r
    c=db(); waiting=c.execute("SELECT r.*,u.name member_name FROM requests r JOIN users u ON u.id=r.member_id WHERE r.status='Waiting Approval' ORDER BY r.id DESC").fetchall(); history=c.execute("SELECT r.*,u.name member_name FROM requests r JOIN users u ON u.id=r.member_id WHERE r.status!='Waiting Approval' ORDER BY r.id DESC LIMIT 100").fetchall(); c.close()
    return render_template('manager.html',waiting=waiting,history=history)
@app.route('/request/<int:rid>/approve',methods=['POST'])
def approve(rid):
    r=login_required(('manager','admin'))
    if r:return r
    c=db(); c.execute("UPDATE requests SET status='Approved',approved_at=?,approver_id=? WHERE id=? AND status='Waiting Approval'",(datetime.now().isoformat(timespec='seconds'),session['uid'],rid)); c.commit(); c.close(); return redirect(url_for('manager_dashboard'))
@app.route('/request/<int:rid>/reject',methods=['POST'])
def reject(rid):
    r=login_required(('manager','admin'))
    if r:return r
    reason=request.form.get('reason','').strip() or 'Rejected by manager.'
    c=db(); c.execute("UPDATE requests SET status='Rejected',rejection_reason=?,approved_at=?,approver_id=? WHERE id=? AND status='Waiting Approval'",(reason,datetime.now().isoformat(timespec='seconds'),session['uid'],rid)); c.commit(); c.close(); return redirect(url_for('manager_dashboard'))

@app.route('/admin')
def admin_dashboard():
    r=login_required('admin');
    if r:return r
    c=db(); users=c.execute('SELECT id,username,name,role FROM users ORDER BY id').fetchall(); stats=c.execute("SELECT status,COUNT(*) n,COALESCE(SUM(amount),0) total FROM requests GROUP BY status").fetchall(); rows=c.execute('SELECT r.*,u.name member_name FROM requests r JOIN users u ON u.id=r.member_id ORDER BY r.id DESC LIMIT 100').fetchall(); c.close()
    return render_template('admin.html',users=users,stats=stats,rows=rows)

@app.route('/download/<int:rid>')
def download(rid):
    r=login_required(('member','manager','admin'))
    if r:return r
    c=db(); req=c.execute('SELECT r.*,u.name member_name, a.name approver_name FROM requests r JOIN users u ON u.id=r.member_id LEFT JOIN users a ON a.id=r.approver_id WHERE r.id=?',(rid,)).fetchone(); people=c.execute('SELECT * FROM entertained_people WHERE request_id=?',(rid,)).fetchall(); c.close()
    if not req or (session['role']=='member' and req['member_id']!=session['uid']): abort(403)
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    import io
    buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=18*mm,bottomMargin=18*mm)
    styles=getSampleStyleSheet(); story=[Paragraph('ENTERTAINMENT REPORT',styles['Title']),Spacer(1,8)]
    data=[['Request No.',req['request_no']],['Entertainment Date',req['entertainment_date']],['Submitted By',req['member_name']],['Company',req['company']],['Entertainment Place',req['place']],['Total Amount',f"Rp {req['amount']:,.0f}"],['Status',req['status']]]
    if req['status']=='Rejected': data.append(['Rejection Reason',req['rejection_reason'] or '-'])
    t=Table(data,colWidths=[45*mm,125*mm]); t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.whitesmoke),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),6)])); story += [t,Spacer(1,12),Paragraph('Entertained Persons',styles['Heading2'])]
    pt=Table([['No.','Name','Level']]+[[str(i+1),p['name'],p['level']] for i,p in enumerate(people)],colWidths=[15*mm,95*mm,60*mm]); pt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.whitesmoke),('PADDING',(0,0),(-1,-1),6)])); story += [pt,Spacer(1,12)]
    if req['receipt_file']:
        path=os.path.join(UPLOAD,req['receipt_file'])
        if os.path.exists(path) and req['receipt_file'].lower().endswith(('.jpg','.jpeg','.png')):
            try: story += [Paragraph('Receipt',styles['Heading2']),Image(path,width=120*mm,height=90*mm)]
            except: pass
    story += [Spacer(1,10),Paragraph(f"Approver: {req['approver_name'] or '-'}",styles['Normal']),Paragraph(f"Approval Date: {req['approved_at'] or '-'}",styles['Normal'])]
    doc.build(story); buf.seek(0); return send_file(buf,as_attachment=True,download_name=f"{req['request_no']}.pdf",mimetype='application/pdf')

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True)
