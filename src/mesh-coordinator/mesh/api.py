from fastapi import FastAPI, Response 
from fastapi import APIRouter
import uvicorn
from tortoise.contrib.fastapi import register_tortoise
import models
from uuid import UUID
import random
import hashlib 
import base64


app = FastAPI()

register_tortoise(
    app,
    db_url="sqlite://db.sqlite3",
    modules={"models": ["models"]},
    generate_schemas=True,
    add_exception_handlers=True,
)

router_api_v1 = APIRouter(prefix="/api/v1")
app.include_router(router_api_v1)

@app.get("/")
async def index():
    return {"Do something!"}

@router_api_v1.get("/mesh", response_model=models.MeshListOutput)
async def list_mesh(): 
    return await models.MeshListOutput.from_queryset(models.Mesh.all())

@router_api_v1.post("/mesh/create", response_model=models.MeshOutput)
async def create_mesh(mesh_obj: models.MeshCreateMixin): 
    return await models.MeshOutput.from_tortoise_orm(await models.Mesh.create(**mesh_obj.dict(exclude_unset=True)))

@router_api_v1.get("/mesh/{mesh_id}/site", response_model=models.SiteListOutput)
async def list_site(mesh_id:UUID): 
    return await models.SiteListOutput.from_queryset(models.Site.filter(mesh=mesh_id))

@router_api_v1.post("/mesh/{mesh_id}/site/create", response_model=models.SiteOutput)
async def create_site(mesh_id:UUID, site_obj: models.SiteCreateMixin): 
    mesh = await models.Mesh.get(uid=mesh_id)
    return await models.SiteOutput.from_tortoise_orm(await models.Site.create(mesh=mesh,**site_obj.dict(exclude_unset=True)))

@router_api_v1.delete("/site/{site_id}")
async def delete_site(site_id:UUID):
    await models.Site.get(uid=site_id).delete()
    return {}

@router_api_v1.get("/site/{site_id}/router", response_model=models.RouterListOutput)
async def list_router(site_id:UUID): 
    return await models.RouterListOutput.from_queryset(models.Router.filter(site=site_id))

@router_api_v1.post("/site/{site_id}/router/create", response_model=models.RouterOutput)
async def create_router(site_id:UUID, router_obj: models.RouterCreateMixin): 
    site = await models.Site.get(uid=site_id)
    return await models.RouterOutput.from_tortoise_orm(await models.Router.create(site=site,**router_obj.dict(exclude_unset=True)))

@router_api_v1.get("/router/{router_id}/otp/generate")
async def router_generate_otp(router_id:UUID):
    router = await models.Router.get(uid=router_id)
    otp = random.randbytes(64)
    router.otp = hashlib.sha256(otp).digest()
    router.authkey = None
    await router.save()
    sotp = base64.urlsafe_b64encode(otp).decode("utf-8")
    return {"otp": sotp , "cmd": f"uv run meshcli/meshcli.py register http://localhost:8000 {sotp}"}

@router_api_v1.post("/router/otp/register", response_model=models.RouterRegisterOutput)
async def router_otp_register(router_obj: models.RouterRegisterMixin):
    otp = base64.urlsafe_b64decode(router_obj.otp)
    hotp = hashlib.sha256(otp).digest()
    router = await models.Router.get(otp=hotp)
    site = await router.site.get()
    mesh = await site.mesh.get()
    router.otp = None 
    router.authkey = router_obj.authkey.encode("utf-8")
    if router.name != router_obj.name: 
        router.name = router_obj.name
    if router_obj.description is not None: 
        router.description = router_obj.description
    await router.save()
    router_py = await models.RouterOutput.from_tortoise_orm(router)
    site_py = await models.SiteOutput.from_tortoise_orm(site)
    mesh_py = await models.MeshOutput.from_tortoise_orm(mesh)
    return models.RouterRegisterOutput(router=router_py,site=site_py,mesh=mesh_py)


if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1",port= 8000, reload=True)