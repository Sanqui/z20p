# encoding: utf-8
from datetime import datetime
import time
import os.path
import urlparse # urllib.parse in py3k
import math

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker, relationship, backref
from sqlalchemy.schema import Column, ForeignKey, Table
from sqlalchemy.types import DateTime, Integer, Unicode, Enum, UnicodeText, Boolean

engine = create_engine(open("db").read(), encoding="utf8", pool_size = 100, pool_recycle=4200) # XXX
# pool_recycle is to prevent "server has gone away"
session = scoped_session(sessionmaker(bind=engine, autoflush=False))

Base = declarative_base(bind=engine)


### Yonder tables

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, nullable=False)
    name = Column(Unicode(64))
    password = Column(Unicode(128))
    timestamp = Column(DateTime, nullable=False, index=True)
    laststamp = Column(DateTime, nullable=False, index=True)
    ip = Column(Unicode(64))
    rights = Column(Integer)
    gender = Column(Enum('m', 'f', '-'))
    email = Column(Unicode(128))
    minipic = Column(Unicode(256))
    profile = Column(UnicodeText)
    last_url = Column(Unicode(256))
    last_post_read_id = Column(Integer, ForeignKey('shoutbox_posts.id'))
    
    @property
    def guest(self):
        return not bool(self.password)
        
    @property
    def admin(self):
        return self.rights >= 4
    
    @property
    def redactor(self):
        return self.rights >= 3
    
    @property
    def url(self):
        return "/users/"+str(self.id)+("-"+self.name if self.name else "")
        
    @property
    def rank(self):
        ranks = {0: u"Guest",
                 1: {'m':u"Uživatel", 'f':u'Uživatelka', "-":u"Uživatel"}, 
                 2: u"VIP",
                 3: {'m':u"Redaktor", 'f':u'Redaktorka', '-':u'Redaktor'},
                 4: u"Admin"}
        if self.rights not in ranks:
            rank = "??? ({0})".format(self.rights)
        else:
            rank = ranks[self.rights]
            if type(rank) == dict:
                rank = rank[self.gender]
        return rank            
    
    @property 
    def score(self):
        return round(len(self.articles)**0.65+math.sqrt(len(self.reactions))*1.2+math.sqrt(len(self.media))*0.6+math.sqrt(len(self.shoutbox_posts))*0.1+math.sqrt(len(self.ratings))*0.1+(self.rights or 0), 1)

class Label(Base):
    __tablename__ = 'labels'

    id = Column(Integer, primary_key=True, nullable=False)
    name = Column(Unicode(256), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship("User", backref='labels')
    category = Column(Enum('platform', 'genre', 'column', 'other'))
    
    @property
    def url(self):
        return "/search?labels&noform&{0}_labels={1}".format("other" if self.category=="column" else self.category, self.id)

class ButtonLabel(Base):
    __tablename__ = 'buttons_labels'
    id = Column(Integer, primary_key=True)
    button_id = Column(Integer, ForeignKey('buttons.id'), nullable=False)
    #button = relationship("Button", backref=backref("labels", lazy="joined", ))
    label_id = Column(Integer, ForeignKey('labels.id'), nullable=False)
    label = relationship("Label", backref="buttons", lazy="joined")
    position = Column(Integer, nullable=False)

class Button(Base):
    __tablename__ = 'buttons'
    
    id = Column(Integer, primary_key=True, nullable=False)
    location = Column(Enum("left", "right"), nullable=False)
    position = Column(Integer, nullable=False)
    name = Column(Unicode(256), nullable=False)
    icon = Column(Unicode(256))
    url = Column(Unicode(256))
    function = Column(Enum("", "shoutbox", "columns"), nullable=False)
    
    labels = relationship(ButtonLabel, lazy="joined", order_by=ButtonLabel.position.asc(), backref="button")
    #title = Column(Unicode(256))
    
    @property
    def search_url(self):
        url = "/search?labels&noform"
        for label in self.labels:
            url += "&"+("other" if label.label.category=="column" else label.label.category)+"_labels="+str(label.label.id)
        return url

articles_labels = Table('article_labels', Base.metadata, # XXX wrong table name, but whatever.
    Column('article_id', Integer, ForeignKey('articles.id')),
    Column('label_id', Integer, ForeignKey('labels.id'))
)

# TODO store md5
class Media(Base):
    __tablename__ = 'media'
    id = Column(Integer, primary_key=True, nullable=False)
    author_id = Column(Integer, ForeignKey('users.id'))
    author = relationship("User", backref='media')
    article_id = Column(Integer, ForeignKey('articles.id'))
    timestamp = Column(DateTime, nullable=False, index=True)
    title = Column(Unicode(256), nullable=False)
    url = Column(Unicode(256), nullable=False)
    type = Column(Enum("image", "video"))
    value = Column(Integer) # Enum('featured', 'good', 'regular), but then we'd get no ordering
        
    def thumbdir(self, dir="thumbs"):
        u = self.url.split("/")
        u.insert(-1, dir)
        u = "/".join(u).split(".")
        u[-1] = "png"
        return '.'.join(u)
    
    # This is KIND OF ugly-ish!
    @property
    def thumb(self):
        if self.type == "video":
            vidid = None
            # I really ought to learn some regexes.
            url = urlparse.urlparse(self.url)
            if "youtube" in url.netloc:
                for f in url.query.split("&"):
                    if f.startswith("v="):
                        vidid = f[2:]
            elif "youtu.be" in url.netloc:
                vidid = url.path
            if vidid:
                return "https://img.youtube.com/vi/{0}/0.jpg".format(vidid)
            else: return "about:blank"
        else: return self.thumbdir()
    
    @property
    def thumb_article(self): return self.thumbdir("article_thumbs")
                    

# Reference for the following (and previous):
# http://docs.sqlalchemy.org/en/latest/orm/relationships.html#rows-that-point-to-themselves-mutually-dependent-rows

class Rating(Base):
    __tablename__ = 'ratings'
    id = Column(Integer, primary_key=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship("User", backref='ratings')
    article_id = Column(Integer, ForeignKey('articles.id'), nullable=False)
    rating = Column(Integer)

class Article(Base):
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, nullable=False)
    author_id = Column(Integer, ForeignKey('users.id'))
    author = relationship("User", backref='articles')
    media_id = Column(Integer, ForeignKey('media.id', use_alter=True, name="fk_media"))
    media = relationship("Media", backref='assigned_article', primaryjoin=media_id==Media.id, post_update=True, uselist=False)
    all_media = relationship("Media", primaryjoin=id==Media.article_id, backref="article")
    rating_id = Column(Integer, ForeignKey('ratings.id', use_alter=True, name="fk_rating"))
    rating = relationship("Rating", backref='assigned_article', primaryjoin=rating_id==Rating.id, post_update=True, uselist=False)
    ratings = relationship("Rating", primaryjoin=id==Rating.article_id, backref="article")
    timestamp = Column(DateTime, nullable=False, index=True)
    published = Column(Boolean, nullable=False)
    title = Column(Unicode(256), nullable=False)
    text = Column(UnicodeText, nullable=False)
    f2p = Column(Boolean)
    year = Column(Integer)
    views = Column(Integer, default=0, nullable=False)
    labels = relationship("Label", 
                secondary=articles_labels, backref="articles")
    is_article=True
    @property
    def url(self):
        u = "/articles/"+str(self.id)+"-"+self.title.replace(" ", "_").lstrip("/").replace("/", "_")
        return u
    
    @property
    def images(self):
        return session.query(Media).filter(Media.article == self, Media.type == "image").all()
        
    @property
    def videos(self):
        return session.query(Media).filter(Media.article == self, Media.type == "video").all()
    
    @property
    def rateable(self): return self.rating != None

class Reaction(Base):
    __tablename__ = 'reactions'
    id = Column(Integer, primary_key=True, nullable=False)
    article_id = Column(Integer, ForeignKey('articles.id'))
    article = relationship("Article", backref='reactions')
    author_id = Column(Integer, ForeignKey('users.id'))
    author = relationship("User", backref='reactions')
    media_id = Column(Integer, ForeignKey('media.id'))
    media = relationship("Media", backref='reactions')
    rating_id = Column(Integer, ForeignKey('ratings.id'))
    rating = relationship("Rating", backref='assigned_reaction')
    timestamp = Column(DateTime, nullable=False, index=True)
    text = Column(UnicodeText, nullable=False)
    is_reaction=True
    @property
    def url(self):
        return "/reactions/"+str(self.id)

class ShoutboxPost(Base):
    __tablename__ = 'shoutbox_posts'
    id = Column(Integer, primary_key=True, nullable=False)
    author_id = Column(Integer, ForeignKey('users.id', use_alter=True, name="fk_author"))
    author = relationship("User", backref='shoutbox_posts', primaryjoin=author_id==User.id, post_update=True)
    last_read_by = relationship("User", primaryjoin=id==User.last_post_read_id, backref="last_post_read")
    timestamp = Column(DateTime, nullable=False, index=True)
    text = Column(UnicodeText, nullable=False)

if __name__ == "__main__":
    if raw_input('Drop all? ').strip().lower().startswith('y'):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        # It would be REALLY nice if we could use some sane ids here..  but we
        # must reserve ids 1 through 4 for old z10p authors, and MySQL
        # won't allow id=0.  Yay.
        root = User(id=5, name=u"Root", password=u"df515bb71d7cc77e1287d9b94110aded391e5d202bfb98baba10b7ad", rights=9, gender="-", timestamp=datetime.utcnow(), laststamp=datetime.utcnow()) # The password is "root"
        session.add(root)
    Base.metadata.create_all(bind=engine)
    
    if raw_input('Import stuff? ').strip().lower().startswith('y'):
        import csv
        u = csv.reader(open('tmp/users.csv', 'rb'), delimiter=',', quotechar='"')
        for row in u:
            id_users, name, password, rights, minipic = row
            user = User(id=int(id_users), name=name, password="FIXME", minipic=minipic, rights=int(rights), timestamp=0, laststamp=0)
            session.add(user)
            print(user.name)
        
        l = csv.reader(open('tmp/labels.csv', 'rb'), delimiter=',', quotechar='"')
        for row in l:
            id_labels, id_users, name, icon, hidden, platform, deleted = row
            if deleted=="0" and hidden=="0":
                label = Label(id=int(id_labels), name=name, category={"0":'other', '1':'platform', '2':'genre'}[platform], user_id=int(id_users))
                session.add(label)
                print(label.name)

        a = csv.reader(open('tmp/articles.csv', 'rb'), delimiter=',', quotechar='"', doublequote=False, escapechar='\\')
        for row in a:
            #print(row)
            id_articles, id_users, date, title, text, image_display, image_url, image_alt, image_title, rating, f2p = row
            article = Article(id=int(id_articles), author_id=int(id_users), timestamp=datetime.fromtimestamp(int(date)), title=title, text=text, f2p=bool(int(f2p)) if f2p != "-1" else None, published=True)
            if int(rating) != 0:
                article.rating = Rating(rating=int(rating), user_id=int(id_users), article=article)
            if int(image_display):
                url = "/static/old/"+os.path.basename(image_url)
                media = Media(author_id=int(id_users), article=article, title=image_title, timestamp=datetime.fromtimestamp(int(date)), type="image", url=url)
                article.media = media
            session.add(article)
            print(article.title)
        
        print ("*"*32)
        print ("COMMITTING STEP 1")
        session.commit()
        
        al = csv.reader(open('tmp/articles_labels.csv', 'rb'), delimiter=',', quotechar='"', doublequote=False, escapechar='\\')
        for row in al:
            id_articles_labels, id_articles, id_labels, date = row
            article = session.query(Article).filter_by(id=int(id_articles)).scalar()
            label = session.query(Label).filter_by(id=int(id_labels)).scalar()
            if label and article:
                article.labels.append(label)
        
        print ("Aaaand done.")
        session.commit()
