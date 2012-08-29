# encoding: utf-8
from __future__ import absolute_import, unicode_literals, print_function

#from z20p import db
import db
from sqlalchemy import or_, asc, desc

from datetime import datetime
import time
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
    f2p = BooleanField('Hratelné zdarma')
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

def get_guest(name=None):
    if name:
        guest = db.session.query(db.User).filter(db.User.name == name).filter(db.User.password == None).scalar()
        if not guest:
            guest = db.User(name=name, timestamp=datetime.now(), laststamp=datetime.now(), ip=request.remote_addr)
            db.session.add(guest)
        guest.laststamp = datetime.now()
        db.session.commit()
    else:
        guest = db.session.query(db.User).filter(db.User.ip == request.remote_addr).filter(db.User.password == None).scalar()
        if not guest:
            guest = db.User(name=None, timestamp=datetime.now(), laststamp=datetime.now(), ip=request.remote_addr)
            db.session.add(guest)
        guest.laststamp = datetime.now()
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
    if request.script_root != "/static": # Yeah no.
        if 'user_id' in session:
            user = db.session.query(db.User).filter_by(id=session['user_id']).scalar()
            if not user: # We could've reset the database.  Let's not have to delete cookies.
                logout()
                session['user'] = get_guest()
                return
            user.laststamp = datetime.now()
            session['user'] = user
            db.session.commit()
        else:
            # Let's use a temporary dummy user.
            # session['user'] = db.session.query(db.User).filter_by(id=1).one() # This ought to be the guest...
            session['user'] = get_guest()

@app.teardown_request
def shutdown_session(exception=None):
    db.session.remove()

@app.template_filter('datetime')
def datetime_format(value, format='%d. %m. %Y  %H:%M'): # TODO add 2 hours
    if not value: return "-"
    return value.strftime(format)

@app.route("/")
def main():
    articles = db.session.query(db.Article) \
        .order_by(db.Article.timestamp.desc()).limit(4).all()
    return render_template("main.html", articles=articles)

@app.route("/search")
def search():
    # Oh boy.
    # TODO this could use some ACTUAL FULLTEXT or whatever that is!  Match pokemon to pokémon for one!
    class SimplifiedSearchForm(Form):
        text = TextField("Text", [validators.required()])
        within_labels = BooleanField("Včetně štítků", default=True)
        sort = SelectField("Řazení", choices=[("timestamp", "Datum publikace"), ("rating", "Hodnocení")], default="pubdate")
        order = SelectField("Typ řazení", choices=[("desc", "Sestupně"), ("asc", "Vzestupně")], default="desc")
        submit = SubmitField("Hledat")
    
    class SearchForm(SimplifiedSearchForm):
        platform_label = SelectField('Platforma', choices=[], coerce=int)
        genre_label = SelectField('Žánr', choices=[], coerce=int)
        other_label = SelectField('Štítek', choices=[], coerce=int)
        #label_operator = SelectField("Operátor", choices=[("", " "), ("and", "a"), ("or", "nebo"), ("nor", "ani")])
        #authors = MultiCheckboxField('Autoři', choices=[], coerce=int)
        #author_operator = SelectField("Operátor", choices=[("", " "), ("and", "a"), ("or", "nebo"), ("nor", "ani")])
    if False:
        labels = db.session.query(db.Label) \
            .order_by(db.Label.name.asc()).all()
        for label in labels:
            if label.category == 'platform': f = form.platform_label
            if label.category == 'genre': f = form.genre_label
            if label.category == 'other': f = form.other_label
            f.choices.append((label.id, label.name))
        
        #users = db.session.query(db.User).filter(db.User.rights >= 2) \
        #    .order_by(db.User.name.asc()).all()
        #form.authors.choices = [(u.id, u.name) for u in users]
    
    
    form = SimplifiedSearchForm(request.args)
    try: # This needs more magic...
        page = int(request.args.get("page"))
    except TypeError:
        page = 1
    except ValueError:
        abort(400)
    
    searched = False
    matched_labels = []
    matched_articles = []
    count = None
    if "submit" in request.args and form.validate():
        searched = True
        or_conditions = []
        if form.within_labels.data:
            matched_labels = db.session.query(db.Label).filter(db.Label.name.like('%'+form.text.data+'%')).all()
            if matched_labels:
                or_conditions += [db.Article.labels.contains(l) for l in matched_labels]
        or_conditions += [db.Article.title.like('%'+form.text.data+'%'),
                         db.Article.text.like('%'+form.text.data+'%')]
        
        order_by = {"timestamp": db.Article.timestamp, "rating": db.Rating.rating}[form.sort.data]
        order = {'asc': asc, 'desc': desc}[form.order.data]
        
        articles = db.session.query(db.Article).join(db.Article.rating).filter(or_(*or_conditions)).order_by(order(order_by)) 
        matched_articles = articles.all() # Nope, this won't work without the all.  It'll just regard everything which matched, including dupes (which get nuked when /read/ but that's about it).  :(
        count = len(matched_articles)
        matched_articles = matched_articles[(page-1)*5:(page)*5]
        
    url_args = request.args.copy()
    if page in url_args: del url_args["page"]
    return render_template("search.html", form=form, searched=searched, matched_articles=matched_articles, matched_labels=matched_labels, count=count, page=page, url_args=url_args)

# TODO all these POSTs should go elsewhere with a redirect.  Better for refreshing.
@app.route("/articles/<int:article_id>", methods=['GET', 'POST'])
def article(article_id):
    article = db.session.query(db.Article).filter_by(id=article_id).scalar()
    if not article: abort(404)
    class UploadForm(Form):
        image = FileField('Obrázek', [file_allowed(uploads, "Jen obrázky")])
        title = TextField('Titulek obrázku', [validators.required()])
        submit = SubmitField('Přidat obrázek')
    
    upload_form = UploadForm(request.form)
    if request.method == 'POST' and request.form['submit'] == upload_form.submit.label.text and upload_form.validate():
        media = upload_image(title=upload_form.title.data, author=session['user'],
            article=article)
        db.session.commit() # Gotta commit here 'cause we're reading media ids later
    
    class VideoForm(Form):
        url = TextField('URL videa', [validators.required()])
        video_title = TextField('Titulek videa', [validators.required()])
        submit = SubmitField('Přidat video')
        
        def validate_url(self, url):
            if url.data.startswith("http") and ("youtube" in url.data or "youtu.be/" in url.data):
                pass
            else:
                raise ValidationError("Musí být Youtube URL.")
    
    video_form = VideoForm(request.form)
    
    if request.method == 'POST' and request.form['submit'] == video_form.submit.label.text and video_form.validate():
        media = db.Media(type="video", url=video_form.url.data, timestamp=datetime.now(), article=article, author=session['user'], title=video_form.video_title.data)
        db.session.add(media)
        flash("Video přidáno.")
        db.session.commit()
    
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
                msg = "Hodnocení upraveno."
            else:
                db.session.delete(rating)
                msg = "Hodnocení odebráno."
        else:
            rating = db.Rating(rating=rating_form.rating.data, user_id=session['user'].id, article=article)
            if article.author == session['user']: # If the author removes then adds an rating using this form
                article.rating = rating
            db.session.add(rating)
            msg = "Ohodnoceno."
        flash(msg)
    
    if session['user'].guest:
        name_validators = [validators.required()]
    else:
        name_validators = [validators.optional()]
    class ReactionForm(Form):
        name = TextField('Jméno', name_validators) # Only for guests
        text = TextAreaField('Text', [validators.required()])
        rating = SelectField('Hodnocení', choices=[(0, '-')]+[(i+1, str(i+1)) for i in range(0,10)], coerce=int)
        image = SelectField('Obrázek', choices=[(-1, '-')], coerce=int, default=-1)
        submit = SubmitField('Přidat reakci')
    
    reaction_form = ReactionForm(request.form, rating=rating.rating if (rating and article.author != session['user']) else 0)
    for media in article.all_media:
        if media.author == session['user'] and not media.assigned_article and not media.assigned_reaction:
            reaction_form.image.choices.append((media.id, media.title))
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
        media = reaction_form.image.data if reaction_form.image.data != -1 else None
        reaction = db.Reaction(text=reaction_form.text.data, rating=rating, article=article, timestamp=datetime.now(), author=user, media_id=media)
        db.session.add(reaction)
        flash("Reakce přidána.")
    
    article.views += 1
    db.session.commit()
    # TODO make these @properties of the article?
    images = db.session.query(db.Media).filter(db.Media.article==article).filter(db.Media.type=="image").all()
    videos = db.session.query(db.Media).filter(db.Media.article==article).filter(db.Media.type=="video").all()
    return render_template("article.html", article=article, upload_form=upload_form, reaction_form=reaction_form, rating_form=rating_form, video_form=video_form, images=images, videos=videos)

# TODO /reactions/id redirect to article#id

@app.route("/reactions/<int:reaction_id>/edit", methods=['GET', 'POST'])
@minrights(1)
def edit_reaction(reaction_id):
    reaction = db.session.query(db.Reaction).filter_by(id=reaction_id).scalar()
    if not reaction: abort(404)
    if not session['user'].admin and (session['user'] != reaction.author): abort(403)
    class EditReactionForm(Form):
        text = TextAreaField('Text', [validators.required()])
        rating = SelectField('Hodnocení', choices=[(0, '-')]+[(i+1, str(i+1)) for i in range(0,10)], coerce=int)
        image = SelectField('Obrázek', choices=[(-1, '-')], coerce=int)
        submit = SubmitField('Upravit reakci')
    # This could be constructed better...
    rating = db.session.query(db.Rating).filter(db.Rating.assigned_reaction.contains(reaction)) \
         .filter(db.Rating.user == reaction.author).scalar()
    form = EditReactionForm(request.form, reaction)
    if form.rating.data == None: form.rating.data = rating.rating if (rating and rating.rating) else 0
    for media in reaction.article.all_media:
        if media.author == session['user'] and not media.assigned_article and not media.assigned_reaction:
            form.image.choices.append((media.id, media.title))
        elif media == reaction.media:
            form.image.choices.append((media.id, media.title))
            if form.image.data == None: form.image.data = media.id
    
    if request.method == 'POST' and form.validate():
        reaction.text = form.text.data
        if form.image.data != -1:
            reaction.media_id = form.image.data
        else:
            reaction.media = None
        if form.rating.data:
            if rating:
                rating.rating = form.rating.data
            else:
                rating = db.Rating(rating=form.rating.data, user=reaction.author, article=reaction.article)
            reaction.rating = rating
        else:
            reaction.rating = None
        db.session.commit()
        flash("Reakce upravena.")
        return redirect(reaction.article.url+"#reaction-"+str(reaction.id))
    
    return render_template("edit_reaction.html", reaction=reaction, form=form)

# TODO /media/id redirect to image itself
@app.route("/media/<int:media_id>/edit", methods=['GET', 'POST'])
def edit_media(media_id):
    media = db.session.query(db.Media).filter_by(id=media_id).scalar()
    if not media: abort(404)
    if not session['user'].admin and (session['user'] != media.author): abort(403)
    # TODO image rank
    class EditMediaForm(Form):
        title = TextField('Titulek', [validators.required()])
        submit = SubmitField('Upravit')
    
    class AdminEditMediaForm(EditMediaForm):
        url = TextField('URL (u obrázků jen pokud víš co děláš)', [validators.required()])
    
    if not session['user'].admin:
        form = EditMediaForm(request.form, media)
    else:
        form = AdminEditMediaForm(request.form, media)
    
    if request.method == 'POST' and form.validate():
        if session['user'].admin:
            media.url = form.url.data
        media.title = form.title.data
        db.session.commit()
        if media.type == "image":
            flash("Obrázek upraven.")
        else:
            flash("Video upraveno.")
        return redirect(media.article.url+"#media-"+str(media.id))
    
    return render_template("edit_media.html", media=media, form=form)

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
            db.session.commit()
            flash("Jste přihlášeni.")
            return redirect("/")
        else: # This ought to be removed in a "short" while.
            user = db.session.query(db.User).filter_by(name=form.name.data).filter_by(password="FIXME").scalar()
            if user:
                session['user_id'] = user.id
                session['user'] = user
                session['user'].ip = request.remote_addr
                session.commit()
                flash("Byli jste přihlášeni, ale z důvodu masivních změn v systému nemáte heslo.  Prosím, nastavte si nové heslo pokud možno hned.")
                return redirect("/users/"+str(user.id)+"/edit")
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
            rights=1, password=pwhash(form.password.data), timestamp=datetime.now(),
            laststamp=datetime.now())
        db.session.add(user)
        db.session.commit()
        session['user'] = db.session.query(db.User).filter_by(name=form.name.data).filter_by(password=pwhash(form.password.data)).scalar()
        flash("Jste zaregistrováni.")
        return redirect("/login")
    
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
    # TODO check for duplicate filenames
    media = None
    if 'image' in request.files and request.files['image'].filename != "":
        image = request.files['image']
        filename = secure_filename(image.filename)
        image.save(os.path.join("static/uploads/", filename))
        media = db.Media(type="image", url="/static/uploads/"+filename, timestamp=datetime.now(), **kvargs)
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
        article = db.Article(title=form.title.data, text=form.text.data,
            author_id=session['user'].id, 
            timestamp=datetime.now(), published=True)
        media = upload_image(title=form.image_title.data, author_id=session['user'].id,
            article=article)
        article.media = media
        article.f2p = form.f2p.data
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
    
@app.route("/articles/<int:edit_id>/edit", methods=['GET', 'POST'])
@minrights(1)
def edit_article(edit_id):
    article = db.session.query(db.Article).filter_by(id=edit_id).scalar()
    if not article: abort(404)
    if not session['user'].admin and (session['user'] != article.author): abort(403)
    class EditArticleForm(ArticleForm):
        image = SelectField('Obrázek', choices=[(-1, '-')], coerce=int)
    form = EditArticleForm(request.form, article)
    for media in article.all_media:
        if media.author == session['user'] and not media.assigned_article and not media.assigned_reaction:
            form.image.choices.append((media.id, media.title))
        elif media == article.media:
            print(article.media, form.image.data)
            form.image.choices.append((media.id, media.title))
            if form.image.data == None: form.image.data = media.id
    labels = db.session.query(db.Label) \
        .order_by(db.Label.category.desc(), db.Label.name.asc()).all()
    form.labels.choices = [(l.id, l.category[0]+": "+l.name) for l in labels]
    if request.method == 'POST' and form.validate():
        print (form.image.data)
        if form.image.data != -1:
            article.media_id = form.image.data
        else:
            article.media = None
        article.f2p = form.f2p.data
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
        db.session.commit()
        flash('Článek upraven')
        return redirect(article.url)
    if request.method == 'GET' and form.labels.data == None: # welp
        form.labels.data = [l.id for l in article.labels]
        if article.rating:
            form.rating.data = article.rating.rating
    
    return render_template("edit_article.html", form=form, article=article)
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
