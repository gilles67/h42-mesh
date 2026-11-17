import typer
import os
import base64
from rich import print
from ecdsa import SigningKey, NIST384p
import requests
import hashlib
from pydantic import BaseModel
from pydantic import Base64Bytes
import config 

app = typer.Typer()

@app.command("status") 
def status():
    conf = config.ClientConfiguration.load()
    if conf is None: 
        print("No configuration found, please start with register command")
        return 1

    print(f"Mesh joined:\n")
    for id,mesh in enumerate(conf.meshes):
        default = "*" if id == 0 else ""
        print(f"[ {id} ] {mesh.name} {default}")
        site = mesh.GetSite(mesh.my_site)
        print(f"      Site: {site.nickname}")
        print(f"      ASN: {site.asn}")
        router = site.GetRouter(mesh.my_router)
        print(f"      Router: {router.name}")

class RegisterRouterMixin(BaseModel): 
    otp: str
    authkey: str
    name: str
    description: str = None

@app.command("register")
def mesh_register(coordinator_url: str, register_otp: str):
    # Open Configuration
    conf = config.ClientConfiguration.load()
    if conf is not None and len(conf.meshes) > 0: 
        print("Abort mesh confiugation already exists !")
        return 1

    conf = config.ClientConfiguration()
    #Build Mesh configuration
    sk = SigningKey.generate(curve=NIST384p)
    
    query = RegisterRouterMixin(otp=register_otp, authkey=sk.verifying_key.to_pem(), name=os.uname().nodename)
    r = requests.post(f"{coordinator_url}/api/v1/router/otp/register", json=query.model_dump(exclude_unset=True))

    if r.status_code != 200: 
        print("Abort somethings wrong with the coordinator server.")
        return 1    
    robj = r.json()

    mesh = config.MeshConfiguration().model_validate(robj["mesh"])
    mesh.url = coordinator_url
    mesh.authkey = sk.to_pem()
    mesh.my_site = robj["site"]["uid"]
    mesh.my_router = robj["router"]["uid"]
    

    print(f"Welcome to {mesh.name} mesh network.")

    site = config.SiteConfiguration().model_validate(robj["site"])
    mesh.sites = [site,]
    print(site.model_dump())

    router = config.RouterConfiguration().model_validate(robj["router"])
    site.routers = [router,]
    print(router.model_dump())

    conf.meshes = [mesh]
    conf.save()

if __name__ == "__main__":
    app()