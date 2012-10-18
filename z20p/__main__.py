from __future__ import absolute_import

from z20p import app

app.app.run(host="", port=5631, debug=True, threaded=True, use_evalex=False) # debug=True
