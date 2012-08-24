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
from flask import Flask, render_template, request, flash, redirect, session, abort

app = Flask('z20p')
app.secret_key = b"superuniqueandsecret"

# TODO split this into file
from wtforms import Form, BooleanField, TextField, TextAreaField, PasswordField, RadioField, SelectField, SelectMultipleField, validators, ValidationError, widgets
from flask.ext.wtf import FileField, file_allowed, file_required
from flask.ext.wtf.html5 import IntegerField
from flask.ext.uploads import UploadSet, IMAGES

uploads = UploadSet("uploads", IMAGES)

class MultiCheckboxField(SelectMultipleField):
    """
    A multiple-select, except displays a list of checkboxes.

    Iterating the field will produce subfields, allowing custom rendering of
    the enclosed checkbox fields.
    
    Shamelessly stolen from WTForms FAQ.
    """
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class ArticleForm(Form):
    title = TextField('Titulek', [validators.required()])
    text = TextAreaField('Text', [validators.required()])
    rating = IntegerField('Hodnocení', [validators.optional()])
    labels = MultiCheckboxField('Štítky', coerce=int)
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
                return abort(403) #"soft 403 (nedostatecna prava: {0} < {1})".format(session['user'].rights, minrights)
            return abort(403) # "soft 403 (prihlas se)" # TODO use something
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

@app.route("/article/<int:article_id>")
def article(article_id):
    article = db.session.query(db.Article).filter_by(id=article_id).scalar()
    if not article: abort(404)
    return render_template("article.html", article=article)

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
@minrights(1)
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

def upload_image(**kvargs):
    media = None
    if 'image' in request.files and request.files['image'].filename != "":
        image = request.files['image']
        filename = secure_filename(image.filename)
        image.save(os.path.join("static/uploads/", filename))
        media = db.Media(type="image", url="/static/uploads/"+filename, **kvargs)
        db.session.add(media)
        print(media)
        flash("Obrázek nahrán.")
    return media

@app.route("/new_article", methods=['GET', 'POST'])
@minrights(2)
def new_article():
    form = ArticleForm(request.form)
    labels = db.session.query(db.Label) \
        .order_by(db.Label.category.asc()).all()
    form.labels.choices = [(l.id, l.name+" ("+l.category+")") for l in labels]
    if request.method == 'POST' and form.validate():
        media = upload_image(title=form.image_title.data, author_id=session['user'].id)
    
        article = db.Article(title=form.title.data, text=form.text.data,
            rating=form.rating.data, media=media, author_id=session['user'].id, 
            timestamp=datetime.utcnow())
        article.labels = []
        for label_id in form.labels.data:
            article.labels.append(db.session.query(db.Label).filter_by(id=label_id).scalar())
        db.session.add(article)
        db.session.commit()
        flash('Článek přidán')
        return redirect("/")
    return render_template("new_article.html", form=form)
    
@app.route("/article/<int:edit_id>/edit", methods=['GET', 'POST'])
@minrights(2)
def edit_article(edit_id):
    article = db.session.query(db.Article).filter_by(id=edit_id).scalar()
    form = ArticleForm(request.form, article)
    labels = db.session.query(db.Label) \
        .order_by(db.Label.category.asc()).all()
    form.labels.choices = [(l.id, l.name+" ("+l.category+")") for l in labels]
    if request.method == 'POST' and form.validate():
        media = upload_image(title=form.image_title.data, author_id=session['user'].id)
    
        article.title = form.title.data
        article.text = form.text.data
        article.rating = form.rating.data
        article.image_title = form.image_title.data
        article.labels = []
        for label_id in form.labels.data:
            article.labels.append(db.session.query(db.Label).filter_by(id=label_id).scalar())
        if media != None:
            article.media = media
        db.session.commit()
        flash('Článek upraven')
        return redirect("/")
    if request.method == 'GET' and form.labels.data == None:
        form.labels.data = [l.id for l in article.labels]
    return render_template("edit_article.html", form=form, article=article)
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
