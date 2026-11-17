import os
from pydantic_core import from_json
from pydantic import HttpUrl
from pydantic import BaseModel
from pydantic import ConfigDict
from uuid import UUID
from typing import List, Optional, Tuple

class RouterConfiguration(BaseModel):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
    uid: UUID = None
    name: str = None 
    description: str = None

class SiteConfiguration(BaseModel):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
    uid: UUID = None
    nickname: str = None
    description: str = None
    asn: int = None
    routers: Optional[List[RouterConfiguration]] = None

    def GetRouter(self, router_uid:UUID):
        for router in self.routers:
            if router.uid == router_uid: 
                return router
        return None

class MeshConfiguration(BaseModel):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
    uid: UUID = None
    name: str = None 
    description: str = None

    url: HttpUrl = None
    authkey: bytes = None
    my_site: UUID = None
    my_router: UUID = None
    mesh_id: int = 0

    sites: Optional[List[SiteConfiguration]] = None

    def GetSite(self, site_uid:UUID): 
        for site in self.sites: 
            if site.uid == site_uid: 
                return site
        return None


class ClientConfiguration(BaseModel):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    meshes: Optional[List[MeshConfiguration]] = None

    def save(self):
        if not os.path.isdir(ClientConfiguration.getFolder()):
            os.makedirs(ClientConfiguration.getFolder(), mode=0o700)
        filename = os.path.join(ClientConfiguration.getFolder(), "configuration.json")
        with open(filename, "w") as file:
            file.write(self.model_dump_json(indent=2, exclude_none=True))
            file.close()

    @classmethod
    def getFolder(cls): 
        if (os.getuid() == 0):
            return "/etc/h42/mesh"
        else:
            return os.path.expanduser("~/.h42/mesh")

    @classmethod
    def load(cls):
        obj = None
        if not os.path.isdir(cls.getFolder()):
            return obj
        filename = os.path.join(ClientConfiguration.getFolder(), "configuration.json")
        if not os.path.isfile(filename):
            return obj
        with open(filename) as file:
            obj = cls.model_validate(from_json(file.read()))
            file.close()
        return obj


