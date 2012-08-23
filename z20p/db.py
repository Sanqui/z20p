from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.schema import Column, ForeignKey, Table
from sqlalchemy.types import DateTime, Integer, Unicode, Enum, UnicodeText

engine = create_engine(open("db").read(), encoding="utf8", pool_size = 100, pool_recycle=7200) # XXX
# pool_recycle is to prevent "server has gone away"
session = scoped_session(sessionmaker(bind=engine, autoflush=False))

Base = declarative_base(bind=engine)


### Yonder tables

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, nullable=False)
    name = Column(Unicode(64), nullable=False)
    password = Column(Unicode(128))
    rights = Column(Integer)
    gender = Column(Enum('m', 'f', '-'))
    minipic = Column(Unicode(256))


class Label(Base):
    __tablename__ = 'labels'

    id = Column(Integer, primary_key=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship("User")
    name = Column(Unicode(256), nullable=False)
    category = Column(Enum('platform', 'genre', 'other'))

articles_labels = Table('article_labels', Base.metadata,
    Column('article_id', Integer, ForeignKey('articles.id')),
    Column('label_id', Integer, ForeignKey('labels.id'))
)

class Media(Base):
    __tablename__ = 'media'
    id = Column(Integer, primary_key=True, nullable=False)
    author_id = Column(Integer, ForeignKey('users.id'))
    author = relationship("User", backref='media')
    title = Column(Unicode(256), nullable=False)
    url = Column(Unicode(256), nullable=False)
    type = Column(Enum("image", "video"))

class Article(Base):
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, nullable=False)
    author_id = Column(Integer, ForeignKey('users.id'))
    author = relationship("User", backref='articles')
    media_id = Column(Integer, ForeignKey('media.id'))
    media = relationship("Media", backref='article')
    timestamp = Column(DateTime, nullable=False, index=True)
    title = Column(Unicode(256), nullable=False)
    text = Column(UnicodeText, nullable=False)
    year = Column(Integer)
    rating = Column(Integer)
    labels = relationship("Label", 
                secondary=articles_labels, backref="articles")
    

if __name__ == "__main__":
    if raw_input('Drop all? ').strip().lower().startswith('y'):
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    root = User(id=0, name=u"Root", password=u"df515bb71d7cc77e1287d9b94110aded391e5d202bfb98baba10b7ad", rights=9, gender="-")
    session.add(root)
    session.commit()
