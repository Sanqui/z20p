# encoding: utf-8
from __future__ import absolute_import, unicode_literals, print_function

#from z20p import db
import db
from sqlalchemy import or_, and_, asc, desc

from datetime import datetime
import time
from functools import wraps # We need this to make Flask understand decorated routes.
import hashlib
import os
import random

def pwhash(string):
    return hashlib.sha224(string+"***REMOVED***").hexdigest()
    
from werkzeug import secure_filename
from flask import Flask, render_template, request, flash, redirect, session, abort, url_for, make_response, g

app = Flask('z20p')
app.secret_key = b"superuniqueandsecret"

# TODO split this into file
from wtforms import Form, BooleanField, TextField, TextAreaField, PasswordField, RadioField, SelectField, SelectMultipleField, BooleanField, HiddenField, SubmitField, validators, ValidationError, widgets
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
        guest.last_url = request.path
        db.session.commit()
    else:
        guest = db.session.query(db.User).filter(db.User.ip == request.remote_addr).filter(db.User.password == None).filter(db.User.name == None).scalar()
        if not guest:
            guest = db.User(name=None, timestamp=datetime.now(), laststamp=datetime.now(), ip=request.remote_addr)
            db.session.add(guest)
        guest.laststamp = datetime.now()
        guest.last_url = request.path
        db.session.commit()
    return guest

# Callable decorator
def minrights(minrights):
    def decorator(function):
        @wraps(function)
        def f(*args, **kvargs):     
            if 'user_id' in session:
                if g.user.rights >= minrights:
                    return function(*args, **kvargs)
                return abort(403) #"soft 403 (nedostatecna prava: {0} < {1})".format(g.user.rights, minrights)
            return abort(403) # "soft 403 (prihlas se)" # TODO use something
        return f
    return decorator

@app.before_request
def before_request():
    if not request.path.startswith("/static"): # Yeah no.
        if 'user_id' in session:
            user = db.session.query(db.User).get(session['user_id'])
            if not user: # We could've reset the database.  Let's not have to delete cookies.
                logout()
                g.user = get_guest()
                return
            session.permanent = True
            user.laststamp = datetime.now()
            user.last_url = request.path
            g.user = user
            db.session.commit()
        else:
            # Let's use a temporary dummy user.
            # g.user = db.session.query(db.User).filter_by(id=1).one() # This ought to be the guest...
            g.user = get_guest()
        # I'm not sure if I'm okay with this being here, but I don't want logic and cruft in templates.
        # This could also be done in a single query; I'm just too stupid with SQL.
        if not g.user.guest:
            latest = db.session.query(db.ShoutboxPost.id).order_by(db.ShoutboxPost.timestamp.desc()).first().id
            g.unread = latest - g.user.last_post_read_id
        # Templating stuff.
        g.left_buttons = db.session.query(db.Button).filter(db.Button.location=="left").order_by(db.Button.position).all()
        g.right_buttons = db.session.query(db.Button).filter(db.Button.location=="right").order_by(db.Button.position).all()
        g.button_ids = [button.id for button in g.left_buttons+g.right_buttons] # blargh
        g.kip = random.randint(0, 4) == 0
        if g.kip:
            g.kipleft = random.randint(0, 100)
            g.kiptop = random.randint(0, 100)
            g.kiptype = random.randint(1,2)
        #g.unread_posts = latest - g.user.last_post_read.id

@app.teardown_request
def shutdown_session(exception=None):
    db.session.remove()

@app.template_filter('datetime')
def datetime_format(value, format='%d. %m. %Y  %H:%M'): # TODO add 2 hours
    if not value: return "-"
    return value.strftime(format)

# Stonlen and edited: https://gist.github.com/3091909
def url_for_here(**changed_args):
    args = request.args.to_dict()#.copy() # We do not want to flattern.
    args.update(request.view_args)
    for arg, value in changed_args.iteritems():
        if arg in args: del args[arg]
        args[arg] = value
    #args.update(changed_args)
    return url_for(request.endpoint, **args)

app.jinja_env.globals['url_for_here'] = url_for_here
app.jinja_env.globals['round'] = round # useful

@app.route("/")
def main():
    articles = db.session.query(db.Article) \
        .order_by(db.Article.timestamp.desc()).limit(4).all()
    images = db.session.query(db.Media).filter(db.Media.type=="image") \
        .order_by(db.Media.timestamp.desc()).limit(8).all()
    return render_template("main.html", articles=articles, images=images)

def get_page():
    try: # This needs more magic...
        page = int(request.args.get("page"))
    except TypeError:
        page = 1
    except ValueError:
        abort(400)
    if page == 0: abort(400)
    return page

@app.route("/search")
def search():
    # Oh boy.
    class SearchForm(Form):
        sort = SelectField("Řazení", choices=[("timestamp", "data publikace"), ("rating", "hodnocení"), ("views", "počtu shlédnutí")], default="timestamp")
        order = SelectField("Typ řazení", choices=[("desc", "sestupně"), ("asc", "vzestupně")], default="desc")
        # No submit so it doesn't get struck in the URL
    
    # TODO this could use some ACTUAL FULLTEXT or whatever that is!  Match pokemon to pokémon for one!    
    class TextSearchForm(SearchForm):
        text = TextField("Text", [validators.required()])
        within_labels = BooleanField("Včetně štítků", default=True)
    
    class LabelSearchForm(SearchForm):
        platform_labels = MultiCheckboxField('Platforma', choices=[], coerce=int)
        genre_labels = MultiCheckboxField('Žánr', choices=[], coerce=int)
        other_labels = MultiCheckboxField('Štítek', choices=[], coerce=int)
        operator = SelectField("Operátor", choices=[("or", "nebo"), ("and", "a")], default="or")
        labels = HiddenField("labels", default="y")
    
    if 'labels' in request.args:
        stype = 'labels'
        form = LabelSearchForm(request.args)
        
        labels = db.session.query(db.Label) \
            .order_by(db.Label.name.asc()).all()
        for label in labels:
            if label.category == 'platform': f = form.platform_labels
            if label.category == 'genre': f = form.genre_labels
            if label.category == 'other': f = form.other_labels
            f.choices.append((label.id, label.name))
    elif "all" in request.args:
        stype = 'all'
        form = SearchForm(request.args)
    else:
        stype = 'text'
        form = TextSearchForm(request.args)
        
        #users = db.session.query(db.User).filter(db.User.rights >= 2) \
        #    .order_by(db.User.name.asc()).all()
        #form.authors.choices = [(u.id, u.name) for u in users]
    
    
    page = get_page()
    searched = False
    matched_labels = []
    matched_articles = []
    count = None
    if ("text" in request.args or "all" in request.args or "platform_labels" in request.args or "genre_labels" in request.args or "other_labels" in request.args) and form.validate(): # Yep.
        searched = True
        or_conditions = []
        and_conditions = []
        label_or = [] # see the note below
        if stype == 'text':
            if form.within_labels.data:
                matched_labels = db.session.query(db.Label).filter(db.Label.name.like('%'+form.text.data+'%')).all()
                if matched_labels:
                    or_conditions += [db.Article.labels.contains(l) for l in matched_labels]
            or_conditions += [db.Article.title.like('%'+form.text.data+'%'),
                             db.Article.text.like('%'+form.text.data+'%')]
        elif stype == 'labels':
            for label_id in form.platform_labels.data+form.genre_labels.data+form.other_labels.data:
                matched_labels.append(db.session.query(db.Label).get(label_id))
            for label in matched_labels:
                if form.operator.data == "or":
                    label_or.append(label.id) # This is for speed.  Using or_conditions proved horribly slow.
                elif form.operator.data == "and":
                    and_conditions.append(db.Article.labels.contains(label))
        elif stype == 'all':
            and_conditions = [db.Article.published == True]
        order_by = {"timestamp": db.Article.timestamp, "rating": db.Rating.rating, "views": db.Article.views}[form.sort.data]
        order = {'asc': asc, 'desc': desc}[form.order.data]
        
        articles = db.session.query(db.Article).outerjoin(db.Article.rating).filter(and_(*and_conditions)).filter(or_(*or_conditions))
        if label_or:
            articles = articles.filter(db.Article.labels.any(db.Label.id.in_(label_or)))
        matched_articles = articles.order_by(order(order_by)).all() # Nope, this won't work without the all.  It'll just regard everything which matched, including dupes (which get nuked when /read/ but that's about it).  :(
        count = len(matched_articles)
        matched_articles = matched_articles[(page-1)*5:(page)*5]
        
    return render_template("search.html", form=form, searched=searched, matched_articles=matched_articles, matched_labels=matched_labels, count=count, page=page, stype=stype)

# TODO all these POSTs should go elsewhere with a redirect.  Better for refreshing.
@app.route("/articles/<int:article_id>", methods=['GET'])
@app.route("/articles/<int:article_id>-<path:title>", methods=['GET'])
@app.route("/articles/<int:article_id>/post", methods=['POST'])
@app.route("/articles/<int:article_id>-<path:title>/post", methods=['POST'])
def article(article_id, title=None):
    article = db.session.query(db.Article).get(article_id)
    if not article: abort(404)
    class UploadForm(Form):
        image = FileField('Obrázek', [file_allowed(uploads, "Jen obrázky")])
        title = TextField('Titulek obrázku', [validators.required()])
        submit = SubmitField('Přidat obrázek')
    
    upload_form = UploadForm(request.form)
    if request.method == 'POST' and request.form['submit'] == upload_form.submit.label.text and upload_form.validate():
        media = upload_image(title=upload_form.title.data, author=g.user,
            article=article)
        db.session.commit() # Gotta commit here 'cause we're REDIRECTING THE USER
        return redirect(article.url)
    
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
        media = db.Media(type="video", url=video_form.url.data, timestamp=datetime.now(), article=article, author=g.user, title=video_form.video_title.data)
        db.session.add(media)
        flash("Video přidáno.")
        db.session.commit()
        return redirect(article.url)
    
    class RatingForm(Form):
        rating = SelectField('Hodnocení', choices=[(0, '-')]+[(i+1, str(i+1)) for i in range(0,10)], coerce=int)
        submit = SubmitField('Přidat hodnocení')
    
    rating = db.session.query(db.Rating).filter(db.Rating.article == article) \
         .filter(db.Rating.user == g.user).scalar()
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
            rating = db.Rating(rating=rating_form.rating.data, user_id=g.user.id, article=article)
            if article.author == g.user: # If the author removes then adds an rating using this form
                article.rating = rating
            db.session.add(rating)
            msg = "Ohodnoceno."
        flash(msg)
        db.session.commit()
        return redirect(article.url)
    
    if g.user.guest:
        name_validators = [validators.required()]
    else:
        name_validators = [validators.optional()]
    class ReactionForm(Form):
        name = TextField('Jméno', name_validators) # Only for guests
        text = TextAreaField('Text', [validators.required()])
        rating = SelectField('Hodnocení', choices=[(0, '-')]+[(i+1, str(i+1)) for i in range(0,10)], coerce=int)
        image = SelectField('Obrázek', choices=[(-1, '-')], coerce=int, default=-1)
        submit = SubmitField('Přidat reakci')
    
    reaction_form = ReactionForm(request.form, rating=rating.rating if (rating and article.author != g.user) else 0)
    for media in article.all_media:
        if media.author == g.user and not media.assigned_article and not media.assigned_reaction:
            reaction_form.image.choices.append((media.id, media.title))
    if request.method == 'POST' and request.form['submit'] == reaction_form.submit.label.text and reaction_form.validate():
        if reaction_form.name.data: # This technically allows logged-in users to post as guests if they hack the input in.
            user = get_guest(reaction_form.name.data)
        else:
            user = g.user
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
        db.session.commit()
        return redirect(article.url)
    
    article.views += 1
    db.session.commit()
    # TODO make these @properties of the article?
    images = db.session.query(db.Media).filter(db.Media.article==article).filter(db.Media.type=="image").all()
    videos = db.session.query(db.Media).filter(db.Media.article==article).filter(db.Media.type=="video").all()
    return render_template("article.html", article=article, upload_form=upload_form, reaction_form=reaction_form, rating_form=rating_form, video_form=video_form, images=images, videos=videos)

@app.route("/reactions/<int:reaction_id>", methods=['GET'])
def reaction(reaction_id):
    reaction = db.session.query(db.Reaction).get(reaction_id)
    if not reaction: abort(404)
    return redirect(reaction.article.url+"#reaction-"+str(reaction.id))

@app.route("/reactions/<int:reaction_id>/edit", methods=['GET', 'POST'])
@minrights(1)
def edit_reaction(reaction_id):
    reaction = db.session.query(db.Reaction).get(reaction_id)
    if not reaction: abort(404)
    if not g.user.admin and (g.user != reaction.author): abort(403)
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
        if media.author == g.user and not media.assigned_article and not media.assigned_reaction:
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

@app.route("/reactions/<int:reaction_id>/delete", methods=['POST'])
@minrights(3) # Only admins can delete reactions.
def delete_reaction(reaction_id):
    reaction = db.session.query(db.Reaction).get(reaction_id)
    if not reaction: abort(404)
    if request.method == 'POST':
        print("Reaction id "+str(reaction.id)+" DELETED")
        print(reaction.id, reaction.author.id, reaction.author.name, reaction.text)
        db.session.delete(reaction)
        db.session.commit()
        flash("Reakce odstraněna")
        return redirect(reaction.article.url)

# TODO /media/id redirect to image itself
@app.route("/media/<int:media_id>/edit", methods=['GET', 'POST'])
@minrights(1)
def edit_media(media_id):
    media = db.session.query(db.Media).get(media_id)
    if not media: abort(404)
    if not g.user.admin and (g.user != media.author): abort(403)
    # TODO image rank
    class EditMediaForm(Form):
        title = TextField('Titulek', [validators.required()])
        submit = SubmitField('Upravit')
    
    class AdminEditMediaForm(EditMediaForm):
        url = TextField('URL (u obrázků jen pokud víš co děláš)', [validators.required()])
    
    if not g.user.admin:
        form = EditMediaForm(request.form, media)
    else:
        form = AdminEditMediaForm(request.form, media)
    
    if request.method == 'POST' and form.validate():
        if g.user.admin:
            media.url = form.url.data
        media.title = form.title.data
        db.session.commit()
        if media.type == "image":
            flash("Obrázek upraven.")
        else:
            flash("Video upraveno.")
        return redirect(media.article.url+"#media-"+str(media.id))
    
    return render_template("edit_media.html", media=media, form=form)

@app.route("/media/<int:media_id>/delete", methods=['POST'])
@minrights(1)
def delete_media(media_id):
    media = db.session.query(db.Media).get(media_id)
    if not media: abort(404)
    if not g.user.admin and (g.user != media.author): abort(403)
    if request.method == 'POST':
        db.session.delete(media)
        db.session.commit()
        if media.type == "image": flash("Obrázek odstraněn")
        else: flash("Video odstraněno")
        return redirect(media.article.url)
    

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
            g.user = user
            g.user.ip = request.remote_addr
            db.session.commit()
            flash("Jste přihlášeni.")
            return redirect("/")
        else: # This ought to be removed in a "short" while.
            user = db.session.query(db.User).filter_by(name=form.name.data).filter_by(password="FIXME").scalar()
            if user:
                session['user_id'] = user.id
                g.user = user
                g.user.ip = request.remote_addr
                db.session.commit()
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
            laststamp=datetime.now(), last_post_read_id=0)
        db.session.add(user)
        db.session.commit()
        g.user = db.session.query(db.User).filter_by(name=form.name.data).filter_by(password=pwhash(form.password.data)).scalar()
        flash("Jste zaregistrováni.")
        return redirect("/login")
    
    return render_template("register.html", form=form)

@app.route("/users", methods=['GET'])
def users():
    users = db.session.query(db.User) \
        .order_by(db.User.name.asc()).filter(db.User.password != None).all()
    anons = db.session.query(db.User) \
        .order_by(db.User.laststamp.desc()).filter(db.User.password == None).all()
    return render_template("users.html", users=users, anons=anons)

@app.route("/users/<int:user_id>", methods=['GET'])
@app.route("/users/<int:user_id>-<path:name>", methods=['GET'])
def user(user_id, name=None):
    user = db.session.query(db.User).get(user_id)
    if not user: abort(404)
    page = get_page()
    return render_template('user.html', user=user, page=page)

@app.route("/users/<int:user_id>/edit", methods=['GET', 'POST'])
@app.route("/users/<int:user_id>-<path:name>/edit", methods=['GET', 'POST'])
@minrights(1)
def edit_user(user_id, name=None):
    user = db.session.query(db.User).get(user_id)
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
    if g.user.rights >= 3:
        form = AdminEditUserForm(request.form, user)
        admin = True
    elif user == g.user:
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
                user_id=g.user.id)
            db.session.add(label)
            db.session.commit()
            flash('Štítek přidán')
    
    if edit_id:
        editlabel = db.session.query(db.Label).get(edit_id)
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

@app.route("/labels/<int:label_id>/mass", methods=['GET', 'POST'])
@minrights(2)
def mass_label(label_id):
    label = db.session.query(db.Label).get(label_id)
    class MassLabelForm(Form):
        labels = MultiCheckboxField('Štítky', coerce=int)
        submit = SubmitField("Oštítkovat")
    articles = db.session.query(db.Article).order_by(db.Article.timestamp.asc).all()
    form.articles.choices = [(a.id, a.title) for a in labels]
    return render_template("mass_label")
    

def upload_image(**kvargs):
    media = None
    if 'image' in request.files and request.files['image'].filename != "":
        # TODO check for duplicate filenames
        if "." not in request.files['image'].filename or request.files['image'].filename.split(".")[-1].lower() not in ('png', 'jpg', 'jpeg', 'gif'):
            flash("Nahraný soubor není obrázek.", 'error')
            return None
        image = request.files['image']
        filename = secure_filename(image.filename)
        if os.path.exists(os.path.join("static/uploads/", filename)): # Lazy
            filename = filename.split(".")
            filename[0] += "_"
            filename = ".".join(filename)
        image.save(os.path.join("static/uploads/", filename))
        media = db.Media(type="image", url="/static/uploads/"+filename, timestamp=datetime.now(), **kvargs)
        db.session.add(media)
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
            author_id=g.user.id, 
            timestamp=datetime.now(), published=True)
        media = upload_image(title=form.image_title.data, author_id=g.user.id,
            article=article)
        article.media = media
        article.f2p = form.f2p.data
        if form.rating.data:
            article.rating = db.Rating(rating=form.rating.data, user_id=g.user.id, article=article)
        article.labels = []
        for label_id in form.labels.data:
            article.labels.append(db.session.query(db.Label).filter_by(id=label_id).scalar())
        db.session.add(article)
        db.session.commit()
        flash('Článek přidán')
        return redirect("/")
    return render_template("new_article.html", form=form)
    
@app.route("/articles/<int:edit_id>/edit", methods=['GET', 'POST'])
@app.route("/articles/<int:edit_id>-<title>/edit", methods=['GET', 'POST'])
@minrights(1)
def edit_article(edit_id, title=None):
    article = db.session.query(db.Article).get(edit_id)
    if not article: abort(404)
    if not g.user.admin and (g.user != article.author): abort(403)
    class EditArticleForm(ArticleForm):
        image = SelectField('Obrázek', choices=[(-1, '-')], coerce=int)
    form = EditArticleForm(request.form, article)
    for media in article.all_media:
        if media.author == g.user and not media.assigned_article and not media.assigned_reaction:
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
            article.rating = db.Rating(rating=form.rating.data, user_id=g.user.id, article=article)
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

class ShoutboxPostForm(Form):
    text = TextField('Text', [validators.required()])
    submit = SubmitField('Odeslat')

class GuestShoutboxPostForm(ShoutboxPostForm):
    name = TextField("Jméno", [validators.required()])

@app.route("/shoutbox", methods=['GET'])
@app.route("/shoutbox/post", methods=['POST'])
def shoutbox():
    page = get_page()
    posts = db.session.query(db.ShoutboxPost).order_by(db.ShoutboxPost.timestamp.desc())[(page-1)*30:page*30]
    count =  db.session.query(db.ShoutboxPost).count()
    if not posts: abort(404)
    if g.user.guest:
        guest = db.session.query(db.User).filter(db.User.name != None).filter(db.User.password == None).filter(db.User.ip == g.user.ip).order_by(db.User.laststamp.desc()).limit(1).scalar()
        name = None
        if guest:
            name = guest.name
        form = GuestShoutboxPostForm(request.form, name=name)
    else:
        form = ShoutboxPostForm(request.form)
    
    
    if request.method == 'POST' and form.validate():
        if g.user.guest:
            user = get_guest(form.name.data)
        else: user = g.user
        post = db.ShoutboxPost(author=user, text=form.text.data, timestamp=datetime.now(), )
        db.session.add(post)
        db.session.commit()
        #flash("Příspěvek přidán.")
        return redirect("/shoutbox")
        
    if page == 1: g.user.last_post_read = posts[0]
    g.unread = 0
    db.session.commit()
    
    return render_template("shoutbox.html", posts=posts, form=form, count=count, page=page)
    

@app.route("/buttons", methods=['GET', 'POST'])
@minrights(3)
def buttons(): # QUICK 'N DIRTY OKAY.
    class ButtonForm(Form):
        icon = TextField('Ikonka')
        name = TextField('Jméno', [validators.required()])
        url = TextField('URL (ne pokud bude mít štítky)')
        location = SelectField('Umístění', choices=[("left","vlevo"),("right","vpravo")], default="left")
        submit = SubmitField('Přidat tlačítko')
    form = ButtonForm(request.form)
    if request.method == 'POST' and form.validate():
        if form.location.data == "left": count=len(g.left_buttons)
        else: count = len(g.right_buttons)
        button = db.Button(icon=form.icon.data or None, name=form.name.data, url=form.url.data or None, location=form.location.data, position=count)
        db.session.add(button)
        flash('Tlačítko "'+button.name+'" přidáno', "success")
    
    if "move" in request.args: # XXX UGLY HACK WARNING
        move = request.args['move']
        id = request.args['id']
        button = db.session.query(db.Button).get(int(id))
        thisside = {'left':g.left_buttons, 'right':g.right_buttons}[button.location] # WOW.
        if move == "up":
            thisside[button.position-1].position += 1
            button.position -= 1
        elif move == "down":
            thisside[button.position+1].position -= 1
            button.position += 1
    
    db.session.commit()
    
    g.left_buttons = db.session.query(db.Button).filter(db.Button.location=="left").order_by(db.Button.position).all()
    g.right_buttons = db.session.query(db.Button).filter(db.Button.location=="right").order_by(db.Button.position).all()
    
    return render_template("buttons.html", form=form)

@app.route("/buttons/<int:button_id>/edit", methods=['GET', 'POST'])
@minrights(3)
def edit_button(button_id): # quick and dirty 2: electric boogaloo
    button = db.session.query(db.Button).get(button_id)
    if not button: abort(404)
    class ButtonForm(Form): # WOW!!  IT'S FREAKING NOTHING!!
        icon = TextField('Ikonka')
        name = TextField('Jméno', [validators.required()])
        url = TextField('URL (ne pokud bude mít štítky)')
        submit = SubmitField('UPRAVIT tlačítko')
    form = ButtonForm(request.form, button)
    
    class LabelForm(Form):
        label = SelectField("Štítek", coerce=int)
        submit = SubmitField("Přidat")
    label_form = LabelForm(request.form)
    labels = db.session.query(db.Label) \
        .order_by(db.Label.category.asc(), db.Label.name.asc()).all()
    label_form.label.choices = [(l.id, l.category[0]+": "+l.name) for l in labels]
    
    if request.method == 'POST' and request.form['submit'] == form.submit.label.text and form.validate():
        button.icon, button.name, button.url = form.icon.data or None, form.name.data, form.url.data or None
        flash("Tlačítko upraveno.")
        db.session.commit()
        return redirect("/buttons")

    if request.method == 'POST' and request.form['submit'] == label_form.submit.label.text and label_form.validate():
        button.labels.append(db.ButtonLabel(button=button, label_id=int(label_form.label.data), position=len(button.labels)))
        db.session.commit()
    
    if "move" in request.args: # XXX UGLY HACK WARNING
        move = request.args['move']
        id = request.args['id']
        button_label = db.session.query(db.ButtonLabel).get(int(id))
        labels = db.session.query(db.ButtonLabel).filter(db.ButtonLabel.button == button).order_by(db.ButtonLabel.position).all()
        print(labels, button_label.position)
        if move == "up":
            labels[button_label.position-1].position += 1
            button_label.position -= 1
        elif move == "down":
            labels[button_label.position+1].position -= 1
            button_label.position += 1
        elif move == "delete":
            for i in range(button_label.position, len(button.labels)):
                labels[i].position -= 1
            db.session.delete(button_label)
        db.session.commit()
    
    labels = db.session.query(db.ButtonLabel).filter(db.ButtonLabel.button == button).order_by(db.ButtonLabel.position).all()
    
    return render_template("edit_button.html", form=form, labels=labels, label_form=label_form, button=button)

@app.route("/buttons/<int:button_id>/delete", methods=['POST'])
@minrights(3)
def delete_button(button_id): # quick and dirty 3: dark dawn
    button = db.session.query(db.Button).get(button_id)
    if not button: abort(404)
    thisside = {'left':g.left_buttons, 'right':g.right_buttons}[button.location]
    for i in range(button.position, len(thisside)):
        thisside[i].position -= 1
    db.session.delete(button)
    db.session.commit()
    flash('Tlačítko "'+button.name+'" odstraněno')
    return redirect("/buttons")

# Redirects for ANCIENT stuff.
@app.route("/index.php")
def index_php():
    page = request.args.get('page')
    if page == "main": return redirect("/", 301)
    if page == "info": return redirect("/info", 301)
    if page == "single":
        article = db.session.query(db.Article).get(request.args.get('id'))
        return redirect(article.url, 301)
    if page == "search":
        if 'id_labels' in request.args:
            label = db.session.query(db.Label).get(request.args.get('id_labels'))
            if not label: return redirect("/search?labels", 301)
            return redirect(label.url, 301)
        elif 'id_users' in request.args:
            user = db.session.query(db.User).get(request.args.get('id_users'))
            return redirect(user.url, 301)
        elif 'all' in request.args:
            return redirect("/search?all", 301)
        return redirect("/search")
    if page == "article": return redirect("/new_article", 301)
    if page == "labels": return redirect("/labels", 301)
    if page == "login": return redirect("/login", 301)
    if page == "list": return redirect("/search?all", 301)

@app.route("/rss")
@app.route("/rss/")
def rss():
    articles = db.session.query(db.Article) \
        .order_by(db.Article.timestamp.desc()).limit(10).all()
    now = datetime.now()
    response = make_response(render_template("rss.xml", articles=articles, now=now))
    response.headers['Content-type'] = "application/rss+xml"
    return response

if __name__ == "__main__":
    app.run(host="", port=5631, debug=True, threaded=True)
