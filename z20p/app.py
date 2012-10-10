# encoding: utf-8
from __future__ import absolute_import, unicode_literals, print_function

#from z20p import db
import db
from sqlalchemy import or_, and_, asc, desc

from lxml.html.clean import Cleaner

from datetime import datetime
import time
from functools import wraps # We need this to make Flask understand decorated routes.
import hashlib
import os
import subprocess
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

rating_field = SelectField('Hodnocení', choices=[(-2, '-'), (-1, 'N')]+[(i, str(i)) for i in range(0,11)], coerce=int)

class ArticleForm(Form):
    title = TextField('Titulek', [validators.required()])
    text = TextAreaField('Text', [validators.required()])
    rating = rating_field
    f2p = SelectField('Hratelné zdarma', choices=[(-1, "N/A"), (0, "Ne"), (1, "Ano")], coerce=int)
    labels = MultiCheckboxField('Štítky', coerce=int)
    image = FileField('Obrázek', [file_allowed(uploads, "Jen obrázky")])
    image_title = TextField('Titulek obrázku', [validators.optional()])
    
    # TODO make this work??
    #def validate_image(self, field):
    #    if "." in field.data and field.data.split('.')[-1] in ('png', 'jpg', 'jpeg', 'gif'):
    #        return
    #    else:
    #        raise ValidationError("Nepovolený typ souboru.")

class RedactorArticleForm(ArticleForm):
    published = BooleanField("Publikovat")

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
            if g.user.rights >= minrights:
                return function(*args, **kvargs)
            else:
                return abort(403)
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
        g.kip = random.randint(0, 12) == 0
        if g.kip:
            g.kipleft = random.randint(0, 100)
            g.kiptop = random.randint(0, 100)
            g.kiptype = random.randint(1,2)
        #g.unread_posts = latest - g.user.last_post_read.id
    g.article_query = db.session.query(db.Article).filter(db.Article.published == True)

@app.teardown_request
def shutdown_session(exception=None):
    db.session.close()
    db.session.remove()

@app.template_filter('datetime')
def datetime_format(value, format='%d. %m. %Y  %H:%M'):
    if not value: return "-"
    if isinstance(value, unicode): return value
    return value.strftime(format)

cleaner = Cleaner(comments=False, style=False, embedded=False, annoying_tags=False)

@app.template_filter('clean')
def clean(value):
    if value: return cleaner.clean_html(value)
    else: return ""

# https://gist.github.com/3765578
def url_for_here(**changed_args):
    args = request.args.to_dict(flat=False)
    args.update(request.view_args)
    args.update(changed_args)
    return url_for(request.endpoint, **args)

app.jinja_env.globals['url_for_here'] = url_for_here
app.jinja_env.globals['round'] = round # useful

@app.errorhandler(404)
def page_not_found(e):
    if not request.path.startswith("/static"):
        return render_template('errorpage.html', error=404), 404
    else:
        return "404", 404 # We don't have templatestuffs.

@app.errorhandler(403)
def page_not_found(e):
    return render_template('errorpage.html', error=403), 403

@app.errorhandler(500)
def page_not_found(e):
    return render_template('errorpage.html', error=500), 500

@app.route("/")
def main():
    page = get_page()
    page_columns = get_page("page_columns")
    column_labels = db.session.query(db.Label).filter(db.Label.category == "column").all()
    articles = g.article_query.order_by(db.Article.publish_timestamp.desc()).filter(~ db.Article.labels.any(db.Label.id.in_([l.id for l in column_labels])))[(page-1)*3:page*3]
    columns = g.article_query.order_by(db.Article.publish_timestamp.desc()).filter(db.Article.labels.any(db.Label.id.in_([l.id for l in column_labels])))[(page_columns-1)*2:page_columns*2]
    images = db.session.query(db.Media).join(db.Media.article).filter(db.Media.type=="image") \
        .filter(db.Article.published == True).order_by(db.Media.timestamp.desc()).limit(8).all()
    videos = db.session.query(db.Media).filter(db.Media.type=="video") \
        .order_by(db.Media.timestamp.desc()).limit(2).all()
    return render_template("main.html", articles=articles, images=images, columns=columns, videos=videos, page=page, page_columns=page_columns)

def get_page(name="page"):
    try: # This needs more magic...
        page = int(request.args.get(name))
    except TypeError:
        page = 1
    except ValueError:
        abort(400)
    if page == 0: abort(400)
    return page

@app.route("/info")
def info():
    return render_template("info.html")

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
        operator = SelectField("Operátor", choices=[("or", "nebo"), ("and", "a"), ("nor", "ani")], default="or")
        labels = HiddenField("labels", default="y")
    
    if 'labels' in request.args:
        stype = 'labels'
        form = LabelSearchForm(request.args)
        
        labels = db.session.query(db.Label) \
            .order_by(db.Label.name.asc()).all()
        for label in labels:
            if label.category == 'platform': f = form.platform_labels
            if label.category == 'genre': f = form.genre_labels
            if label.category == 'other' or label.category == 'column': f = form.other_labels
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
        label_nor = []
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
                elif form.operator.data == "nor":
                    label_nor.append(label.id)
                elif form.operator.data == "and":
                    and_conditions.append(db.Article.labels.contains(label))
        elif stype == 'all':
            and_conditions = [db.Article.published == True]
        order_by = {"timestamp": db.Article.publish_timestamp, "rating": db.Rating.rating, "views": db.Article.views}[form.sort.data]
        order = {'asc': asc, 'desc': desc}[form.order.data]
        
        articles = g.article_query
        if order_by == db.Rating.rating:
            articles = articles.join(db.Article.rating)
        else:
            articles = articles.outerjoin(db.Article.rating)
        articles = articles.filter(and_(*and_conditions)).filter(or_(*or_conditions))
        if label_or:
            articles = articles.filter(db.Article.labels.any(db.Label.id.in_(label_or)))
        if label_nor:
            articles = articles.filter(~ db.Article.labels.any(db.Label.id.in_(label_nor)))
        matched_articles = articles.order_by(order(order_by)).all() # Nope, this won't work without the all.  It'll just regard everything which matched, including dupes (which get nuked when /read/ but that's about it).  :(
        count = len(matched_articles)
        matched_articles = matched_articles[(page-1)*7:(page)*7]
        
    return render_template("search.html", form=form, searched=searched, matched_articles=matched_articles, matched_labels=matched_labels, count=count, page=page, stype=stype)

class VideoForm(Form):
    url = TextField('URL videa', [validators.required(), validators.URL("Musí být Youtube URL.")])
    video_title = TextField('Titulek videa', [validators.required()])
    submit = SubmitField('Přidat video')
    
    def validate_url(self, url):
        if url.data.startswith("http") and ("youtube" in url.data or "youtu.be/" in url.data):
            pass
        else:
            raise ValidationError("Musí být Youtube URL.")

@app.route("/articles/<int:article_id>", methods=['GET'])
@app.route("/articles/<int:article_id>-<path:title>", methods=['GET'])
@app.route("/articles/<int:article_id>/post", methods=['POST'])
@app.route("/articles/<int:article_id>-<path:title>/post", methods=['POST'])
def article(article_id, title=None):
    article = db.session.query(db.Article).get(article_id)
    if not article: abort(404)
    if not article.published and not g.user.redactor and article.author != g.user: abort(403)
    
    upload_form = UploadForm(request.form)
    upload_form.populate()
    if request.method == 'POST' and request.form['submit'] == upload_form.submit.label.text and upload_form.validate():
        media = upload_image(title=upload_form.title.data, author=g.user,
            article=article, rank=upload_form.rank.data)
        db.session.commit() # Gotta commit here 'cause we're REDIRECTING THE USER
        return redirect(article.url+"#gallery-images")
    
    video_form = VideoForm(request.form)
    
    if request.method == 'POST' and request.form['submit'] == video_form.submit.label.text and video_form.validate():
        media = db.Media(type="video", url=video_form.url.data, timestamp=datetime.now(), article=article, author=g.user, title=video_form.video_title.data)
        db.session.add(media)
        flash("Video přidáno.")
        db.session.commit()
        return redirect(article.url)
    
    class RatingForm(Form):
        rating = rating_field
        submit = SubmitField('Přidat hodnocení')
    
    rating = db.session.query(db.Rating).filter(db.Rating.article == article) \
         .filter(db.Rating.user == g.user).first()
    rating_form = RatingForm(request.form, rating=-2 if (not rating or rating == None) else rating.rating)
    
    if request.method == 'POST' and request.form['submit'] == rating_form.submit.label.text and rating_form.validate(): # XXX
        msg = "Hodnocení nedotčeno."
        if rating:
            if rating_form.rating.data != -2:
                rating.rating = form.rating.data
                msg = "Hodnocení upraveno."
            else:
                db.session.delete(rating)
                msg = "Hodnocení odebráno."
        else:
            if rating_form.rating.data != -2:
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
        rating = rating_field
        image = FileField('Obrázek', [file_allowed(uploads, "Jen obrázky")])
        title = TextField('Titulek obrázku', [validators.optional()])
        submit = SubmitField('Přidat reakci')
    
    
    reaction_form = ReactionForm(request.form, rating=rating.rating if (rating and rating.rating != None and article.author != g.user) else -2)
    if not article.rating: reaction_form.rating = None
    #for media in article.all_media:
    #    if media.author == g.user and not media.assigned_article and not media.assigned_reaction:
    #        reaction_form.image.choices.append((media.id, media.title))
    if request.method == 'POST' and request.form['submit'] == reaction_form.submit.label.text and reaction_form.validate():
        if reaction_form.name.data: # This technically allows logged-in users to post as guests if they hack the input in.
            user = get_guest(reaction_form.name.data)
        else:
            user = g.user
        rating = None
        if user != article.author:
            if rating and rating_form.rating.data != -2:
                rating.raing = None if reaction_form.rating.data == -2 else reaction_form.rating.data
            elif rating_form.rating.data != -2:
                rating = db.Rating(rating=None if reaction_form.rating.data == -2 else reaction_form.rating.data, user=user, article=article)
                db.session.add(rating)
        media = upload_image(title=upload_form.title.data, author=user,
            article=article, rank=2)
        reaction = db.Reaction(text=reaction_form.text.data, rating=rating, article=article, timestamp=datetime.now(), author=user, media=media)
        db.session.add(reaction)
        flash("Reakce přidána.")
        db.session.commit()
        return redirect(article.url)
    
    article.views += 1
    db.session.commit()
    # TODO make these @properties of the article?
    images = db.session.query(db.Media).filter(db.Media.article==article).filter(db.Media.type=="image").order_by(db.Media.rank.desc(), db.Media.timestamp.asc()).all()
    videos = db.session.query(db.Media).filter(db.Media.article==article).filter(db.Media.type=="video").order_by(db.Media.rank.desc(), db.Media.timestamp.asc()).all()
    return render_template("article.html", article=article, upload_form=upload_form, reaction_form=reaction_form, rating_form=rating_form, video_form=video_form, images=images, videos=videos)


@app.route("/reactions/", methods=['GET'])
def reactions():
    page = get_page()
    reactions = db.session.query(db.Reaction).join(db.Reaction.article).filter(db.Article.published == True).order_by(db.Reaction.timestamp.desc())[(page-1)*10:(page)*10]
    count = db.session.query(db.Reaction).join(db.Reaction.article).filter(db.Article.published == True).count()
    return render_template("reactions.html", reactions=reactions, page=page, count=count)

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
        rating = rating_field
        image = SelectField('Obrázek', choices=[(-1, '-')], coerce=int)
        submit = SubmitField('Upravit reakci')
    # This could be constructed better...
    rating = db.session.query(db.Rating).filter(db.Rating.assigned_reaction.contains(reaction)) \
         .filter(db.Rating.user == reaction.author).scalar()
    form = EditReactionForm(request.form, reaction)
    if form.rating.data == None: form.rating.data = rating.rating if (rating and rating.rating != None) else -2
    for media in reaction.article.all_media:
        if media.author == g.user and not media.assigned_article and not media.reactions:
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
        if form.rating.data != -2:
            if rating:
                rating.rating = None if form.rating.data == -2 else form.rating.data
            else:
                rating = db.Rating(rating=None if form.rating.data == -2 else form.rating.data, user=reaction.author, article=reaction.article)
            reaction.rating = rating
        else:
            reaction.rating = None
        reaction.edit_timestamp = datetime.now()
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

class MediaForm(Form):
    rank = SelectField("Váha", choices=[], default=2, coerce=int)
    
    def populate(self):
        self.rank.choices = [(2, "Normální"), (1, "Nízká")]
        if g.user.rights >= 2: self.rank.choices.insert(0, (3, "Vysoká"))

class UploadForm(MediaForm):
    image = FileField('Obrázek', [file_allowed(uploads, "Jen obrázky")])
    title = TextField('Titulek obrázku', [validators.required()])
    submit = SubmitField('Přidat obrázek')

@app.route("/media", methods=['GET'])
@app.route("/media/post", methods=["GET", 'POST'])
def media():
    class SortForm(Form):
        type = SelectField("Co", choices=[("image", "obrázky"), ("video", "videa"), ("both", "obojí")], default="image")
        order = SelectField("Typ řazení", choices=[("desc", "sestupně"), ("asc", "vzestupně")], default="desc")
        filter = SelectField("Se články", choices=[("article", "jen u článků"), ("all", "všechny"), ("no_article", "jen bez článku")], default="article")
        author = SelectField("Od autora", choices=[(0, "všech")], default=0, coerce=int)
    
    form = SortForm(request.args)
    for user in db.session.query(db.User).join(db.User.media).filter(db.User.media.any()).all():
        form.author.choices.append((user.id, user.name or user.ip))
    
    upload_form = UploadForm(request.form)
    upload_form.populate()
    if request.method == 'POST' and form.type.data == "image" and upload_form.validate():
        media = upload_image(title=upload_form.title.data, author=g.user,
            article=None, rank=upload_form.rank.data)
        db.session.commit()
        return redirect("/media?filter=all#top")

    video_form = VideoForm(request.form)
    if request.method == 'POST' and form.type.data == "video" and video_form.validate():
        video = db.Media(title=video_form.video_title.data, url=video_form.url.data, type="video", timestamp=datetime.now(), author=g.user)
        db.session.add(video)
        db.session.commit()
        return redirect("/media?filter=all&type=video#top")
    
    page = get_page()
    
    order = {'asc': asc, 'desc': desc}[form.order.data]
    query = db.session.query(db.Media).order_by(order(db.Media.timestamp))
    if form.type.data != "both":
        query = query.filter(db.Media.type == form.type.data)
    if form.filter.data == "no_article":
        query = query.filter(db.Media.article == None)
    elif form.filter.data == "article":
        query = query.join(db.Media.article).filter(db.Article.published == True)
    if form.author.data: query = query.filter(db.Media.author_id == form.author.data)
    media = query[(page-1)*30:page*30]
    count = query.count()
    return render_template("media.html", upload_form=upload_form, video_form=video_form, form=form, media=media, page=page, count=count)

# TODO /media/id redirect to image itself
@app.route("/media/<int:media_id>/edit", methods=['GET', 'POST'])
@minrights(1)
def edit_media(media_id):
    media = db.session.query(db.Media).get(media_id)
    if not media: abort(404)
    if not g.user.admin and (g.user != media.author): abort(403)
    # TODO image rank
    class EditMediaForm(MediaForm):
        title = TextField('Titulek', [validators.required()])
        submit = SubmitField('Upravit')
        
    class AdminEditMediaForm(EditMediaForm):
        article = SelectField('Článek', choices=[(0, "[Bez článku]")], default=media.article.id if media.article else 0, coerce=int)
        url = TextField('URL (u obrázků jen pokud víš co děláš)', [validators.required()])
    
    if not g.user.admin:
        form = EditMediaForm(request.form, media)
    else:
        form = AdminEditMediaForm(request.form, media)
        for article in db.session.query(db.Article).order_by(db.Article.timestamp.desc()).all():
            form.article.choices.append((article.id, article.title))
            if request.method == 'GET': form.article.data = media.article.id if media.article else 0
    
    form.populate()
    
    if request.method == 'POST' and form.validate():
        if g.user.admin:
            media.url = form.url.data
            if form.article.data:
                media.article_id = form.article.data
            else:
                media.article = None
        media.title = form.title.data
        media.rank = form.rank.data
        db.session.commit()
        if media.type == "image":
            flash("Obrázek upraven.")
        else:
            flash("Video upraveno.")
        if media.article:
            return redirect(media.article.url+"#media-"+str(media.id))
        else:
            return redirect("/media?filter=no_article")
        media.edit_timestamp = datetime.now()
    
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
        return redirect(media.article.url or "/media")
    

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
        name = TextField('Jméno', [validators.required(), validators.Length(3, 20, "Jméno musí být mezi třemi a dvaceti znaky.")])
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
        g.user = user
        g.user.ip = request.remote_addr
        db.session.commit()
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
    articles = g.article_query.filter(db.Article.author == user).order_by(db.Article.publish_timestamp.desc()).all()
    if not user: abort(404)
    page = get_page()
    return render_template('user.html', user=user, page=page, articles=articles)

@app.route("/users/<int:user_id>/edit", methods=['GET', 'POST'])
@app.route("/users/<int:user_id>-<path:name>/edit", methods=['GET', 'POST'])
@minrights(1)
def edit_user(user_id, name=None):
    user = db.session.query(db.User).get(user_id)
    if not user: abort(404)
    class EditUserForm(Form):
        email = TextField('Email', [validators.optional(), validators.Email("Musí být platná emailová adresa.")])
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
    if g.user.admin:
        form = AdminEditUserForm(request.form, user)
    elif user == g.user:
        form = EditUserForm(request.form, user)
    else:
        abort(403) # No editing other users!
    
    if request.method == 'POST' and form.validate():
        if g.user.admin:
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
    
    return render_template('edit_user.html', user=user, form=form)

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
    articles = g.article_query.order_by(db.Article.timestamp.asc).all()
    form.articles.choices = [(a.id, a.title) for a in labels]
    return render_template("mass_label")
    

def upload_image(**kvargs):
    media = None
    if 'image' in request.files and request.files['image'].filename != "":
        if "." not in request.files['image'].filename or request.files['image'].filename.split(".")[-1].lower() not in ('png', 'jpg', 'jpeg', 'gif'):
            flash("Nahraný soubor není obrázek.", 'error')
            return None
        image = request.files['image']
        filename = secure_filename(image.filename).replace("-", "_")
        while os.path.exists(os.path.join("static/uploads/", filename)): # Lazy
            filename = filename.split(".")
            filename[0] += "_"
            filename = ".".join(filename)
        image.save(os.path.join("static/uploads/", filename))
        subprocess.check_call(["mogrify", "-layers", "flatten", "-format", "png", "-path", "static/uploads/thumbs/", "-thumbnail", '200x96', "-strip", "-quality", "100", "-unsharp", "0x0.5", "-colors", "256", "static/uploads/"+filename], stderr=subprocess.STDOUT)
        subprocess.check_call(["mogrify", "-layers", "flatten", "-format", "png", "-path", "static/uploads/article_thumbs/", "-thumbnail", '172x300', "-strip", "-quality", "100", "-unsharp", "0x0.5", "-colors", "256", "static/uploads/"+filename])
        media = db.Media(type="image", url="/static/uploads/"+filename, timestamp=datetime.now(), **kvargs)
        db.session.add(media)
        flash("Obrázek nahrán.")
    return media

@app.route("/new_article", methods=['GET', 'POST'])
@minrights(1)
def new_article():
    form = ArticleForm(request.form)
    if g.user.redactor: form = RedactorArticleForm(request.form)
    labels = db.session.query(db.Label) \
        .order_by(db.Label.category.desc(), db.Label.name.asc()).all()
    form.labels.choices = [(l.id, l.category[0]+": "+l.name) for l in labels]
    if request.method == 'POST' and form.validate():    
        article = db.Article(title=form.title.data, text=form.text.data,
            author_id=g.user.id, 
            timestamp=datetime.now(), published=False)
        media = upload_image(title=form.image_title.data, author_id=g.user.id,
            article=article, rank=3)
        article.media = media
        article.f2p = None if form.f2p.data==-1 else form.f2p.data
        if form.rating.data != -2:
            article.rating = db.Rating(rating=form.rating.data, user_id=g.user.id, article=article)
        article.labels = []
        for label_id in form.labels.data:
            article.labels.append(db.session.query(db.Label).filter_by(id=label_id).scalar())
        if g.user.redactor:
            article.published = form.published.data
            if article.published: article.publish_timestamp = datetime.now()
            msg = "Článek přidán."
            if article.published: msg = "Článek publikován."
        else:
            msg = "Děkujeme za váš příspěvek.  Administrátor váš článek ohodnotí a rozhodne, zda-li ho publikovat."
        db.session.add(article)
        db.session.commit()
        flash(msg)
        return redirect(article.url)
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
    
    class RedactorEditArticleForm(EditArticleForm):
        published = BooleanField("Publikovat", default=True)
        publish_timestamp = TextField("Datum publikace")
    
    if g.user.redactor:
        form = RedactorEditArticleForm(request.form, article)
    else:
        form = EditArticleForm(request.form, article)
    for media in article.all_media:
        if media.author == g.user and not media.assigned_article and not media.reactions:
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
        article.f2p = None if form.f2p.data==-1 else form.f2p.data
        article.title = form.title.data
        article.text = form.text.data
        if article.rating:
            if form.rating.data == -2:
                db.session.delete(article.rating)
                article.rating = None
            else:
                article.rating.rating = form.rating.data
        else:
            if form.rating.data != -2:
                article.rating = db.Rating(rating=form.rating.data, user_id=g.user.id, article=article)
        if g.user.redactor:
            article.published = form.published.data
            if article.published and not form.publish_timestamp.data:
                article.publish_timestamp = datetime.now()
            elif form.publish_timestamp.data:
                article.publish_timestamp = form.publish_timestamp.data
            elif not form.publish_timestamp.data:
                article.publish_timestam = None
        article.labels = []
        for label_id in form.labels.data:
            article.labels.append(db.session.query(db.Label).filter_by(id=label_id).scalar())
        article.edit_timestamp = datetime.now()
        db.session.commit()
        flash('Článek upraven')
        return redirect(article.url)
    if request.method == 'GET' and form.labels.data == None: # welp
        form.labels.data = [l.id for l in article.labels]
        if article.rating:
            form.rating.data = article.rating.rating
    
    return render_template("edit_article.html", form=form, article=article)

@app.route("/unpublished", methods=['GET'])
@minrights(1)
def unpublished():
    mine = db.session.query(db.Article).filter(db.Article.published == False, db.Article.author == g.user).order_by(db.Article.timestamp.desc())
    unpublished = db.session.query(db.Article).join(db.Article.author).filter(db.Article.published == False, db.User.rights <= 1).order_by(db.Article.timestamp.desc())
    intentionally_unpublished = db.session.query(db.Article).join(db.Article.author).filter(db.Article.published == False, db.Article.author != g.user, db.User.rights >= 2).order_by(db.Article.timestamp.desc())
    return render_template("unpublished.html", mine=mine, unpublished=unpublished, intentionally_unpublished=intentionally_unpublished)

class ShoutboxPostForm(Form):
    text = TextField('Text', [validators.required()])
    submit = SubmitField('Odeslat')

class GuestShoutboxPostForm(ShoutboxPostForm):
    name = TextField("Jméno", [validators.required()])

@app.route("/shoutbox", methods=['GET'])
@app.route("/shoutbox/post", methods=['POST'])
def shoutbox():
    page = get_page()
    posts = db.session.query(db.ShoutboxPost).order_by(db.ShoutboxPost.timestamp.desc())[(page-1)*30:page*30] # , db.Article, db.Reaction, db.Media, db.User, db.Rating, db.ShoutboxPost
    #posts = db.session.query(db.ShoutboxPost).union(db.session.query(db.Reaction)).order_by("timestamp")[(page-1)*30:page*30]
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
        function = SelectField('Funkce', choices=[('', ''), ("shoutbox","Shoutbox"), ("columns", "Sloupky")])
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
        button.icon, button.name, button.url, button.function = form.icon.data or None, form.name.data, form.url.data or None, form.function.data
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
    if page == "single" and "id" in request.args:
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
    abort(404)

@app.route("/article/<path:path>")
def article_redirect(path):
    return redirect("/articles/"+path, 301)

@app.route("/rss")
@app.route("/rss/")
def rss():
    articles = g.article_query \
        .order_by(db.Article.publish_timestamp.desc()).limit(10).all()
    now = datetime.now()
    response = make_response(render_template("rss.xml", articles=articles, now=now))
    response.headers['Content-type'] = "application/rss+xml"
    return response

if __name__ == "__main__":
    app.run(host="", port=5631, debug=True, threaded=True)
