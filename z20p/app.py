# encoding: utf-8
from __future__ import absolute_import, unicode_literals, print_function

#from z20p import db
import db

from datetime import datetime
from functools import wraps # We need this to make Flask understand decorated routes.
import hashlib
import os

def pwhash(string):
    return hashlib.sha224(string+"***REMOVED***").hexdigest()
    
from werkzeug import secure_filename
from flask import Flask, render_template, request, flash, redirect, session

app = Flask('z20p')
app.secret_key = b"superuniqueandsecret"

# TODO split this into file
from wtforms import Form, BooleanField, TextField, TextAreaField, PasswordField, RadioField, SelectField, validators, ValidationError
from flask.ext.wtf import FileField, file_allowed, file_required
from flask.ext.wtf.html5 import IntegerField
from flask.ext.uploads import UploadSet, IMAGES

uploads = UploadSet("uploads", IMAGES)

class ArticleForm(Form):
    title = TextField('Titulek', [validators.required()])
    text = TextAreaField('Text', [validators.required()])
    rating = IntegerField('Hodnocení', [validators.optional()])
    image = FileField('Obrázek', [file_allowed(uploads, "Jen obrázky")])
    image_title = TextField('Titulek obrázku', [validators.optional()])
    
    # TODO make this work??
    #def validate_image(self, field):
    #    if "." in field.data and field.data.split('.')[-1] in ('png', 'jpg', 'jpeg', 'gif'):
    #        return
    #    else:
    #        raise ValidationError("Nepovolený typ souboru.")

# Callable decorator
def minrights(minrights):
    def decorator(function):
        @wraps(function)
        def f(*args, **kvargs):     
            if 'user' in session:
                if session['user'].rights >= minrights:
                    return function(*args, **kvargs)
                return "soft 403 (nedostatecna prava: {0} < {1})".format(session['user'].rights, minrights)
            return "soft 403 (prihlas se)" # TODO use something
        return f
    return decorator

@app.teardown_request
def shutdown_session(exception=None):
    db.session.remove()

@app.template_filter('datetime')
def datetime_format(value, format='%d. %m. %Y  %H:%M'):
    return value.strftime(format)

@app.route("/")
def root():
    articles = db.session.query(db.Article) \
        .order_by(db.Article.timestamp.desc()).limit(4).all()
    return render_template("main.html", articles=articles)

@app.route("/login", methods=['GET', 'POST'])
def login():
    class LoginForm(Form):
        name = TextField('Jméno', [validators.required()])
        password = PasswordField('Heslo', [validators.required()])
    
    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        user = db.session.query(db.User).filter_by(name=form.name.data).filter_by(password=pwhash(form.password.data)).scalar()
        if user:
            session['user'] = user
            flash("Jste přihlášeni.")
            return redirect("/")
        else:
            flash("Nesprávné uživatelské jméno nebo heslo.")
    
    return render_template("login.html", form=form)

@app.route("/logout")
@minrights(2)
def logout():
    session.pop("user")
    flash("Byli jste odhlášeni.")
    return redirect("/")

@app.route("/register", methods=['GET', 'POST'])
def register():
    class RegistrationForm(Form):
        name = TextField('Jméno', [validators.required()])
        password = PasswordField('Heslo', [
            validators.Required(),
            validators.EqualTo('confirm', message='Hesla se musí schodovat')
        ])
        confirm = PasswordField('Heslo znovu')
        gender = SelectField('Pohlaví', choices=[("m", "ten"), ("f", "ta"), ("-", "to")])
    
    form = RegistrationForm(request.form)
    if request.method == 'POST' and form.validate():
        # TODO confirm that username is unique
        user = db.User(name=form.name.data, gender=form.gender.data, 
            rights=1, password=pwhash(form.password.data))
        db.session.add(user)
        db.session.commit()
        session['user'] = db.session.query(db.User).filter_by(name=form.name.data).filter_by(password=pwhash(form.password.data)).scalar()
        flash("Jste zaregistrováni.")
        return redirect("/")
    
    return render_template("register.html", form=form)

@app.route("/labels", methods=['GET', 'POST'])
@app.route("/labels/<int:edit_id>/edit", methods=['GET', 'POST'])
@minrights(2)
def labels(edit_id=None):
    class LabelForm(Form):
        name = TextField('Jméno', [validators.required()])
        category = SelectField('Kategorie', choices=[("platform", "Platforma"), ("genre", "Žánr"), ("other", "Jiné")])
    
    if edit_id == None:
        form = LabelForm(request.form)
        if request.method == 'POST' and form.validate():
            label = db.Label(name=form.name.data, category=form.category.data,
                user_id=session['user'].id)
            db.session.add(label)
            db.session.commit()
            flash('Štítek přidán')
    
    if edit_id:
        editlabel = db.session.query(db.Label).filter_by(id=edit_id).scalar()
        form = LabelForm(request.form, editlabel)
        if request.method == 'POST' and form.validate():
            editlabel.name = form.name.data
            editlabel.category = form.category.data
            db.session.commit()
            # Done!
            flash("Štítek upraven.")
            return redirect("/labels")
    
    labels = db.session.query(db.Label) \
        .order_by(db.Label.category.asc()).all()
    return render_template("labels.html", form=form, labels=labels, edit_id=edit_id)

@app.route("/new_article", methods=['GET', 'POST'])
@minrights(2)
def new_article():
    form = ArticleForm(request.form)
    if request.method == 'POST' and form.validate():
        media = None
        if 'image' in request.files:
            image = request.files['image']
            filename = secure_filename(image.filename)
            image.save(os.path.join("static/uploads/", filename))
            media = db.Media(type="image", url="/static/uploads/"+filename, title=form.image_title.data, author_id=session['user'].id)
            db.session.add(media)
            print(media)
            flash("Obrázek nahrán.")
    
        article = db.Article(title=form.title.data, text=form.text.data,
            rating=form.rating.data, media=media, author_id=session['user'].id, 
            timestamp=datetime.utcnow())
        db.session.add(article)
        db.session.commit()
        flash('Článek přidán')
        return redirect("/")
    return render_template("new_article.html", form=form)
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
