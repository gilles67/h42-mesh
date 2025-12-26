from uuid import UUID, uuid4
from sqlmodel import Field, SQLModel, create_engine

class Mesh(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    uuid: UUID = Field(default_factory=uuid4, index=True)
    name: str = Field(index=True)

class Router(SQLModel, table=True):
    __tablename__ = "mesh_router"
    id: int | None = Field(default=None, primary_key=True)
    uuid: UUID = Field(default_factory=uuid4, index=True)
    asn: int = Field(default=4200000000)
    hostname: str = Field(index=True)

class WanInterface(SQLModel, table=True):
    __tablename__ = "mesh_router_wan_interface"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field()
    provider: str = Field()
    media: str = Field()
    order: int = Field(default=0)
    backup: bool = Field(default=False)
    ipv4: str = Field()
    ipv6: str = Field()
    vrf: int = Field()
    router_id: int | None = Field(default=None, foreign_key="mesh_router.id")

def db_engine(): 
    sqlite_file_name = "database.db"
    sqlite_url = f"sqlite:///{sqlite_file_name}"

    connect_args = {"check_same_thread": False}
    engine = create_engine(sqlite_url, echo=True, connect_args=connect_args)
    return engine

def create_tables(engine):
     SQLModel.metadata.create_all(engine)

