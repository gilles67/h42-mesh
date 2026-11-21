// Short names for the types of the API, taken from the generated schema.d.ts.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Mesh = Schemas["MeshRead"];
export type Site = Schemas["SiteRead"];
export type Router = Schemas["RouterRead"];
export type Connection = Schemas["ConnectionRead"];
export type ConnectionRole = Schemas["ConnectionRole"];
export type DirectMode = Schemas["DirectMode"];
export type AccessLevel = Schemas["MeshAccessLevel"];
export type EnrollmentToken = Schemas["EnrollmentTokenCreated"];
