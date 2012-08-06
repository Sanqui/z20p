from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.schema import Column, ForeignKey, Table
from sqlalchemy.types import DateTime, Integer, Unicode, Enum, UnicodeText

engine = create_engine(open("z20p/db").read(), encoding="utf8") # XXX
session = scoped_session(sessionmaker(bind=engine, autoflush=False))

Base = declarative_base(bind=engine)


### Yonder tables

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, nullable=False)
    name = Column(Unicode(64), nullable=False)
    password = Column(Unicode(128))
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

class Article(Base):
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, nullable=False)
    author_id = Column(Integer, ForeignKey('users.id'))
    author = relationship("User", backref='articles')
    timestamp = Column(DateTime, nullable=False, index=True)
    title = Column(Unicode(256), nullable=False)
    text = Column(UnicodeText, nullable=False)
    image_url = Column(Unicode(256))
    image_title = Column(Unicode(256))
    rating = Column(Integer)
    labels = relationship("Label", 
                secondary=articles_labels, backref="articles")
    

if __name__ == "__main__":
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
