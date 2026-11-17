from tortoise import fields
from tortoise.models import Model
from uuid import UUID
from tortoise.contrib.pydantic import pydantic_model_creator, pydantic_queryset_creator
from pydantic import ConfigDict, SkipValidation, field_serializer, BaseModel
from enum import StrEnum


class ConnectionPrecedence(StrEnum):
    ACTIVE = 'Active'
    BACKUP = 'Backup'
    LAST_RESORT = 'Last Resort'

class ConnectionRole(StrEnum):
    HUB = 'Hub'
    SPOKE = 'Spoke'

class Mesh(Model):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
    uid = fields.UUIDField(primary_key=True)
    name = fields.CharField(unique=True, max_length=32)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

MeshCreateMixin = pydantic_model_creator(Mesh,exclude=("uid","created_at","updated_at",))
MeshOutput = pydantic_model_creator(Mesh)
MeshListOutput = pydantic_queryset_creator(Mesh)

class Site(Model): 
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
    uid = fields.UUIDField(primary_key=True)
    nickname = fields.CharField(unique=True, max_length=4)
    description = fields.TextField(null=True)
    mesh = fields.ForeignKeyField('models.Mesh', related_name='sites')
    asn = fields.BigIntField()
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    routers: fields.ReverseRelation["Router"]

SiteCreateMixin = pydantic_model_creator(Site,exclude=("uid","mesh","created_at","updated_at",))
SiteOutput = pydantic_model_creator(Site)
SiteListOutput = pydantic_queryset_creator(Site)

class Router(Model): 
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
    uid = fields.UUIDField(primary_key=True)
    name = fields.CharField(null=True, max_length=32)
    description = fields.TextField(null=True)
    authkey = fields.BinaryField(null=True)
    otp = fields.BinaryField(null=True)
    site: fields.ForeignKeyRelation[Site] = fields.ForeignKeyField(Site, related_name='routers')
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

RouterCreateMixin = pydantic_model_creator(Router,exclude=("uid","site","authkey","otp","created_at","updated_at",))
RouterListOutput = pydantic_queryset_creator(Router, exclude=("authkey","otp",))
RouterOutput = pydantic_model_creator(Router, exclude=("authkey","otp",))

class RouterRegisterMixin(BaseModel):
    otp: str
    authkey: str
    name: str
    description: str = None

class RouterRegisterOutput(BaseModel): 
    mesh: MeshOutput
    site: SiteOutput
    router: RouterOutput

class Connection(Model):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
    uid = fields.UUIDField(primary_key=True)
    name = fields.CharField(null=True, max_length=32)
    isp = fields.CharField(null=True, max_length=64)
    ipv4 = fields.CharField(null=True, max_length=15)
    ipv6 = fields.CharField(null=True, max_length=39)
    precedence = fields.data.CharEnumField(ConnectionPrecedence, default=ConnectionPrecedence.ACTIVE)
    role = fields.data.CharEnumField(ConnectionRole, default=ConnectionRole.HUB)
    router = fields.ForeignKeyField('models.Router', related_name='connections')
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

class Tunnel(Model):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
    id = fields.IntField(primary_key=True)
    psk = fields.BinaryField(null=True)
    a_connection = fields.ForeignKeyField('models.Router', related_name='a_tunnels')
    a_wg_port = fields.IntField(null=True)
    a_wg_pubkey = fields.BinaryField(null=True)
    a_peer_ipv4 = fields.CharField(null=True, max_length=15)
    a_peer_ipv6 = fields.CharField(null=True, max_length=39)
    b_connection = fields.ForeignKeyField('models.Router', related_name='b_tunnels')
    b_wg_port = fields.IntField(null=True)
    b_wg_pubkey = fields.BinaryField(null=True)
    b_peer_ipv4 = fields.CharField(null=True, max_length=15)
    b_peer_ipv6 = fields.CharField(null=True, max_length=39)
