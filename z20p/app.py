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
from wtforms import Form, BooleanField, TextField, TextAreaField, PasswordField, RadioField, SelectField, SelectMultipleField, BooleanField, SubmitField, validators, ValidationError, widgets
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
    rating = SelectField('Hodnocení', choices=[(0, '-')]+[(i+1, str(i+1)) for i in range(0,10)], coerce=int)
    labels = MultiCheckboxField('Štítky', coerce=int)
    image = FileField('Obrázek', [file_allowed(uploads, "Jen obrázky")])
    image_title = TextField('Titulek obrázku', [validators.optional()])
    published = BooleanField("Publikovat", default=True)
    
    # TODO make this work??
    #def validate_image(self, field):
    #    if "." in field.data and field.data.split('.')[-1] in ('png', 'jpg', 'jpeg', 'gif'):
    #        return
    #    else:
    #        raise ValidationError("Nepovolený typ souboru.")

def get_guest(name):
    guest = db.session.query(db.User).filter(db.User.name == name).filter(db.User.password == None).scalar()
    if not guest:
        guest = db.User(name=name, timestamp=datetime.utcnow(), laststamp=datetime.utcnow()) # TODO ip?
        db.session.add(guest)
        db.session.commit()
    return guest

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

@app.before_request
def before_request():
    if 'user_id' in session:
        user = db.session.query(db.User).filter_by(id=session['user_id']).scalar()
        if not user: # We could've reset the database.  Let's not have to delete cookies.
            logout()
            return
        user.laststamp = datetime.utcnow()
        session['user'] = user
        db.session.commit()
    else:
        # Let's use a temporary dummy user.
        session['user'] = db.User(name="Anonym", rights=0)

@app.teardown_request
def shutdown_session(exception=None):
    db.session.remove()

@app.template_filter('datetime')
def datetime_format(value, format='%d. %m. %Y  %H:%M'): # TODO add 2 hours
    return value.strftime(format)

@app.route("/")
def root():
    articles = db.session.query(db.Article) \
        .order_by(db.Article.timestamp.desc()).limit(4).all()
    return render_template("main.html", articles=articles)

@app.route("/article/<int:article_id>", methods=['GET', 'POST'])
def article(article_id):
    article = db.session.query(db.Article).filter_by(id=article_id).scalar()
    if not article: abort(404)
    class RatingForm(Form):
        rating = SelectField('Hodnocení', choices=[(0, '-')]+[(i+1, str(i+1)) for i in range(0,10)], coerce=int)
        submit = SubmitField('Přidat hodnocení')
    
    rating = db.session.query(db.Rating).filter(db.Rating.article == article) \
        .filter(db.Rating.user == session['user']).scalar()
    rating_form = RatingForm(request.form, rating=rating.rating if rating else 0)
    
    if request.method == 'POST' and request.form['submit'] == rating_form.submit.label.text and rating_form.validate(): # XXX
        if rating:
            if rating_form.rating.data:
                rating.rating = rating_form.rating.data
            else:
                db.session.delete(rating)
        else:
            rating = db.Rating(rating=rating_form.rating.data, user_id=session['user'].id, article=article)
            if article.author == session['user']: # If the author removes then adds an rating using this form
                article.rating = rating
            db.session.add(rating)
    
    if session['user'].guest:
        name_validators = [validators.required()]
    else:
        name_validators = [validators.optional()]
    class ReactionForm(Form):
        name = TextField('Jméno', name_validators) # Only for guests
        text = TextAreaField('Text', [validators.required()])
        rating = SelectField('Hodnocení', choices=[(0, '-')]+[(i+1, str(i+1)) for i in range(0,10)], coerce=int)
        submit = SubmitField('Přidat reakci')
    
    reaction_form = ReactionForm(request.form, rating=rating.rating if (rating and article.author != session['user']) else 0)
    if request.method == 'POST' and request.form['submit'] == reaction_form.submit.label.text and reaction_form.validate():
        if reaction_form.name.data: # This technically allows logged-in users to post as guests if they hack the input in.
            user = get_guest(reaction_form.name.data)
        else:
            user = session['user']
        rating = None
        if user != article.author:
            if rating and rating_form.rating.data:
                rating.raing = reaction_form.rating.data
            elif rating_form.rating.data:
                rating = db.Rating(rating=reaction_form.rating.data, user=user, article=article)
                db.session.add(rating)
            
        reaction = db.Reaction(text=reaction_form.text.data, rating=rating, article=article, timestamp=datetime.utcnow(), author=user)
        db.session.add(reaction)
    
    article.views += 1
    db.session.commit()
    return render_template("article.html", article=article, reaction_form=reaction_form, rating_form=rating_form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    class LoginForm(Form):
        name = TextField('Jméno', [validators.required()])
        password = PasswordField('Heslo', [validators.required()])
    
    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        user = db.session.query(db.User).filter_by(name=form.name.data).filter_by(password=pwhash(form.password.data)).scalar()
        if user:
            session['user_id'] = user.id
            session['user'] = user
            session['user'].ip = request.remote_addr
            flash("Jste přihlášeni.")
            return redirect("/")
        else:
            flash("Nesprávné uživatelské jméno nebo heslo.")
    
    return render_template("login.html", form=form)

@app.route("/logout")
def logout():
    if 'user' in session:
        session.pop("user")
    if 'user_id' in session:
        session.pop("user_id")
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
            rights=1, password=pwhash(form.password.data), timestamp=datetime.utcnow(),
            laststamp=datetime.utcnow())
        db.session.add(user)
        db.session.commit()
        session['user'] = db.session.query(db.User).filter_by(name=form.name.data).filter_by(password=pwhash(form.password.data)).scalar()
        flash("Jste zaregistrováni.")
        return redirect("/")
    
    return render_template("register.html", form=form)

@app.route("/users", methods=['GET'])
def users():
    users = db.session.query(db.User) \
        .order_by(db.User.name.asc()).filter(db.User.password != None).all()
    anons = db.session.query(db.User) \
        .order_by(db.User.name.asc()).filter(db.User.password == None).all()
    return render_template("users.html", users=users, anons=anons)

@app.route("/users/<int:user_id>", methods=['GET'])
def user(user_id):
    user = db.session.query(db.User).filter_by(id=user_id).scalar()
    if not user: abort(404)
    return render_template('user.html', user=user)

@app.route("/users/<int:user_id>/edit", methods=['GET', 'POST'])
@minrights(1)
def edit_user(user_id):
    user = db.session.query(db.User).filter_by(id=user_id).scalar()
    if not user: abort(404)
    class EditUserForm(Form):
        email = TextField('Email', [validators.optional()])
        password = PasswordField('Heslo (jen pokud nové)', [ validators.optional(),
            validators.EqualTo('confirm', message='Hesla se musí schodovat')
        ])
        confirm = PasswordField('Heslo znovu', [validators.optional()])
        gender = SelectField('Pohlaví', choices=[("m", "ten"), ("f", "ta"), ("-", "to")])
        minipic = TextField('URL ikonky', [validators.optional()])
        profile = TextAreaField('Profil', [validators.optional()])
    
    class AdminEditUserForm(EditUserForm):
        name = TextField('Jméno')
        rights = IntegerField('Práva')
    
    admin = False
    if session['user'].rights >= 3:
        form = AdminEditUserForm(request.form, user)
        admin = True
    elif user == session['user']:
        form = EditUserForm(request.form, user)
    else:
        abort(403) # No editing other users!
    
    if request.method == 'POST' and form.validate():
        if admin:
            user.name = form.name.data
            user.rights = form.rights.data
        user.email = form.email.data
        if form.password.data:
            user.password = pwhash(form.password.data)
        user.gender = form.gender.data
        user.minipic = form.minipic.data
        user.profile = form.profile.data
        db.session.commit()
        flash("Uživatel upraven!")
        return redirect("/users/"+str(user.id))
    
    return render_template('edit_user.html', user=user, form=form, admin=admin)

@app.route("/labels", methods=['GET', 'POST'])
@app.route("/labels/<int:edit_id>/edit", methods=['GET', 'POST'])
@minrights(2)
def labels(edit_id=None):
    class LabelForm(Form):
        name = TextField('Jméno', [validators.required()])
        category = SelectField('Kategorie', choices=[("platform", "Platforma"), ("genre", "Žánr"), ("column", "Sloupek"), ("other", "Jiné")])
    
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
        .order_by(db.Label.category.desc(), db.Label.name.asc()).all()
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
        .order_by(db.Label.category.desc(), db.Label.name.asc()).all()
    form.labels.choices = [(l.id, l.category[0]+": "+l.name) for l in labels]
    if request.method == 'POST' and form.validate():
        media = upload_image(title=form.image_title.data, author_id=session['user'].id)
    
        article = db.Article(title=form.title.data, text=form.text.data,
            media=media, author_id=session['user'].id, 
            timestamp=datetime.utcnow(), published=True)
        if form.rating.data:
            article.rating = db.Rating(rating=form.rating.data, user_id=session['user'].id, article=article)
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
        .order_by(db.Label.category.desc(), db.Label.name.asc()).all()
    form.labels.choices = [(l.id, l.category[0]+": "+l.name) for l in labels]
    if request.method == 'POST' and form.validate():
        media = upload_image(title=form.image_title.data, author_id=session['user'].id)
    
        article.title = form.title.data
        article.text = form.text.data
        if article.rating:
            if not form.rating.data:
                db.session.delete(article.rating)
                article.rating = None
            else:
                article.rating.rating = form.rating.data
        else:
            article.rating = db.Rating(rating=form.rating.data, user_id=session['user'].id, article=article)
        article.published = form.published.data
        article.labels = []
        for label_id in form.labels.data:
            article.labels.append(db.session.query(db.Label).filter_by(id=label_id).scalar())
        if media != None:
            article.media = media
        db.session.commit()
        flash('Článek upraven')
        return redirect("/article/{0}".format(article.id))
    if request.method == 'GET' and form.labels.data == None: # welp
        form.labels.data = [l.id for l in article.labels]
        if article.rating:
            form.rating.data = article.rating.rating
        print(form.rating.data)
    
    return render_template("edit_article.html", form=form, article=article)
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
