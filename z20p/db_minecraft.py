# encoding: utf-8
from datetime import datetime
import time
import os.path

from sqlalchemy import create_engine, or_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker, relationship, backref
from sqlalchemy.schema import Column, ForeignKey, Table
from sqlalchemy.types import DateTime, Integer, Unicode, Enum, UnicodeText, Boolean, TypeDecorator, Float

engine = create_engine(open("db_mc").read(), encoding="utf8", pool_size = 100, pool_recycle=4200) # XXX
# pool_recycle is to prevent "server has gone away"
session = scoped_session(sessionmaker(bind=engine, autoflush=False))

Base = declarative_base(bind=engine)

### Yonder tables

class HawkeyePlayer(Base):
    __tablename__ = 'hawk_players'
    __singlename__ = 'hawk_player'
    player_id = Column(Integer, primary_key=True, nullable=False)
    player = Column(Unicode(255))
    
    
    @property
    def joins(self):
        return session.query(HawkeyeAction).filter(HawkeyeAction.action == 5, HawkeyeAction.player_id == self.player_id).order_by(HawkeyeAction.timestamp).all()
    @property
    def blocks_placed(self):
        return session.query(HawkeyeAction).filter(HawkeyeAction.action == 1, HawkeyeAction.player_id == self.player_id).count()
    @property
    def blocks_destroyed(self):
        return session.query(HawkeyeAction).filter(HawkeyeAction.action == 0, HawkeyeAction.player_id == self.player_id).count()
    @property
    def death_count(self):
        return session.query(HawkeyeAction).filter(or_(HawkeyeAction.action == 12, HawkeyeAction.action == 21, HawkeyeAction.action == 22, ), HawkeyeAction.player_id == self.player_id).count()
    @property
    def mob_kills(self):
        return session.query(HawkeyeAction).filter(HawkeyeAction.action == 36, HawkeyeAction.player_id == self.player_id).count()
    @property
    def chat_lines(self):
        return session.query(HawkeyeAction).filter(HawkeyeAction.action == 3, HawkeyeAction.player_id == self.player_id).count()

class HawkeyeWorld(Base):
    __tablename__ = 'hawk_worlds'
    __singlename__ = 'hawk_world'

    world_id = Column(Integer, primary_key=True, nullable=False)
    world = Column(Unicode(255), nullable=False)

class HawkeyeAction(Base):
    __tablename__ = 'hawkeye'
    __singlename__ = 'hawk_actions'
    data_id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    player_id = Column(Integer, ForeignKey('hawk_players.player_id'), nullable=False)
    player = relationship("HawkeyePlayer")
    action = Column(Integer, nullable=False) # enum
    world_id = Column(Integer, ForeignKey('hawk_worlds.world_id'), nullable=False)
    world = relationship("HawkeyeWorld")
    x = Column(Integer, nullable=False)
    y = Column(Integer, nullable=False)
    z = Column(Integer, nullable=False)
    data = Column(Unicode(500))
    plugin = Column(Unicode(255))

