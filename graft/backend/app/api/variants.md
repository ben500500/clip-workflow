# backend/app/api/variants.py

- VariantGenerateRequest · class · L41-L45 — class VariantGenerateRequest(BaseModel)
- VariantBindRequest · class · L48-L50 — class VariantBindRequest(BaseModel)
- _get_thresholds · function · L53-L63 — async def _get_thresholds() -> dict
- _list_variant_groups · function · L66-L101 — async def _list_variant_groups() -> list[dict]
- variant_matrix · function · L105-L111 — async def variant_matrix( current_user: Annotated[User, Depends(get_current_user)] = None, )
- variant_detail · function · L115-L150 — async def variant_detail( variant_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, )
- generate_variants · function · L154-L171 — async def generate_variants( data: VariantGenerateRequest, current_user: Annotated[User, Depends(get_current_user)] = None, )
- verify_variant · function · L175-L190 — async def verify_variant( variant_id: str, current_user: Annotated[User, Depends(get_current_user)] = None, )
- bind_variant_account · function · L194-L216 — async def bind_variant_account( variant_id: str, data: VariantBindRequest, current_user: Annotated[User, Depends(get_current_user)] = None, )
- update_thresholds · function · L220-L239 — async def update_thresholds( data: dict, current_user: Annotated[User, Depends(get_current_user)] = None, )
- uuid_of · function · L242-L247 — def uuid_of(v: str)
