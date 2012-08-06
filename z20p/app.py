from __future__ import absolute_import, unicode_literals, print_function

from z20p import db

from flask import Flask, render_template
app = Flask('z20p')

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
    print(articles)
    return render_template("main.html", articles=articles)
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
