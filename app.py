from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash, abort, send_file
import sqlite3, os, uuid, calendar, json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(BASE,'entertainment.db')
UPLOAD=os.path.join(BASE,'uploads')
os.makedirs(UPLOAD, exist_ok=True)
app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY','change-this-secret-key')
app.config['MAX_CONTENT_LENGTH']=24*1024*1024
ALLOWED={'jpg','jpeg','png','pdf'}


def db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    return c


def init_db():
    c=db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, name TEXT, role TEXT, manager_id INTEGER, department TEXT DEFAULT 'Marketing', must_change_password INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT, request_no TEXT UNIQUE, member_id INTEGER, company TEXT, people_count INTEGER, place TEXT, amount REAL, entertainment_date TEXT, receipt_file TEXT, receipt_files TEXT DEFAULT '', status TEXT DEFAULT 'Waiting Approval', rejection_reason TEXT, submitted_at TEXT, approved_at TEXT, approver_id INTEGER, purpose TEXT DEFAULT '', cost_estimation REAL DEFAULT 0, cost_actual REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS entertained_people(id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER, name TEXT, level TEXT);
    CREATE TABLE IF NOT EXISTS sugity_members(id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER, name TEXT);
    CREATE TABLE IF NOT EXISTS budgets(id INTEGER PRIMARY KEY AUTOINCREMENT, month TEXT UNIQUE, department TEXT DEFAULT 'Marketing', amount REAL NOT NULL DEFAULT 0, updated_at TEXT);
    ''')
    cols={r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
    if 'department' not in cols: c.execute("ALTER TABLE users ADD COLUMN department TEXT DEFAULT 'Marketing'")
    if 'must_change_password' not in cols:
        c.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 1")
    cols={r['name'] for r in c.execute('PRAGMA table_info(requests)').fetchall()}
    for col, typ, default in [('purpose','TEXT',''),('cost_estimation','REAL','0'),('cost_actual','REAL','0'),('receipt_files','TEXT','')]:
        if col not in cols: c.execute(f"ALTER TABLE requests ADD COLUMN {col} {typ} DEFAULT {default!r}")
    if c.execute('SELECT COUNT(*) n FROM users').fetchone()['n']==0:
        users=[
            ('admin','admin123','System Admin','admin',None,'Marketing'),
            ('manager','manager123','Manager One','manager',None,'Marketing'),
            ('member','member123','Member One','member',2,'Marketing'),
            ('member2','member123','Member Two','member',2,'Marketing'),
            ('member3','member123','Member Three','member',2,'Marketing'),
        ]
        for u in users:
            c.execute('INSERT INTO users(username,password,name,role,manager_id,department,must_change_password) VALUES(?,?,?,?,?,?,1)',(u[0],generate_password_hash(u[1]),u[2],u[3],u[4],u[5]))
    else:
        c.execute("UPDATE users SET department='Marketing' WHERE department IS NULL OR department='' ")
        # Existing demo accounts must also change the initial/demo password once.
        c.execute("UPDATE users SET must_change_password=1 WHERE username IN ('admin','manager','member','member2','member3') AND must_change_password IS NULL")
    c.commit(); c.close()

init_db()


def login_required(role=None):
    if 'uid' not in session: return redirect(url_for('login'))
    if role and session.get('role') not in (role if isinstance(role,tuple) else (role,)): abort(403)
    c=db(); u=c.execute('SELECT must_change_password FROM users WHERE id=?',(session['uid'],)).fetchone(); c.close()
    if u and u['must_change_password'] and request.endpoint not in ('change_password','logout','static'):
        return redirect(url_for('change_password'))
    return None


def current_user():
    if 'uid' not in session:return None
    c=db(); u=c.execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone(); c.close(); return u

@app.context_processor
def inject(): return {'current_user':current_user()}

@app.template_filter('idr')
def idr(value):
    try: return 'Rp. {:,.0f}'.format(float(value or 0))
    except: return 'Rp. 0'

@app.route('/')
def index():
    if 'uid' not in session:return redirect(url_for('login'))
    if current_user()['must_change_password']: return redirect(url_for('change_password'))
    if session['role']=='member': return redirect(url_for('member_dashboard'))
    if session['role']=='manager': return redirect(url_for('manager_dashboard'))
    return redirect(url_for('admin_dashboard'))

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        c=db(); u=c.execute('SELECT * FROM users WHERE username=?',(request.form['username'].strip(),)).fetchone(); c.close()
        if u and check_password_hash(u['password'],request.form['password']):
            session.clear(); session.update(uid=u['id'],role=u['role'],name=u['name'], dash_start=datetime.now().strftime('%Y-%m'), dash_end=datetime.now().strftime('%Y-%m'), admin_month=datetime.now().strftime('%Y-%m'))
            if u['must_change_password']: return redirect(url_for('change_password'))
            return redirect(url_for('index'))
        flash('Invalid username or password','error')
    return render_template('login.html')

@app.route('/change-password',methods=['GET','POST'])
def change_password():
    if 'uid' not in session:return redirect(url_for('login'))
    if request.method=='POST':
        current=request.form.get('current_password','')
        new=request.form.get('new_password','')
        confirm=request.form.get('confirm_password','')
        c=db(); u=c.execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone()
        if not u or not check_password_hash(u['password'],current):
            c.close(); flash('Current password is incorrect.','error'); return render_template('change_password.html')
        if len(new)<8: c.close(); flash('New password must be at least 8 characters.','error'); return render_template('change_password.html')
        if new!=confirm: c.close(); flash('New password and confirmation do not match.','error'); return render_template('change_password.html')
        c.execute('UPDATE users SET password=?,must_change_password=0 WHERE id=?',(generate_password_hash(new),session['uid'])); c.commit(); c.close()
        flash('Password changed successfully.','message'); return redirect(url_for('index'))
    return render_template('change_password.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))


def month_bounds(month):
    y,m=map(int,month.split('-'))
    return f'{y:04d}-{m:02d}-01', f'{y:04d}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}'


def valid_month(m):
    try: datetime.strptime(m,'%Y-%m'); return True
    except: return False


def dashboard_range():
    today=datetime.now().strftime('%Y-%m')
    # Range is stored in the login session. It stays unchanged across
    # request submissions/navigation and only resets on the next login.
    start=request.args.get('start_month','').strip()
    end=request.args.get('end_month','').strip()
    if start or end:
        start=start if valid_month(start) else session.get('dash_start',today)
        end=end if valid_month(end) else session.get('dash_end',today)
        if start>end: start,end=end,start
        sy,sm=map(int,start.split('-')); ey,em=map(int,end.split('-'))
        span=(ey-sy)*12+(em-sm)+1
        if span>36:
            end=add_months(start,35)
        session['dash_start'],session['dash_end']=start,end
    else:
        start=session.get('dash_start',today)
        end=session.get('dash_end',today)
        if not valid_month(start): start=today
        if not valid_month(end): end=today
        if start>end: start,end=end,start
    return start,end


def add_months(month, delta):
    y,m=map(int,month.split('-')); idx=y*12+(m-1)+delta; yy=idx//12; mm=idx%12+1; return f'{yy:04d}-{mm:02d}'


def dashboard_data(c, user_id=None):
    start,end=dashboard_range(); sdate,_=month_bounds(start); _,edate=month_bounds(end)
    where_member='AND member_id=?' if user_id else ''
    params=[user_id,sdate,edate] if user_id else [sdate,edate]
    counts=c.execute(f"SELECT status,COUNT(*) n FROM requests WHERE 1=1 {where_member} GROUP BY status",params[:1] if user_id else []).fetchall()
    # Correct parameter order for date/member-specific queries.
    if user_id:
        mine=c.execute('SELECT * FROM requests WHERE member_id=? ORDER BY id DESC',(user_id,)).fetchall()
        my_sub=c.execute("SELECT COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests WHERE member_id=? AND entertainment_date BETWEEN ? AND ? AND status IN ('Waiting Approval','Approved','Rejected')",(user_id,sdate,edate)).fetchone()['total'] or 0
        my_approved=c.execute("SELECT COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests WHERE member_id=? AND entertainment_date BETWEEN ? AND ? AND status='Approved'",(user_id,sdate,edate)).fetchone()['total'] or 0
    else:
        mine=[]; my_sub=0; my_approved=0
    members=c.execute("""SELECT u.id,u.name,COUNT(r.id) request_count,
                       COALESCE(SUM(CASE WHEN r.status='Approved' THEN r.cost_actual ELSE 0 END),0) approved_total,
                       COALESCE(SUM(CASE WHEN r.status IN ('Waiting Approval','Approved','Rejected') THEN r.cost_actual ELSE 0 END),0) submitted_total
                       FROM users u LEFT JOIN requests r ON r.member_id=u.id AND r.entertainment_date BETWEEN ? AND ?
                       WHERE u.role='member' AND u.department='Marketing' GROUP BY u.id,u.name ORDER BY approved_total DESC,u.name""",(sdate,edate)).fetchall()
    dept_sub=c.execute("SELECT COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests r JOIN users u ON u.id=r.member_id WHERE u.department='Marketing' AND r.entertainment_date BETWEEN ? AND ? AND r.status IN ('Waiting Approval','Approved','Rejected')",(sdate,edate)).fetchone()['total'] or 0
    dept_approved=c.execute("SELECT COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests r JOIN users u ON u.id=r.member_id WHERE u.department='Marketing' AND r.entertainment_date BETWEEN ? AND ? AND r.status='Approved'",(sdate,edate)).fetchone()['total'] or 0
    pending=c.execute("SELECT COUNT(*) n FROM requests r JOIN users u ON u.id=r.member_id WHERE u.department='Marketing' AND r.status='Waiting Approval'").fetchone()['n']
    chart=[]
    cur=start
    while cur<=end:
        actual=c.execute("SELECT COALESCE(SUM(r.cost_actual),SUM(r.amount),0) total FROM requests r JOIN users u ON u.id=r.member_id WHERE u.department='Marketing' AND r.status='Approved' AND strftime('%Y-%m',r.entertainment_date)=?",(cur,)).fetchone()['total'] or 0
        submitted=c.execute("SELECT COALESCE(SUM(r.cost_actual),SUM(r.amount),0) total FROM requests r JOIN users u ON u.id=r.member_id WHERE u.department='Marketing' AND r.status IN ('Waiting Approval','Approved','Rejected') AND strftime('%Y-%m',r.entertainment_date)=?",(cur,)).fetchone()['total'] or 0
        b=c.execute("SELECT amount FROM budgets WHERE month=? AND department='Marketing'",(cur,)).fetchone()
        chart.append({'month':cur,'label':datetime.strptime(cur,'%Y-%m').strftime("%b'%y"),'actual':float(actual),'submitted':float(submitted),'budget':float(b['amount']) if b else 0})
        cur=add_months(cur,1)
    status={'Waiting Approval':0,'Approved':0,'Rejected':0}
    for x in counts: status[x['status']]=x['n']
    return dict(start_month=start,end_month=end,requests=mine,status=status,members=members,my_submitted=my_sub,my_approved=my_approved,dept_submitted=dept_sub,dept_approved=dept_approved,pending_dept=pending,chart_months=chart)

@app.route('/member')
def member_dashboard():
    r=login_required('member')
    if r:return r
    c=db(); data=dashboard_data(c,session['uid']); c.close()
    return render_template('member.html',**data)

@app.route('/manager')
def manager_dashboard():
    r=login_required('manager')
    if r:return r
    c=db(); data=dashboard_data(c,None)
    waiting=c.execute("SELECT r.*,u.name member_name FROM requests r JOIN users u ON u.id=r.member_id WHERE r.status='Waiting Approval' ORDER BY r.id DESC").fetchall()
    history=c.execute("SELECT r.*,u.name member_name FROM requests r JOIN users u ON u.id=r.member_id WHERE r.status!='Waiting Approval' ORDER BY r.id DESC LIMIT 100").fetchall(); c.close()
    return render_template('manager.html',waiting=waiting,history=history,**data)

@app.route('/member/new',methods=['GET','POST'])
def new_request():
    r=login_required('member')
    if r:return r
    if request.method=='POST':
        company=request.form['company'].strip(); place=request.form['place'].strip(); purpose=request.form.get('purpose','').strip(); datev=request.form['entertainment_date']
        try: estimation=float(request.form.get('cost_estimation') or 0); actual=float(request.form.get('cost_actual') or 0)
        except ValueError: flash('Cost must be a valid number.','error'); return render_template('new_request.html')
        count=int(request.form.get('people_count') or 0)
        names=request.form.getlist('person_name'); levels=request.form.getlist('person_level')
        sugity_names=[x.strip() for x in request.form.getlist('sugity_member') if x.strip()]
        receipts=request.files.getlist('receipt')
        valid_receipts=[f for f in receipts if f and f.filename]
        if not company or not place or not datev or not purpose or count<1 or count>10 or len(names)!=count or any(not x.strip() for x in names) or len(sugity_names)>7 or not valid_receipts:
            flash('Please complete all required fields. Enter 1–10 customers, up to 7 Sugity Members, and at least 1 receipt.','error'); return render_template('new_request.html')
        saved=[]
        for receipt in valid_receipts:
            ext=receipt.filename.rsplit('.',1)[-1].lower() if '.' in receipt.filename else ''
            if ext not in ALLOWED: flash('Receipt files must be JPG, PNG, or PDF.','error'); return render_template('new_request.html')
            filename=f"{uuid.uuid4().hex}.{ext}"; receipt.save(os.path.join(UPLOAD,filename)); saved.append(filename)
        reqno='ENT-'+datetime.now().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:5].upper()
        c=db(); cur=c.execute('''INSERT INTO requests(request_no,member_id,company,people_count,place,amount,entertainment_date,receipt_file,receipt_files,status,submitted_at,purpose,cost_estimation,cost_actual)
                                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(reqno,session['uid'],company,count,place,actual,datev,saved[0],json.dumps(saved),'Waiting Approval',datetime.now().isoformat(timespec='seconds'),purpose,estimation,actual)); rid=cur.lastrowid
        for n,l in zip(names,levels): c.execute('INSERT INTO entertained_people(request_id,name,level) VALUES(?,?,?)',(rid,n.strip(),l.strip()))
        for n in sugity_names: c.execute('INSERT INTO sugity_members(request_id,name) VALUES(?,?)',(rid,n))
        c.commit(); c.close(); return redirect(url_for('member_dashboard'))
    return render_template('new_request.html')

@app.route('/request/<int:rid>')
def request_detail(rid):
    r=login_required(('member','manager','admin'))
    if r:return r
    c=db(); req=c.execute('''SELECT r.*,u.name member_name,a.name approver_name FROM requests r JOIN users u ON u.id=r.member_id LEFT JOIN users a ON a.id=r.approver_id WHERE r.id=?''',(rid,)).fetchone(); people=c.execute('SELECT * FROM entertained_people WHERE request_id=? ORDER BY id',(rid,)).fetchall(); sugity=c.execute('SELECT * FROM sugity_members WHERE request_id=? ORDER BY id',(rid,)).fetchall(); c.close()
    if not req: abort(404)
    if session['role']=='member' and req['member_id']!=session['uid']: abort(403)
    try: receipt_files=json.loads(req['receipt_files'] or '') if req['receipt_files'] else ([req['receipt_file']] if req['receipt_file'] else [])
    except: receipt_files=[req['receipt_file']] if req['receipt_file'] else []
    return render_template('detail.html',req=req,people=people,sugity=sugity,receipt_files=receipt_files)

@app.route('/receipt/<filename>')
def receipt(filename):
    if 'uid' not in session: abort(403)
    return send_from_directory(UPLOAD,filename,as_attachment=False)

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
    requested_month=request.args.get('month','').strip()
    if requested_month and valid_month(requested_month):
        month=requested_month
        session['admin_month']=month
    else:
        month=session.get('admin_month',datetime.now().strftime('%Y-%m'))
        if not valid_month(month):
            month=datetime.now().strftime('%Y-%m')
            session['admin_month']=month
    c=db(); users=c.execute('SELECT id,username,name,role,department,must_change_password FROM users ORDER BY id').fetchall(); managers=c.execute("SELECT id,name FROM users WHERE role='manager' ORDER BY name").fetchall(); stats=c.execute("SELECT status,COUNT(*) n,COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests GROUP BY status").fetchall(); rows=c.execute('SELECT r.*,u.name member_name FROM requests r JOIN users u ON u.id=r.member_id ORDER BY r.id DESC LIMIT 100').fetchall()
    budget=c.execute("SELECT amount FROM budgets WHERE month=? AND department='Marketing'",(month,)).fetchone(); budget=budget['amount'] if budget else 0
    summary=[]; start=add_months(month,-11)
    cur=start
    while cur<=month:
        b=c.execute("SELECT amount FROM budgets WHERE month=? AND department='Marketing'",(cur,)).fetchone()
        sub=c.execute("SELECT COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests r JOIN users u ON u.id=r.member_id WHERE u.department='Marketing' AND r.status IN ('Waiting Approval','Approved','Rejected') AND strftime('%Y-%m',r.entertainment_date)=?",(cur,)).fetchone()['total'] or 0
        appr=c.execute("SELECT COALESCE(SUM(cost_actual),SUM(amount),0) total FROM requests r JOIN users u ON u.id=r.member_id WHERE u.department='Marketing' AND r.status='Approved' AND strftime('%Y-%m',r.entertainment_date)=?",(cur,)).fetchone()['total'] or 0
        summary.append({'month':cur,'label':datetime.strptime(cur,'%Y-%m').strftime("%b'%y"),'budget':float(b['amount']) if b else 0,'submitted':float(sub),'approved':float(appr)})
        cur=add_months(cur,1)
    c.close(); return render_template('admin.html',users=users,managers=managers,stats=stats,rows=rows,month=month,budget=budget,summary=summary)

@app.route('/admin/budget',methods=['POST'])
def set_budget():
    r=login_required('admin')
    if r:return r
    month=request.form.get('month','').strip()
    try: amount=float(request.form.get('budget') or 0); datetime.strptime(month,'%Y-%m')
    except ValueError: flash('Invalid month or budget.','error'); return redirect(url_for('admin_dashboard'))
    c=db(); c.execute("INSERT INTO budgets(month,department,amount,updated_at) VALUES(?,?,?,?) ON CONFLICT(month) DO UPDATE SET amount=excluded.amount,updated_at=excluded.updated_at",(month,'Marketing',amount,datetime.now().isoformat(timespec='seconds'))); c.commit(); c.close(); session['admin_month']=month; flash('Marketing monthly budget updated.','message'); return redirect(url_for('admin_dashboard'))

@app.route('/admin/users/create', methods=['POST'])
def create_user():
    r=login_required('admin')
    if r:return r
    username=request.form.get('username','').strip()
    name=request.form.get('name','').strip()
    role=request.form.get('role','member').strip()
    department=request.form.get('department','Marketing').strip() or 'Marketing'
    password=request.form.get('password','')
    manager_id=request.form.get('manager_id','').strip() or None
    if role not in ('member','manager','admin'):
        flash('Invalid role.','error'); return redirect(url_for('admin_dashboard'))
    if len(password)<8:
        flash('Initial password must be at least 8 characters.','error'); return redirect(url_for('admin_dashboard'))
    if not username or not name:
        flash('Name and username are required.','error'); return redirect(url_for('admin_dashboard'))
    try:
        manager_id=int(manager_id) if manager_id else None
    except ValueError:
        manager_id=None
    c=db()
    try:
        c.execute('INSERT INTO users(username,password,name,role,manager_id,department,must_change_password) VALUES(?,?,?,?,?,?,1)',(username,generate_password_hash(password),name,role,manager_id,department))
        c.commit(); flash(f'Account {username} created. User must change the initial password at first login.','message')
    except sqlite3.IntegrityError:
        flash('Username already exists. Please use another username.','error')
    finally:
        c.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/download/<int:rid>')
def download(rid):
    r=login_required(('member','manager','admin'))
    if r:return r
    c=db(); req=c.execute('''SELECT r.*,u.name member_name,a.name approver_name FROM requests r JOIN users u ON u.id=r.member_id LEFT JOIN users a ON a.id=r.approver_id WHERE r.id=?''',(rid,)).fetchone(); people=c.execute('SELECT * FROM entertained_people WHERE request_id=? ORDER BY id',(rid,)).fetchall(); sugity=c.execute('SELECT * FROM sugity_members WHERE request_id=? ORDER BY id',(rid,)).fetchall(); c.close()
    if not req or (session['role']=='member' and req['member_id']!=session['uid']): abort(403)
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.units import mm
    import io
    buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=13*mm,leftMargin=13*mm,topMargin=9*mm,bottomMargin=9*mm)
    styles=getSampleStyleSheet(); base=ParagraphStyle('f',parent=styles['Normal'],fontName='Helvetica',fontSize=8.5,leading=10); bold=ParagraphStyle('b',parent=base,fontName='Helvetica-Bold'); center=ParagraphStyle('c',parent=base,alignment=TA_CENTER); title=ParagraphStyle('t',parent=base,fontSize=20,leading=22,alignment=TA_CENTER)
    def money(v): return 'Rp. {:,.0f}'.format(float(v or 0))
    def esc(v):
        return str(v or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    story=[Paragraph('PT. SUGITY CREATIVES',base),Spacer(1,2*mm),Paragraph('<u>ENTERTAINMENT FORM</u>',title),Spacer(1,2*mm)]
    header=Table([[Paragraph('<b>* Company</b>',base),Paragraph(': '+esc(req['company']),base),Paragraph('<b>* Date</b>',base),Paragraph(': '+esc(req['entertainment_date']),base)]],colWidths=[28*mm,105*mm,24*mm,102*mm])
    header.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BOTTOMPADDING',(0,0),(-1,-1),2)])); story.append(header)
    ppl=list(people)[:10]
    while len(ppl)<10:ppl.append(None)
    rows=[]
    for i in range(5):
        p1,p2=ppl[i],ppl[i+5]
        def pn(p): return esc(p['name']) + (f" ({esc(p['level'])})" if p and p['level'] else '') if p else ''
        rows.append([Paragraph('Name (Title)' if i==0 else '',base),Paragraph(f'{i+1}.',base),Paragraph(pn(p1),base),Paragraph(f'{i+6}.',base),Paragraph(pn(p2),base)])
    pt=Table(rows,colWidths=[31*mm,10*mm,100*mm,10*mm,108*mm],rowHeights=[8.5*mm]*5)
    pt.setStyle(TableStyle([('BOX',(1,0),(-1,-1),.6,colors.black),('INNERGRID',(1,0),(-1,-1),.35,colors.black),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3)])); story.append(pt)
    details=Table([[Paragraph('<b>* Purpose</b>',base),Paragraph(': '+esc(req['purpose']),base),Paragraph('<b>* Cost Estimation</b>',base),Paragraph(': '+money(req['cost_estimation']),base)],['', '',Paragraph('<b>* Cost Actual</b>',base),Paragraph(': '+money(req['cost_actual']),base)],['','',Paragraph('<b>* Place</b>',base),Paragraph(': '+esc(req['place']),base)]],colWidths=[31*mm,100*mm,40*mm,88*mm],rowHeights=[9*mm,8*mm,8*mm])
    details.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(1,0),(1,-1),.35,colors.black),('LINEBELOW',(3,0),(3,-1),.35,colors.black)])); story.append(Spacer(1,3*mm)); story.append(details)
    sm=[x['name'] for x in sugity][:7]
    while len(sm)<7: sm.append('')
    sugrows=[['Sugity Members','']]+[[sm[i],sm[i+1] if i+1<7 else ''] for i in range(0,7,2)]
    sug=Table(sugrows,colWidths=[45*mm,45*mm],rowHeights=[8*mm]+[6.8*mm]*4)
    sug.setStyle(TableStyle([('SPAN',(0,0),(1,0)),('BOX',(0,0),(-1,-1),.6,colors.black),('INNERGRID',(0,0),(-1,-1),.35,colors.black),('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    div=Table([['Proposed Division','','',''],['','MGR','GM','DIR'],['PLAN','','',''],['ACTUAL','','','']],colWidths=[18*mm,32*mm,32*mm,32*mm],rowHeights=[8*mm,8*mm,6.8*mm,6.8*mm])
    div.setStyle(TableStyle([('SPAN',(0,0),(3,0)),('BOX',(0,0),(-1,-1),.6,colors.black),('INNERGRID',(0,0),(-1,-1),.35,colors.black),('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    acc=Table([['Accounting'],[''],[''],['']],colWidths=[47*mm],rowHeights=[8*mm,8*mm,6.8*mm,6.8*mm])
    acc.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.6,colors.black),('INNERGRID',(0,0),(-1,-1),.35,colors.black),('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    lower=Table([[sug,div,acc]],colWidths=[90*mm,114*mm,47*mm],rowHeights=[35.2*mm]); lower.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)])); story.append(Spacer(1,3*mm)); story.append(lower)
    story.append(Spacer(1,2.5*mm)); meta=Table([[Paragraph(f'Request No.: {esc(req["request_no"])}',base),Paragraph(f'Status: {esc(req["status"])}',base),Paragraph('Receipt: retained in system',base)]],colWidths=[100*mm,70*mm,81*mm]); meta.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),2)])); story.append(meta)
    doc.build(story); buf.seek(0); return send_file(buf,as_attachment=True,download_name=f"{req['request_no']}.pdf",mimetype='application/pdf')

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True)
