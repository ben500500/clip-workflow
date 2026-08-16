# backend/app/api/maintenance.py

- ArchiveRequest · class · L25-L26 — class ArchiveRequest(BaseModel)
- CleanupRequest · class · L29-L30 — class CleanupRequest(BaseModel)
- MaintenanceStatusResponse · class · L33-L36 — class MaintenanceStatusResponse(BaseModel)
- run_archive · function · L40-L48 — async def run_archive( req: ArchiveRequest, current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], )
- run_cleanup · function · L52-L60 — async def run_cleanup( req: CleanupRequest, current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], )
- run_minio_lifecycle · function · L64-L71 — async def run_minio_lifecycle( current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], )
- maintenance_status · function · L75-L85 — async def maintenance_status( current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], )
