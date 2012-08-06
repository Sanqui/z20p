# encoding: utf-8
from __future__ import absolute_import, unicode_literals, print_function

from z20p import db

from datetime import datetime
from flask import Flask, render_template, request, flash, redirect
app = Flask('z20p')
app.secret_key = b"superuniqueandsecret"

# TODO split this into file
from wtforms import Form, BooleanField, TextField, TextAreaField, PasswordField, IntegerField, validators
class ArticleForm(Form):
    title = TextField('Titulek', [validators.required()])
    text = TextAreaField('Text', [validators.required()])
    rating = IntegerField('Hodnocení', [validators.optional()])
    image_url = TextField('URL obrázku', [validators.optional()])
    image_title = TextField('Titulek obrázku', [validators.optional()])

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

@app.route("/new_article", methods=['GET', 'POST'])
def new_article():
    form = ArticleForm(request.form)
    if request.method == 'POST' and form.validate():
        article = db.Article(title=form.title.data, text=form.text.data,
            rating=form.rating.data, image_url=form.image_url.data,
            image_title=form.image_title.data, author_id=0, timestamp=datetime.utcnow())
        db.session.add(article)
        db.session.commit()
        flash('Článek přidán')
        return redirect("/")
    return render_template("new_article.html", form=form)
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
