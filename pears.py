# -*- coding: utf-8 -*-
import os, sqlite3
from itertools import izip_longest
from datetime import datetime as dt
from calendar import monthrange
from flask import Flask, render_template, request, redirect, url_for, abort, \
                    session, send_from_directory, jsonify, g, flash
from werkzeug import secure_filename
from werkzeug.security import check_password_hash
from instagram.client import InstagramAPI

app = Flask(__name__, template_folder="html")
app.config['DATABASE'] = os.path.join(os.path.dirname(__file__), "pears.db")
app.config['DEBUG'] = True
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')

months = [
    (2, "February", "red"),
    (3, "March", "#ffd530"),
]
months_dict = {m[0]:m for m in months}

'''
    Used for finding environment variables through configuration
    if a default is not given, the site will raise an exception
'''
def get_env_variable(var_name, default=-1):
    try:
        return os.environ[var_name]
    except KeyError:
        if default != -1:
            return default
        error_msg = "Set the %s os.environment variable" % var_name
        raise Exception(error_msg)

app.config['SECRET_KEY'] = get_env_variable("PEARS_SECRET_KEY")

ig_api = InstagramAPI(client_id=get_env_variable("IG_CLIENT_ID"), client_secret=get_env_variable("IG_CLIENT_SECRET"))

# This is a jinja custom filter
@app.template_filter('strftime')
def _jinja2_filter_datetime(date, fmt=None):
    # convert instagram date string into python date/time
    # pyDate = time.strptime(date,'%a %b %d %H:%M:%S +0000 %Y')
    # raise Exception(date.__class__)
    # return the formatted date.
    return date.strftime(fmt or 'We are the %d, %b %Y')

def connect_db():
    """Connects to the specific database."""
    rv = sqlite3.connect(app.config['DATABASE'])
    rv.row_factory = sqlite3.Row
    return rv

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = connect_db()
    return db

def query_db(query, args=(), one=False, update=False):
    cur = get_db().execute(query, args)
    if update:
        return get_db().commit()
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def insert_db(table, fields=(), args=()):
    # g.db is the database connection
    query = 'INSERT INTO %s (%s) VALUES (%s)' % (
        table,
        ', '.join(fields),
        ', '.join(['?'] * len(args))
    )
    cur = get_db().execute(query, args)
    get_db().commit()
    id = cur.lastrowid
    cur.close()
    return id

def suffix(d):
    return 'th' if 11<=d<=13 else {1:'st',2:'nd',3:'rd'}.get(d%10, 'th')

def custom_strftime(format, t):
    return t.strftime(format).replace('{S}', str(t.day) + suffix(t.day))
        
def user_exists(user):
    return query_db("""SELECT EXISTS(SELECT * FROM user WHERE name = ?)""", [user], one=True)[0]

def email_exists(user):
    return query_db("""SELECT EXISTS(SELECT * FROM user WHERE email = ?)""",[user], one=True)[0]

@app.before_request
def before_request():
  g.user = session.get('user')

'''Access to static files'''
@app.route('/uploads/<user>/<path:filename>')
def uploaded_file(user, filename):
    photo_dir = os.path.join(app.config['UPLOAD_FOLDER'], user)
    ''' need to use this send_from_directory function so that the proper HTTP
        headers are set and HTML audio API can work properly'''
    return send_from_directory(photo_dir, filename)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/photophoto/')
@app.route('/photophoto/<month>/')
def home(month=None):
    as_media = []
    jb_media = []
    recent_media, next = ig_api.user_recent_media(user_id=1759445103)
    for m in recent_media:
        tags = [t.name for t in m.tags] if hasattr(m, "tags") else []
        if "as" in tags:
            as_media.append(m)
        if "jb" in tags:
            jb_media.append(m)
    return render_template('ig_home.html', as_media=as_media, jb_media=jb_media)

@app.route('/photophoto/old/')
@app.route('/photophoto/old/<month>/')
def home_olde(month=None):
    
    imgs = []
    for m_id, m_name, m_color in reversed(months):
        this_month = {"color":m_color, "imgs":[], "name":m_name}
        
        as_imgs = query_db("SELECT * FROM img WHERE month = ? and user=? ORDER BY month DESC, day DESC", (m_id, "alexandersimoes@gmail.com",))
        jb_imgs = query_db("SELECT * FROM img WHERE month = ? and user=? ORDER BY month DESC, day DESC", (m_id, "jnoelbasil@gmail.com",))
        
        for img in izip_longest(as_imgs, jb_imgs):
            new_img = []
            for i in img:
                if i:
                    i = dict(i)
                    i['date'] = custom_strftime('%B {S}', dt(2015, i['month'], i['day']))
                new_img.append(i)
            this_month["imgs"].append(new_img)
        
        imgs.append(this_month)
    
    return render_template('pears.html', imgs=imgs)

@app.route('/photophoto/toc/')
def toc():
    imgs = {}
    for m_id, m_name, m_color in months:
        first_day, days_in_month = monthrange(2015, m_id)
        if m_id == dt.now().month:
            days_in_month = dt.now().day+1
        else:
            days_in_month = days_in_month+1
        imgs[m_name] = {"color":m_color, "imgs":[None] * days_in_month}
        
        month_imgs = query_db("SELECT * FROM img WHERE month=? ORDER BY day DESC", (m_id,))
        for i in month_imgs:
            initials = "as" if "alex" in i["user"] else "jb"
            if len(imgs[m_name]["imgs"]) < i["day"]-1:
                continue
            if not imgs[m_name]["imgs"][i["day"]-1]:
                imgs[m_name]["imgs"][i["day"]-1] = {}
            imgs[m_name]["imgs"][i["day"]-1][initials] = i
    return render_template('toc.html', imgs=imgs)

@app.route('/photophoto/login/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == "POST":
        '''try to find user'''
        user = query_db("SELECT email, password FROM user WHERE email=?", [request.form["email"].lower()], one=True)
        if not user:
            error = "Woopsie wrong username"
            flash(error, "error")
        elif not check_password_hash(user["password"], request.form["pw"]):
            error = "Woopsie wrong password"
            flash(error, "error")
        else:
            session["logged_in"] = True
            session["user"] = user["email"]
            flash("You're so logged in right now", "success")
            return redirect(url_for("home"))
    return render_template("login.html", error=error)

@app.route("/photophoto/logout/")
def logout():
    session.pop("logged_in", None)
    session.pop("user", None)
    flash("yup... you're logged out PEACE", "success")
    return redirect(url_for("home"))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1] in ("JPG", "jpg", "jpeg", "png")

def unique_filename(filename):
    if query_db("SELECT * FROM img WHERE slug=?", (filename,), one=True) is None:
        return filename
    version = 2
    while True:
        f_name, f_ext = filename.rsplit('.', 1)
        new_filename = "{}{}.{}".format(f_name, version, f_ext)
        if query_db("SELECT * FROM img WHERE slug=?", (new_filename,), one=True) is None:
            break
        version += 1
    return new_filename

@app.route('/photophoto/upload/', methods=['GET', 'POST'])
@app.route('/photophoto/upload/<int:img>/delete/', defaults={'delete': True}, methods=['GET', 'POST'])
@app.route('/photophoto/upload/<int:img>/', defaults={'delete': False}, methods=['GET', 'POST'])
def upload(img=None, delete=False):
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if delete:
        old_img = query_db("SELECT * FROM img WHERE id=?", (img,), one=True)
        if old_img:
            if old_img["slug"]:
                initials = "as" if "alex" in session.get("user") else "jb"
                user_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], initials)
                old_img_path = os.path.join(user_upload_dir, old_img["slug"])
                if os.path.isfile(old_img_path):
                    os.remove(old_img_path)
            query_db('DELETE FROM img WHERE id=?', (img,), update=True)
            flash('so sad, you deleted an image')
        return redirect(url_for("home"))
    if request.method == 'POST':
        file = request.files.get('file')
        id = int(request.form.get('id', 0))
        day = int(request.form.get('day'))
        month = int(request.form.get('month'))
        title = request.form.get('title')
        
        initials = "as" if "alex" in session.get("user") else "jb"
        user_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], initials)
        
        if id:
            query_db("UPDATE img SET title=?, day=?, month=? WHERE id=?", (title, day, month, id), update=True)
            return jsonify(id=id, day=day, month=month, title=title)
        elif file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename = unique_filename(filename)
            file.save(os.path.join(user_upload_dir, filename))
            
            old_img = query_db("SELECT slug FROM img WHERE day=? AND month=? AND user=?", (day,month,session.get("user")), one=True)
            if old_img:
                if old_img["slug"]:
                    old_img_path = os.path.join(user_upload_dir, old_img["slug"])
                    if os.path.isfile(old_img_path):
                        os.remove(old_img_path)
                query_db("DELETE FROM img WHERE day=? AND month=? AND user=?", (day,month,session.get("user")), update=True)
        
            img_id = insert_db("img", fields=('day', 'month', 'user', 'title', 'slug'), args=(day, month, session.get("user"), title, filename))
            return jsonify(id=img_id, day=day, month=month, title=title)
    first_day, days_in_month = monthrange(2015, dt.now().month)
    days_in_month = range(1, days_in_month+1)
    today = dt.now().day
    this_month = dt.now().month
    if img:
        img = query_db("SELECT * FROM img WHERE id=?", (img,), one=True)
        first_day, days_in_month = monthrange(2015, img["month"])
        days_in_month = range(1, days_in_month+1)
    return render_template('upload.html', img=img, days_in_month=days_in_month, today=today, this_month=this_month)

'''

    Run the file!
    
'''
if __name__ == '__main__':
  app.run()