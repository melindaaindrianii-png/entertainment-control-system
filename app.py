from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash, abort, send_file
import sqlite3, os, uuid, calendar
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(BASE,'entertainment.db')
UPLOAD=os.path.join(BASE,'uploads')
os.makedirs(UPLOAD, exist_ok=True)
app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY','change-this-secret-key')
app.config['MAX_CONTENT_LENGTH']=8*1024*1024
ALLOWED={'jpg','jpeg','png','pdf'}


def db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    return c


def init_db():
    c=db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, name TEXT, role TEXT, manager_id INTEGER, department TEXT DEFAULT 'Marketing');
    CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT, request_no TEXT UNIQUE, member_id INTEGER, company TEXT, people_count INTEGER, place TEXT, amount REAL, entertainment_date TEXT, receipt_file TEXT, status TEXT DEFAULT 'Waiting Approval', rejection_reason TEXT, submitted_at TEXT, approved_at TEXT, approver_id INTEGER, purpose TEXT DEFAULT '', cost_estimation REAL DEFAULT 0, cost_actual REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS entertained_people(id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER, name TEXT, level TEXT);
    CREATE TABLE IF NOT EXISTS budgets(id INTEGER PRIMARY KEY AUTOINCREMENT, month TEXT UNIQUE, department TEXT DEFAULT 'Marketing', amount REAL NOT NULL DEFAULT 0, updated_at TEXT);
    ''')
    # Lightweight migration for databases created by the MVP.
    cols={r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
    if 'department' not in cols:
        c.execute("ALTER TABLE users ADD COLUMN department TEXT DEFAULT 'Marketing'")
    cols={r['name'] for r in c.execute('PRAGMA table_info(requests)').fetchall()}
    for col, typ, default in [('purpose','TEXT',''),('cost_estimation','REAL','0'),('cost_actual','REAL','0')]:
        if col not in cols:
            c.execute(f"ALTER TABLE requests ADD COLUMN {col} {typ} DEFAULT {default!r}")
    if c.execute('SELECT COUNT(*) n FROM users').fetchone()['n']==0:
        users=[
            ('admin','admin123','System Admin','admin',None,'Marketing'),
            ('manager','manager123','Manager One','manager',None,'Marketing'),
            ('member','member123','Member One','member',2,'Marketing'),
            ('member2','member123','Member Two','member',2,'Marketing'),
            ('member3','member123','Member Three','member',2,'Marketing'),
        ]
        for u in users:
            c.execute('INSERT INTO users(username,password,name,role,manager_id,department) VALUES(?,?,?,?,?,?)',(u[0],generate_password_hash(u[1]),u[2],u[3],u[4],u[5]))
    else:
        c.execute("UPDATE users SET department='Marketing' WHERE department IS NULL OR department='' ")
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


def month_bounds(month):
    y,m=map(int,month.split('-'))
    return f'{y:04d}-{m:02d}-01', f'{y:04d}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}'


def dashboard_month():
    m=request.args.get('month','').strip()
    if not m:
        m=datetime.now().strftime('%Y-%m')
    try: datetime.strptime(m,'%Y-%m')
    except ValueError: m=datetime.now().strftime('%Y-%m')
    return m

@app.route('/member')
def member_dashboard():
    r=login_required('member')
    if r:return r
    month=dashboard_month(); start,end=month_bounds(month)
    c=db()
    mine=c.execute('SELECT * FROM requests WHERE member_id=? ORDER BY id DESC',(session['uid'],)).fetchall()
    counts=c.execute("SELECT status,COUNT(*) n FROM requests WHERE member_id=? GROUP BY status",(session['uid'],)).fetchall()
    my_month=c.execute("SELECT COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests WHERE member_id=? AND entertainment_date BETWEEN ? AND ? AND status='Approved'",(session['uid'],start,end)).fetchone()['total'] or 0
    members=c.execute("""SELECT u.id,u.name,COUNT(r.id) request_count,
                       COALESCE(SUM(CASE WHEN r.status='Approved' THEN r.cost_actual ELSE 0 END),0) approved_total,
                       COALESCE(SUM(CASE WHEN r.status IN ('Waiting Approval','Approved','Rejected') THEN r.cost_actual ELSE 0 END),0) submitted_total
                       FROM users u LEFT JOIN requests r ON r.member_id=u.id AND r.entertainment_date BETWEEN ? AND ?
                       WHERE u.role='member' AND u.department='Marketing' GROUP BY u.id,u.name ORDER BY approved_total DESC,u.name""",(start,end)).fetchall()
    dept_actual=c.execute("SELECT COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests r JOIN users u ON u.id=r.member_id WHERE u.department='Marketing' AND r.entertainment_date BETWEEN ? AND ? AND r.status='Approved'",(start,end)).fetchone()['total'] or 0
    budget=c.execute("SELECT amount FROM budgets WHERE month=? AND department='Marketing'",(month,)).fetchone()
    budget_amount=(budget['amount'] if budget else 0) or 0
    pending=c.execute("SELECT COUNT(*) n FROM requests r JOIN users u ON u.id=r.member_id WHERE u.department='Marketing' AND r.status='Waiting Approval'").fetchone()['n']
    c.close()
    status={'Waiting Approval':0,'Approved':0,'Rejected':0}
    for x in counts: status[x['status']]=x['n']
    utilization=(dept_actual/budget_amount*100) if budget_amount else None
    return render_template('member.html',requests=mine,month=month,status=status,members=members,dept_actual=dept_actual,budget_amount=budget_amount,utilization=utilization,pending_dept=pending)

@app.route('/member/new',methods=['GET','POST'])
def new_request():
    r=login_required('member')
    if r:return r
    if request.method=='POST':
        company=request.form['company'].strip(); place=request.form['place'].strip(); purpose=request.form.get('purpose','').strip(); datev=request.form['entertainment_date'];
        amount=float(request.form.get('amount') or 0); estimation=float(request.form.get('cost_estimation') or amount); actual=float(request.form.get('cost_actual') or amount)
        count=int(request.form.get('people_count') or 0)
        names=request.form.getlist('person_name'); levels=request.form.getlist('person_level')
        if not company or not place or not datev or not purpose or count<1 or len(names)!=count or any(not x.strip() for x in names):
            flash('Please complete all required fields.','error'); return render_template('new_request.html')
        receipt=request.files.get('receipt'); filename=None
        if receipt and receipt.filename:
            ext=receipt.filename.rsplit('.',1)[-1].lower() if '.' in receipt.filename else ''
            if ext not in ALLOWED: flash('Receipt must be JPG, PNG, or PDF.','error'); return render_template('new_request.html')
            filename=f"{uuid.uuid4().hex}.{ext}"; receipt.save(os.path.join(UPLOAD,filename))
        reqno='ENT-'+datetime.now().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:5].upper()
        c=db(); cur=c.execute('''INSERT INTO requests(request_no,member_id,company,people_count,place,amount,entertainment_date,receipt_file,status,submitted_at,purpose,cost_estimation,cost_actual)
                                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(reqno,session['uid'],company,count,place,actual,datev,filename,'Waiting Approval',datetime.now().isoformat(timespec='seconds'),purpose,estimation,actual)); rid=cur.lastrowid
        for n,l in zip(names,levels): c.execute('INSERT INTO entertained_people(request_id,name,level) VALUES(?,?,?)',(rid,n.strip(),l.strip()))
        c.commit(); c.close(); return redirect(url_for('member_dashboard'))
    return render_template('new_request.html')

@app.route('/request/<int:rid>')
def request_detail(rid):
    r=login_required(('member','manager','admin'))
    if r:return r
    c=db(); req=c.execute('''SELECT r.*,u.name member_name,a.name approver_name FROM requests r JOIN users u ON u.id=r.member_id LEFT JOIN users a ON a.id=r.approver_id WHERE r.id=?''',(rid,)).fetchone(); people=c.execute('SELECT * FROM entertained_people WHERE request_id=?',(rid,)).fetchall(); c.close()
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
    r=login_required('admin')
    if r:return r
    month=dashboard_month(); c=db()
    users=c.execute('SELECT id,username,name,role,department FROM users ORDER BY id').fetchall(); stats=c.execute("SELECT status,COUNT(*) n,COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests GROUP BY status").fetchall(); rows=c.execute('SELECT r.*,u.name member_name FROM requests r JOIN users u ON u.id=r.member_id ORDER BY r.id DESC LIMIT 100').fetchall();
    b=c.execute("SELECT amount FROM budgets WHERE month=? AND department='Marketing'",(month,)).fetchone(); budget=b['amount'] if b else 0
    c.close(); return render_template('admin.html',users=users,stats=stats,rows=rows,month=month,budget=budget)

@app.route('/admin/budget',methods=['POST'])
def set_budget():
    r=login_required('admin')
    if r:return r
    month=request.form.get('month','').strip(); amount=float(request.form.get('budget') or 0)
    try: datetime.strptime(month,'%Y-%m')
    except ValueError: flash('Invalid month.','error'); return redirect(url_for('admin_dashboard'))
    c=db(); c.execute("INSERT INTO budgets(month,department,amount,updated_at) VALUES(?,?,?,?) ON CONFLICT(month) DO UPDATE SET amount=excluded.amount,updated_at=excluded.updated_at",(month,'Marketing',amount,datetime.now().isoformat(timespec='seconds'))); c.commit(); c.close(); flash('Marketing monthly budget updated.','message'); return redirect(url_for('admin_dashboard',month=month))

@app.route('/download/<int:rid>')
def download(rid):
    r=login_required(('member','manager','admin'))
    if r:return r
    c=db(); req=c.execute('''SELECT r.*,u.name member_name,a.name approver_name FROM requests r JOIN users u ON u.id=r.member_id LEFT JOIN users a ON a.id=r.approver_id WHERE r.id=?''',(rid,)).fetchone(); people=c.execute('SELECT * FROM entertained_people WHERE request_id=? ORDER BY id',(rid,)).fetchall(); c.close()
    if not req or (session['role']=='member' and req['member_id']!=session['uid']): abort(403)
    # One-page PDF inspired by the uploaded Excel form. Receipt is kept in the system, not embedded in the form.
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.units import mm
    import io
    buf=io.BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=13*mm,leftMargin=13*mm,topMargin=10*mm,bottomMargin=10*mm)
    styles=getSampleStyleSheet()
    title=ParagraphStyle('formtitle',parent=styles['Title'],fontName='Helvetica',fontSize=17,leading=19,alignment=TA_CENTER,spaceAfter=5)
    small=ParagraphStyle('small',parent=styles['Normal'],fontName='Helvetica',fontSize=7.5,leading=9)
    label=ParagraphStyle('label',parent=small,fontName='Helvetica-Bold')
    center=ParagraphStyle('center',parent=small,alignment=TA_CENTER)
    story=[]
    story.append(Paragraph('PT. SUGITY CREATIVES',small))
    story.append(Spacer(1,2*mm)); story.append(Paragraph('ENTERTAINMENT FORM',title)); story.append(Spacer(1,1*mm))
    def line(text): return Paragraph(text + '<u>                                                                 </u>', small)
    header=Table([
        [Paragraph('<b>* Company</b>',small), Paragraph(': '+str(req['company']),small), Paragraph('<b>* Date</b>',small), Paragraph(': '+str(req['entertainment_date']),small)],
    ], colWidths=[25*mm,82*mm,20*mm,63*mm])
    header.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BOTTOMPADDING',(0,0),(-1,-1),4)])); story.append(header)
    rows=[]
    people10=list(people)[:10]
    while len(people10)<10: people10.append(None)
    for i in range(5):
        p1=people10[i]; p2=people10[i+5]
        rows.append([Paragraph('Name (Title)' if i==0 else '',small), Paragraph(f'{i+1}.',small), Paragraph((p1['name'] if p1 else ''),small), Paragraph(f'{i+6}.',small), Paragraph((p2['name'] if p2 else ''),small)])
    pt=Table(rows,colWidths=[26*mm,8*mm,70*mm,8*mm,70*mm],rowHeights=[7.5*mm]*5)
    pt.setStyle(TableStyle([('BOX',(1,0),(-1,-1),.6,colors.black),('INNERGRID',(1,0),(-1,-1),.35,colors.black),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4)])); story.append(pt)
    purpose=str(req['purpose'] or '')
    details=Table([
        [Paragraph('<b>* Purpose</b>',small), Paragraph(': '+purpose,small), Paragraph('<b>* Cost Estimation</b>',small), Paragraph(': Rp '+f"{req['cost_estimation']:,.0f}",small)],
        ['', '', Paragraph('<b>* Cost Actual</b>',small), Paragraph(': Rp '+f"{req['cost_actual']:,.0f}",small)],
        ['', '', Paragraph('<b>* Place</b>',small), Paragraph(': '+str(req['place']),small)],
    ],colWidths=[26*mm,82*mm,35*mm,39*mm],rowHeights=[9*mm,8*mm,8*mm])
    details.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(1,0),(1,-1),.35,colors.black),('LINEBELOW',(3,0),(3,-1),.35,colors.black),('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2)])); story.append(Spacer(1,2*mm)); story.append(details)
    member_rows=[['Sugity Members','','Proposed Division','MGR','GM','DIR','Accounting'],['','','PLAN','','','', ''],['','','ACTUAL','','','', '']]
    # Put submitted member and approver into the lower section without inventing approval hierarchy.
    member_rows[1][0]=req['member_name']; member_rows[2][0]=req['approver_name'] or ''
    member_rows[1][2]='PLAN'; member_rows[2][2]='ACTUAL'; member_rows[1][6]=''; member_rows[2][6]=''
    lower=Table(member_rows,colWidths=[35*mm,18*mm,22*mm,22*mm,22*mm,22*mm,31*mm],rowHeights=[8*mm,13*mm,13*mm])
    lower.setStyle(TableStyle([('SPAN',(0,0),(1,0)),('SPAN',(2,0),(5,0)),('BOX',(0,0),(-1,-1),.6,colors.black),('INNERGRID',(0,0),(-1,-1),.35,colors.black),('BACKGROUND',(0,0),(-1,0),colors.whitesmoke),('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('FONTSIZE',(0,0),(-1,-1),7)])); story.append(Spacer(1,3*mm)); story.append(lower)
    story.append(Spacer(1,2*mm)); story.append(Paragraph(f'Request No.: {req["request_no"]} &nbsp;&nbsp; Status: {req["status"]} &nbsp;&nbsp; Receipt: retained in system',small))
    doc.build(story); buf.seek(0)
    return send_file(buf,as_attachment=True,download_name=f"{req['request_no']}.pdf",mimetype='application/pdf')

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True)
