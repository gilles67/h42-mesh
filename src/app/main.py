from fastapi import FastAPI
from .models.mesh import db_engine, create_tables


engine = db_engine()

app = FastAPI()


@app.on_event("startup")
def on_startup():
    create_tables(engine)

@app.get("/")
def root():
    return {'hello': 'world'}
