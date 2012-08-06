from __future__ import absolute_import, unicode_literals, print_function

from flask import Flask
app = Flask('z20p')


@app.route("/")
def root():
    return "Wow this is totally useless so far!"
