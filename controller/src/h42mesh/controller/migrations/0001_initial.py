from tortoise import migrations
from tortoise.migrations import operations as ops
from h42mesh.controller.models.enums import ConnectionKind, ConnectionRole, SiteKind
from tortoise.fields.base import OnDelete
from uuid import uuid4
from tortoise import fields

class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name='Site',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('name', fields.CharField(unique=True, max_length=64)),
                ('kind', fields.CharEnumField(description='HOME: home\nRELAY: relay', enum_type=SiteKind, max_length=16)),
                ('number', fields.IntField(unique=True)),
                ('asn', fields.BigIntField(unique=True)),
            ],
            options={'table': 'site', 'app': 'models', 'pk_attr': 'id', 'table_description': 'A home (``home``) or a VPS (``relay``), with its private AS.'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='Router',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('site', fields.ForeignKeyField('models.Site', source_field='site_id', db_constraint=True, to_field='id', related_name='routers', on_delete=OnDelete.CASCADE)),
                ('name', fields.CharField(max_length=64)),
                ('router_id_address', fields.CharField(unique=True, max_length=15)),
                ('wireguard_public_key', fields.CharField(null=True, unique=True, max_length=44)),
                ('signing_public_key', fields.CharField(null=True, unique=True, max_length=44)),
                ('signing_key_enabled', fields.BooleanField(default=True)),
                ('enrolled_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
            ],
            options={'table': 'router', 'app': 'models', 'unique_together': (('site', 'name'),), 'pk_attr': 'id', 'table_description': "A site's router. Private keys never leave the router."},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='EnrollmentToken',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('router', fields.ForeignKeyField('models.Router', source_field='router_id', db_constraint=True, to_field='id', related_name='enrollment_tokens', on_delete=OnDelete.CASCADE)),
                ('token_hash', fields.CharField(unique=True, max_length=64)),
                ('expires_at', fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ('used_at', fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
            ],
            options={'table': 'enrollment_token', 'app': 'models', 'pk_attr': 'id', 'table_description': 'Single-use enrollment token, bound to a declared router.'},
            bases=['BaseModel'],
        ),
        ops.CreateModel(
            name='InternetConnection',
            fields=[
                ('id', fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True)),
                ('created_at', fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ('updated_at', fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ('router', fields.ForeignKeyField('models.Router', source_field='router_id', db_constraint=True, to_field='id', related_name='connections', on_delete=OnDelete.CASCADE)),
                ('name', fields.CharField(max_length=64)),
                ('role', fields.CharEnumField(description='ACTIVE: active\nBACKUP: backup', enum_type=ConnectionRole, max_length=16)),
                ('priority', fields.IntField(null=True)),
                ('direct_ipv4', fields.BooleanField(default=False)),
                ('direct_ipv6', fields.BooleanField(default=False)),
                ('ipv4_port_min', fields.IntField(null=True)),
                ('ipv4_port_max', fields.IntField(null=True)),
                ('metered', fields.BooleanField(default=False)),
                ('kind', fields.CharEnumField(default=ConnectionKind.OTHER, description='FIBER: fiber\nDSL: dsl\nCABLE: cable\nLTE: 4g\nNR: 5g\nSTARLINK: starlink\nOTHER: other', enum_type=ConnectionKind, max_length=16)),
            ],
            options={'table': 'internet_connection', 'app': 'models', 'unique_together': (('router', 'name'),), 'pk_attr': 'id', 'table_description': "A router's internet connection. Addresses are discovered by the agent."},
            bases=['BaseModel'],
        ),
    ]
